"""Statistics handling for power consumption data."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

_LOGGER = logging.getLogger(__name__)

STATISTICS_UNIT_KWH = UnitOfEnergy.KILO_WATT_HOUR


async def async_get_last_statistic(
    hass: HomeAssistant,
    statistic_id: str,
) -> dict[str, Any] | None:
    """Get the latest stored statistic point."""
    recorder = get_instance(hass)
    if not recorder:
        raise RuntimeError("Recorder is not available")

    statistics = await recorder.async_add_executor_job(
        get_last_statistics,
        hass,
        1,
        statistic_id,
        False,
        {"sum"},
    )
    statistic_points = statistics.get(statistic_id, [])
    if statistic_points:
        last_point = dict(statistic_points[-1])
        start = last_point.get("start")
        if isinstance(start, datetime):
            last_point["start"] = dt_util.as_utc(start)
        elif (
            isinstance(start, (int, float))
            and not isinstance(start, bool)
            and math.isfinite(start)
        ):
            last_point["start"] = dt_util.utc_from_timestamp(start)
        else:
            raise RuntimeError(
                f"Invalid start time for statistic {statistic_id}"
            )
        _LOGGER.debug(
            "Last statistic for %s: %s",
            statistic_id,
            last_point.get("start"),
        )
        return last_point

    _LOGGER.debug("No existing statistics found for %s", statistic_id)
    return None


async def async_add_statistics(
    hass: HomeAssistant,
    statistic_id: str,
    data_points: list[dict[str, Any]],
) -> None:
    """Add cumulative external statistics to Home Assistant."""
    valid_points: list[StatisticData] = []
    for point in data_points:
        start = point.get("start")
        total = point.get("sum")
        if (
            not isinstance(start, datetime)
            or start.tzinfo is None
            or not isinstance(total, (int, float))
            or not math.isfinite(total)
        ):
            _LOGGER.debug("Skipping invalid statistics point")
            continue
        valid_points.append({"start": start, "sum": float(total)})

    if not valid_points:
        _LOGGER.debug("No valid statistics points to store for %s", statistic_id)
        return

    metadata: StatisticMetaData = {
        "has_sum": True,
        "mean_type": StatisticMeanType.NONE,
        "name": "oekostrom hourly energy consumption",
        "source": "oekostrom",
        "statistic_id": statistic_id,
        "unit_class": EnergyConverter.UNIT_CLASS,
        "unit_of_measurement": STATISTICS_UNIT_KWH,
    }
    async_add_external_statistics(hass, metadata, valid_points)
    _LOGGER.debug(
        "Queued %d statistics points for %s",
        len(valid_points),
        statistic_id,
    )


def create_statistics_points(
    data: list[list[Any]],
    statistic_suffix: str = "consumption_15min",
    initial_sum: float = 0.0,
    first_hour_timestamp: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Aggregate complete hours, skipping gaps in 15-minute data."""
    statistic_id = f"oekostrom:{statistic_suffix}"
    hourly_intervals: dict[int, dict[int, float]] = {}

    for entry in data:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue

        try:
            timestamp_value = float(entry[1])
            consumption_kwh = float(entry[2])
            if (
                not math.isfinite(timestamp_value)
                or not math.isfinite(consumption_kwh)
                or not timestamp_value.is_integer()
            ):
                continue

            timestamp = int(timestamp_value)
            if timestamp % 900:
                continue
            hour_start = timestamp - timestamp % 3600
            intervals = hourly_intervals.setdefault(hour_start, {})
            intervals[timestamp] = intervals.get(timestamp, 0.0) + consumption_kwh
        except (OverflowError, TypeError, ValueError) as err:
            _LOGGER.debug("Failed to parse load profile point: %s", err)

    points: list[dict[str, Any]] = []
    running_sum = initial_sum
    expected_first_hour = (
        first_hour_timestamp - first_hour_timestamp % 3600
        if first_hour_timestamp is not None
        else None
    )

    for hour_start, intervals in sorted(hourly_intervals.items()):
        expected_timestamps = {hour_start + offset for offset in (0, 900, 1800, 2700)}
        if expected_first_hour is not None and hour_start < expected_first_hour:
            continue
        if not expected_timestamps.issubset(intervals):
            continue

        running_sum += sum(intervals[timestamp] for timestamp in expected_timestamps)
        points.append(
            {
                "start": dt_util.utc_from_timestamp(hour_start),
                "sum": running_sum,
            }
        )

    return statistic_id, points
