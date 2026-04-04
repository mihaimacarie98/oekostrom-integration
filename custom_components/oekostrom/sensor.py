"""Sensor platform for oekostrom AG integration."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OekostromCoordinator


@dataclass(frozen=True, kw_only=True)
class OekostromSensorDescription(SensorEntityDescription):
    """Describe an oekostrom sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _get_product_field(acc_data: dict, field: str) -> Any:
    """Get a field from the first product."""
    products = acc_data.get("products", [])
    if products:
        return products[0].get(field)
    return None


def _get_installment_field(acc_data: dict, field: str) -> Any:
    """Get a field from installment data."""
    inst = acc_data.get("installments", {})
    return inst.get(field)


def _get_dashboard_field(acc_data: dict, key: str, field: str) -> Any:
    """Get a field from a dashboard section."""
    dashboard = acc_data.get("dashboard", {})
    section = dashboard.get(key, {})
    if isinstance(section, dict):
        return section.get(field)
    return None


def _parse_date(value: str | None) -> datetime.date | None:
    """Parse DD.MM.YYYY to a date object for HA date sensor."""
    if not value:
        return None
    try:
        parts = value.split(".")
        if len(parts) == 3:
            return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        pass
    return None


ACCOUNT_SENSORS: tuple[OekostromSensorDescription, ...] = (
    OekostromSensorDescription(
        key="product",
        translation_key="product",
        icon="mdi:lightning-bolt",
        value_fn=lambda d: _get_product_field(d, "ProductDesc"),
        attr_fn=lambda d: {
            "metering_code": _get_product_field(d, "MeteringCode"),
            "supply_start": _get_product_field(d, "SupplyStart"),
            "binding_period": _get_product_field(d, "BindingPeriod"),
            "grid_operator": _get_product_field(d, "GriDesc"),
            "cancelation_period": _get_product_field(d, "CancelationPeriod"),
            "price_guarantee": _get_product_field(d, "PriceGuaranteedate"),
            "discount_info": _get_product_field(d, "DiscountInfo"),
            "conditions": _get_product_field(d, "Conditions"),
            "load_profile": _get_product_field(d, "LprSDesc"),
            "profile_type": _get_product_field(d, "MprProfileTypeDesc"),
            "energy_voucher": _get_product_field(d, "EnergyVoucher"),
        },
    ),
    OekostromSensorDescription(
        key="energy_price",
        translation_key="energy_price",
        icon="mdi:currency-eur",
        native_unit_of_measurement="ct/kWh",
        suggested_display_precision=2,
        value_fn=lambda d: _get_product_field(d, "PriceEnergyGross"),
    ),
    OekostromSensorDescription(
        key="base_price",
        translation_key="base_price",
        icon="mdi:currency-eur",
        native_unit_of_measurement="EUR/month",
        suggested_display_precision=2,
        value_fn=lambda d: _get_product_field(d, "PriceBasicGross"),
    ),
    OekostromSensorDescription(
        key="energy_price_net",
        translation_key="energy_price_net",
        icon="mdi:currency-eur",
        native_unit_of_measurement="ct/kWh",
        suggested_display_precision=2,
        value_fn=lambda d: _get_product_field(d, "PriceEnergyNet"),
    ),
    OekostromSensorDescription(
        key="base_price_net",
        translation_key="base_price_net",
        icon="mdi:currency-eur",
        native_unit_of_measurement="EUR/month",
        suggested_display_precision=2,
        value_fn=lambda d: _get_product_field(d, "PriceBasicNet"),
    ),
    OekostromSensorDescription(
        key="account_state",
        translation_key="account_state",
        icon="mdi:check-circle",
        value_fn=lambda d: d.get("info", {}).get("AccState"),
        attr_fn=lambda d: {
            "account_number": d.get("info", {}).get("AccNo"),
            "account_type": d.get("info", {}).get("AccType"),
            "address": (
                f"{d.get('info', {}).get('AccStreetAndHno', '')}, "
                f"{d.get('info', {}).get('AccZipAndCity', '')}"
            ),
            "smart_meter": d.get("info", {}).get("AccSMART"),
            "spot_tariff": d.get("info", {}).get("AccSPOT"),
        },
    ),
    OekostromSensorDescription(
        key="next_installment",
        translation_key="next_installment",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _parse_date(
            _get_installment_field(d, "ScoNextInstallment")
        ),
    ),
    OekostromSensorDescription(
        key="installment_amount",
        translation_key="installment_amount",
        icon="mdi:cash",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda d: _get_installment_field(d, "ScoAmount"),
        attr_fn=lambda d: {
            "monthly": _get_installment_field(d, "ScoMonthly"),
            "valid_to": _get_installment_field(d, "ScoValidTo"),
            "updateable": _get_installment_field(d, "ScoUpdateable"),
        },
    ),
    OekostromSensorDescription(
        key="metering_code",
        translation_key="metering_code",
        icon="mdi:meter-electric",
        value_fn=lambda d: _get_product_field(d, "MeteringCode"),
    ),
    OekostromSensorDescription(
        key="supply_status",
        translation_key="supply_status",
        icon="mdi:transmission-tower",
        value_fn=lambda d: _get_product_field(d, "Status"),
    ),
    OekostromSensorDescription(
        key="smart_meter_status",
        translation_key="smart_meter_status",
        icon="mdi:meter-electric-outline",
        value_fn=lambda d: d.get("smart_meter", {}).get("Status"),
    ),
    OekostromSensorDescription(
        key="bonus_points",
        translation_key="bonus_points",
        icon="mdi:star-circle",
        value_fn=lambda d: d.get("bonus_points", {}).get("ShowBlockBonusPoints"),
        attr_fn=lambda d: {
            "status": d.get("bonus_points", {}).get("Status"),
            "items": len(d.get("bonus_points", {}).get("CusInfoList", [])),
        },
    ),
    OekostromSensorDescription(
        key="referral_bonus",
        translation_key="referral_bonus",
        icon="mdi:account-group",
        value_fn=lambda d: _get_dashboard_field(d, "FWF", "Info"),
        attr_fn=lambda d: {
            "headline": _get_dashboard_field(d, "FWF", "Headline"),
            "description": _get_dashboard_field(d, "FWF", "Description"),
        },
    ),
    OekostromSensorDescription(
        key="contract_start",
        translation_key="contract_start",
        icon="mdi:calendar-start",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _parse_date(
            _get_product_field(d, "SupplyStart")
        ),
    ),
    OekostromSensorDescription(
        key="price_guarantee",
        translation_key="price_guarantee",
        icon="mdi:shield-check",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _parse_date(
            _get_product_field(d, "PriceGuaranteedate")
        ),
    ),
    OekostromSensorDescription(
        key="binding_period",
        translation_key="binding_period",
        icon="mdi:calendar-lock",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _parse_date(
            _get_product_field(d, "BindingPeriod")
        ),
    ),
    OekostromSensorDescription(
        key="grid_operator",
        translation_key="grid_operator",
        icon="mdi:transmission-tower",
        value_fn=lambda d: _get_product_field(d, "GriDesc"),
    ),
    OekostromSensorDescription(
        key="invoice_count",
        translation_key="invoice_count",
        icon="mdi:receipt-text",
        value_fn=lambda d: len(d.get("invoices", [])),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up oekostrom sensors from a config entry."""
    coordinator: OekostromCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[OekostromSensor] = []

    for acc_id in coordinator.data.get("accounts", {}):
        acc_info = coordinator.data["accounts"][acc_id]["info"]
        for description in ACCOUNT_SENSORS:
            entities.append(
                OekostromSensor(
                    coordinator=coordinator,
                    description=description,
                    acc_id=acc_id,
                    acc_info=acc_info,
                    entry_id=entry.entry_id,
                )
            )

    async_add_entities(entities)


class OekostromSensor(CoordinatorEntity[OekostromCoordinator], SensorEntity):
    """Representation of an oekostrom sensor."""

    entity_description: OekostromSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OekostromCoordinator,
        description: OekostromSensorDescription,
        acc_id: int,
        acc_info: dict[str, Any],
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._acc_id = acc_id
        acc_no = acc_info.get("AccNo", acc_id)
        acc_type = acc_info.get("AccType", "Energy")

        self._attr_unique_id = f"{entry_id}_{acc_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(acc_id))},
            name=f"oekostrom {acc_type} {acc_no}",
            manufacturer="oekostrom AG",
            model=acc_type,
        )

    @property
    def _acc_data(self) -> dict[str, Any]:
        """Return account data from coordinator."""
        return self.coordinator.data.get("accounts", {}).get(self._acc_id, {})

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self._acc_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.attr_fn:
            return self.entity_description.attr_fn(self._acc_data)
        return None
