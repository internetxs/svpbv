"""Sensor platform for SVP BV District Heating."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN
from . import SVPBVDataUpdateCoordinator

# Months in Dutch (as returned by the API)
_MONTHS_NL = ["jan", "feb", "mrt", "apr", "mei", "jun",
               "jul", "aug", "sep", "okt", "nov", "dec"]


@dataclass
class SVPBVSensorEntityDescription(SensorEntityDescription):
    """Describes an SVP BV sensor."""
    value_fn: Callable[[dict[str, Any]], Any] | None = None


SENSOR_DESCRIPTIONS: tuple[SVPBVSensorEntityDescription, ...] = (
    SVPBVSensorEntityDescription(
        key="month_usage_gj",
        name="Heat Usage This Month",
        native_unit_of_measurement="GJ",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        value_fn=lambda d: d.get("month_usage_gj"),
    ),
    SVPBVSensorEntityDescription(
        key="total_gj",
        name="Heat Usage This Year",
        native_unit_of_measurement="GJ",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        value_fn=lambda d: d.get("total_gj"),
    ),
    SVPBVSensorEntityDescription(
        key="advance_amount_eur",
        name="Monthly Advance Payment",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:currency-eur",
        value_fn=lambda d: d.get("advance_amount_eur"),
    ),
    SVPBVSensorEntityDescription(
        key="customer_name",
        name="Customer Name",
        icon="mdi:account",
        value_fn=lambda d: d.get("customer_name"),
    ),
    SVPBVSensorEntityDescription(
        key="address",
        name="Address",
        icon="mdi:home",
        value_fn=lambda d: d.get("address"),
    ),
    SVPBVSensorEntityDescription(
        key="today_total_gj",
        name="Heat Usage Today",
        native_unit_of_measurement="GJ",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        value_fn=lambda d: d.get("today_total_gj"),
    ),
)

# Generate per-month sensors dynamically
_MONTH_SENSORS: list[SVPBVSensorEntityDescription] = []
for _month in _MONTHS_NL:
    _m = _month  # capture in closure

    def _month_value_fn(d: dict, m: str = _m) -> float | None:
        monthly = d.get("monthly", {})
        return monthly.get(m)

    _MONTH_SENSORS.append(
        SVPBVSensorEntityDescription(
            key=f"monthly_{_month}",
            name=f"Heat Usage {_month.capitalize()}",
            native_unit_of_measurement="GJ",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:fire",
            value_fn=_month_value_fn,
        )
    )

ALL_SENSORS = SENSOR_DESCRIPTIONS + tuple(_MONTH_SENSORS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SVP BV sensors from a config entry."""
    coordinator: SVPBVDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    async_add_entities(
        SVPBVSensor(coordinator, entry, description)
        for description in ALL_SENSORS
    )


class SVPBVSensor(CoordinatorEntity, SensorEntity):
    """Represents a single SVP BV sensor."""

    entity_description: SVPBVSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SVPBVDataUpdateCoordinator,
        entry: ConfigEntry,
        description: SVPBVSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="SVP BV District Heating",
            manufacturer="SVP BV",
            model="Customer Portal",
            configuration_url="https://mijn.svpbv.nl",
        )

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        if self.coordinator.data is None:
            return None
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "total_gj":
            attrs: dict[str, Any] = {}
            if "contract_start" in data:
                attrs["contract_start"] = data["contract_start"]
            if "contract_end" in data:
                attrs["contract_end"] = data["contract_end"]
            if "monthly" in data:
                attrs["monthly_breakdown"] = data["monthly"]
            return attrs
        if key == "today_total_gj" and "today_hourly" in data:
            return {"hourly_breakdown": data["today_hourly"]}
        return {}
