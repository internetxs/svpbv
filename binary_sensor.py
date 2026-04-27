"""Binary sensor platform for SVP BV District Heating."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN
from . import SVPBVDataUpdateCoordinator


@dataclass
class SVPBVBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an SVP BV binary sensor."""
    value_fn: Callable[[dict[str, Any]], bool | None] | None = None


BINARY_SENSOR_DESCRIPTIONS: tuple[SVPBVBinarySensorEntityDescription, ...] = (
    SVPBVBinarySensorEntityDescription(
        key="has_smart_meter",
        name="Smart Meter Active",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:meter-electric",
        value_fn=lambda d: d.get("has_smart_meter"),
    ),
    SVPBVBinarySensorEntityDescription(
        key="connection_active",
        name="Connection Active",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:connection",
        value_fn=lambda d: d.get("connection_active"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SVP BV binary sensors from a config entry."""
    coordinator: SVPBVDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    async_add_entities(
        SVPBVBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class SVPBVBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Represents a single SVP BV binary sensor."""

    entity_description: SVPBVBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SVPBVDataUpdateCoordinator,
        entry: ConfigEntry,
        description: SVPBVBinarySensorEntityDescription,
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
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is active."""
        if self.coordinator.data is None:
            return None
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return self.coordinator.data.get(self.entity_description.key)
