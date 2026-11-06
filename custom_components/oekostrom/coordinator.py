"""Data coordinator for oekostrom AG integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OekostromApi, OekostromApiError, OekostromAuthError
from .const import DOMAIN
from .statistics import (
    async_add_statistics,
    async_get_last_statistic,
    create_statistics_points,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=1)


class OekostromCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch data from oekostrom AG portal."""

    def __init__(self, hass: HomeAssistant, api: OekostromApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="oekostrom",
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self._statistics_store = Store(hass, 1, f"{DOMAIN}_statistics")
        self._rebuilt_statistics: set[str] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the API."""
        try:
            return await self._fetch_all()
        except OekostromAuthError:
            _LOGGER.debug("Session expired, re-authenticating")
            try:
                await self.api.authenticate()
                return await self._fetch_all()
            except OekostromAuthError as auth_err:
                raise ConfigEntryAuthFailed(str(auth_err)) from auth_err
            except OekostromApiError as api_err:
                raise UpdateFailed(
                    f"Re-authentication failed: {api_err}"
                ) from api_err
        except OekostromApiError as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err

    async def _fetch_all(self) -> dict[str, Any]:
        """Fetch all relevant data for all accounts."""
        user_data = self.api.user_data
        if not user_data:
            raise UpdateFailed("No user data available")

        accounts = user_data.get("AccountIds", [])
        data: dict[str, Any] = {
            "user": user_data,
            "accounts": {},
        }

        for account in accounts:
            acc_id = account["AccId"]
            acc_data: dict[str, Any] = {
                "info": account,
                "products": [],
                "installments": {},
                "invoices": [],
                "invoice_summary": {},
                "price_infos": {},
                "dashboard": {},
                "smart_meter": {},
                "bonus_points": {},
                "load_profile_widget": {},
                "load_profile": {},
                "notifications": {},
            }

            try:
                acc_data["products"] = await self.api.get_products(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get products for %s: %s", acc_id, err)

            try:
                acc_data["installments"] = await self.api.get_installments(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get installments for %s: %s", acc_id, err)

            try:
                acc_data["invoices"] = await self.api.get_invoices(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get invoices for %s: %s", acc_id, err)

            try:
                acc_data["invoice_summary"] = await self.api.get_invoice_summary(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get invoice summary for %s: %s", acc_id, err)

            try:
                acc_data["price_infos"] = await self.api.get_price_infos(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get price infos for %s: %s", acc_id, err)

            try:
                acc_data["dashboard"] = await self.api.get_dashboard(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get dashboard for %s: %s", acc_id, err)

            try:
                acc_data["smart_meter"] = await self.api.get_smart_meter(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get smart meter for %s: %s", acc_id, err)

            try:
                acc_data["bonus_points"] = await self.api.get_bonus_point_data(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get bonus points for %s: %s", acc_id, err)

            try:
                acc_data["load_profile_widget"] = await self.api.get_load_profile_widget(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get load profile for %s: %s", acc_id, err)

            try:
                acc_data["notifications"] = await self.api.get_new_notifications(acc_id)
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get notifications for %s: %s", acc_id, err)

            # Fetch and store power consumption data
            try:
                acc_data["load_profile"] = await self._fetch_and_store_load_profile(
                    acc_id
                )
            except OekostromAuthError:
                raise
            except OekostromApiError as err:
                _LOGGER.debug("Failed to fetch load profile data for %s: %s", acc_id, err)
                acc_data["load_profile"] = {"status": "error", "error": str(err)}

            data["accounts"][acc_id] = acc_data

        return data

    async def _fetch_and_store_load_profile(self, acc_id: int) -> dict[str, Any]:
        """Fetch load profile (15min consumption) and store new data only.

        On the first run, fetch the full available consumption period. Later
        updates resume from the last stored interval.
        """
        frequencies = await self.api.get_settlement_frequencies(acc_id)

        consumption_periods: list[tuple[dict[str, Any], datetime, datetime]] = []
        for period in frequencies:
            if "verbrauch" not in str(period.get("INFO", "")).casefold():
                continue
            try:
                start = datetime.strptime(period["BDATE"], "%d.%m.%Y")
                end = datetime.strptime(period["EDATE"], "%d.%m.%Y")
            except (KeyError, TypeError, ValueError):
                continue
            if start <= end:
                consumption_periods.append((period, start, end))

        if not consumption_periods:
            _LOGGER.debug("No consumption period found for account %s", acc_id)
            return {"status": "no_consumption_period"}

        period, period_start, period_end = max(
            consumption_periods,
            key=lambda item: item[2],
        )
        statistic_id = f"oekostrom:consumption_15min_{acc_id}"
        if self._rebuilt_statistics is None:
            stored_data = await self._statistics_store.async_load()
            self._rebuilt_statistics = set(
                stored_data.get("rebuilt_statistics", [])
                if stored_data
                else []
            )
        rebuild_statistics = statistic_id not in self._rebuilt_statistics
        last_statistic = (
            None
            if rebuild_statistics
            else await async_get_last_statistic(self.hass, statistic_id)
        )
        last_stat_time = (
            last_statistic.get("start")
            if last_statistic and isinstance(last_statistic.get("start"), datetime)
            else None
        )
        initial_sum = (
            float(last_statistic.get("sum") or 0)
            if last_statistic
            else 0.0
        )

        start_date = period_start
        if last_stat_time:
            last_stat_local = dt_util.as_local(last_stat_time)
            if last_stat_local.date() > period_end.date():
                start_date = period_end
            elif last_stat_local.date() >= period_start.date():
                start_date = last_stat_local

        b_date = start_date.strftime("%d.%m.%Y")
        e_date = period["EDATE"]
        _LOGGER.debug(
            "Fetching load profile for account %s from %s to %s",
            acc_id,
            b_date,
            e_date,
        )

        # Get load profile data
        load_profile_data = await self.api.get_load_profile(acc_id, b_date, e_date)

        if not isinstance(load_profile_data, list) or len(load_profile_data) == 0:
            _LOGGER.debug("No load profile data received for account %s", acc_id)
            return {"status": "no_data"}

        profile = next(
            (
                item
                for item in load_profile_data
                if isinstance(item, dict) and isinstance(item.get("data"), list)
            ),
            None,
        )
        data_points = profile.get("data", []) if profile else []

        if not data_points:
            _LOGGER.debug("No data points in load profile for account %s", acc_id)
            return {"status": "no_data"}

        latest_point = next(
            (
                point
                for point in reversed(data_points)
                if (
                    isinstance(point, (list, tuple))
                    and len(point) >= 3
                    and isinstance(point[2], (int, float))
                    and math.isfinite(point[2])
                )
            ),
            None,
        )
        latest_consumption = (
            float(latest_point[2]) if latest_point is not None else None
        )

        # Filter out points that are older than last stored timestamp
        filtered_points = data_points
        if last_stat_time:
            filtered_points = [
                p for p in data_points
                if (
                    isinstance(p, (list, tuple))
                    and len(p) >= 3
                    and isinstance(p[1], (int, float))
                    and p[1] >= last_stat_time.timestamp() + 3600
                )
            ]
            _LOGGER.debug(
                "Filtered to %d new data points (out of %d total)",
                len(filtered_points),
                len(data_points),
            )

        if not filtered_points:
            _LOGGER.debug("No new data points since last update for account %s", acc_id)
            return {
                "status": "up_to_date",
                "last_consumption_kwh": latest_consumption,
            }

        # Convert to statistics format and store
        stat_id, stats_points = create_statistics_points(
            filtered_points,
            statistic_suffix=f"consumption_15min_{acc_id}",
            initial_sum=initial_sum,
            first_hour_timestamp=(
                int(last_stat_time.timestamp()) + 3600 if last_stat_time else None
            ),
        )

        if not stats_points:
            return {
                "status": "waiting_for_complete_hour",
                "last_consumption_kwh": latest_consumption,
            }

        if rebuild_statistics:
            _LOGGER.debug("Rebuilding stored statistics for account %s", acc_id)

        _LOGGER.debug(
            "Storing %d new statistics points for account %s",
            len(stats_points),
            acc_id,
        )

        await async_add_statistics(self.hass, stat_id, stats_points)
        if rebuild_statistics:
            self._rebuilt_statistics.add(statistic_id)
            await self._statistics_store.async_save(
                {"rebuilt_statistics": sorted(self._rebuilt_statistics)}
            )
        return {
            "status": "updated",
            "hours_added": len(stats_points),
            "last_consumption_kwh": latest_consumption,
        }
