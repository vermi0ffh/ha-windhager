"""Whether the heater has an error."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator
from .entity import WindhagerEntity, async_add_module_entities
from .helpers import parse_value
from .sensor import NO_ERROR

# Read only, from the coordinator's data: no limit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensors from a config entry, and those of a module listed later."""
    coordinator = entry.runtime_data
    async_add_module_entities(
        entry,
        async_add_entities,
        lambda device_info: (
            [sensor_class(coordinator, device_info)]
            if (sensor_class := BINARY_SENSOR_CLASSES.get(device_info.get("type")))
            else []
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


class WindhagerRunningSensor(WindhagerEntity, BinarySensorEntity):
    """On while a pump runs: a heating circuit's pump, or its hot water charging pump."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]) -> None:
        super().__init__(coordinator, device_info)
        self._oid = device_info.get("oid")

    @property
    def is_on(self) -> bool | None:
        # 0 when stopped; 100 while the circuit pump ran on 2026-10-31
        value = parse_value(self.coordinator.data.get("oids", {}).get(self._oid), float, self._oid)
        return None if value is None else value > 0


# The binary sensor of each type the client describes
BINARY_SENSOR_CLASSES: dict[str | None, type[BinarySensorEntity]] = {
    "problem": WindhagerProblemSensor,
    "running": WindhagerRunningSensor,
}
