"""Whether the heater has an error."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator
from .entity import WindhagerEntity, async_add_module_entities
from .sensor import NO_ERROR

# Read only, from the coordinator's data: no limit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the heater's problem sensor from a config entry, or once its module is listed."""
    coordinator = entry.runtime_data
    async_add_module_entities(
        entry,
        async_add_entities,
        lambda device_info: (
            [WindhagerProblemSensor(coordinator, device_info)] if device_info.get("type") == "problem" else []
        ),
    )


class WindhagerProblemSensor(WindhagerEntity, BinarySensorEntity):
    """On while the heater reports an error code: what an automation warning of a fault watches."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]) -> None:
        super().__init__(coordinator, device_info)
        self._oid = device_info.get("oid")

    @property
    def is_on(self) -> bool | None:
        code = self.coordinator.data.get("oids", {}).get(self._oid)
        return None if code is None else code != NO_ERROR
