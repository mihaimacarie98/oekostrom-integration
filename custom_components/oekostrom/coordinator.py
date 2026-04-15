"""Data coordinator for oekostrom AG integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OekostromApi, OekostromApiError, OekostromAuthError

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
            if not isinstance(account, dict) or "AccId" not in account:
                _LOGGER.debug("Skipping malformed account payload: %s", account)
                continue

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
                "notifications": {},
            }

            try:
                acc_data["products"] = await self.api.get_products(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get products for %s: %s", acc_id, err)

            try:
                acc_data["installments"] = await self.api.get_installments(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get installments for %s: %s", acc_id, err)

            try:
                acc_data["invoices"] = await self.api.get_invoices(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get invoices for %s: %s", acc_id, err)

            try:
                acc_data["invoice_summary"] = await self.api.get_invoice_summary(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get invoice summary for %s: %s", acc_id, err)

            try:
                acc_data["price_infos"] = await self.api.get_price_infos(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get price infos for %s: %s", acc_id, err)

            try:
                acc_data["dashboard"] = await self.api.get_dashboard(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get dashboard for %s: %s", acc_id, err)

            try:
                acc_data["smart_meter"] = await self.api.get_smart_meter(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get smart meter for %s: %s", acc_id, err)

            try:
                acc_data["bonus_points"] = await self.api.get_bonus_point_data(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get bonus points for %s: %s", acc_id, err)

            try:
                acc_data["load_profile_widget"] = await self.api.get_load_profile_widget(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get load profile for %s: %s", acc_id, err)

            try:
                acc_data["notifications"] = await self.api.get_new_notifications(acc_id)
            except OekostromApiError as err:
                _LOGGER.debug("Failed to get notifications for %s: %s", acc_id, err)

            data["accounts"][acc_id] = acc_data

        return data
