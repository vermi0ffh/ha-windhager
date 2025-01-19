"""Support for Windhager Climate."""

from __future__ import annotations
import logging
from typing import Any

from homeassistant.const import (
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .helpers import parse_value, get_oid_value

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up WindHager lights from a config entry."""
    data_coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    for deviceInfo in data_coordinator.data.get("devices"):
        if deviceInfo.get("type") == "temperature":
            entity = WindhagerTemperatureSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif deviceInfo.get("type") == "sensor":
            entity = WindhagerGenericSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif deviceInfo.get("type") == "select":
            entity = WindhagerSelectSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif (
            deviceInfo.get("type") == "total"
            or deviceInfo.get("type") == "total_increasing"
        ):
            entity = WindhagerPelletSensor(data_coordinator, deviceInfo)
            entities.append(entity)

    async_add_entities(entities)


class WindhagerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Windhager sensors."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._id = device_info.get("id")
        self._name = device_info.get("name")
        self._oid = device_info.get("oid")
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, device_info.get("device_id"))},
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )

    @property
    def unique_id(self) -> str:
        """Return unique ID for sensor."""
        return self._id

    @property
    def name(self) -> str:
        """Return sensor name."""
        return self._name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self._device_info

    def _get_oid_value(self, oid: str | None = None) -> Any | None:
        """Get value from coordinator data for given OID."""
        return get_oid_value(self.coordinator, oid or self._oid)


class WindhagerTemperatureSensor(WindhagerBaseSensor):
    """Temperature sensor implementation."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        super().__init__(coordinator, device_info)
        self._correction_oid = device_info.get("correction_oid")

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        value = self._get_oid_value()

        if value is None:
            return None

        if self._correction_oid is not None:
            correction = self._get_oid_value(self._correction_oid)
            if correction is not None:
                value -= correction

        return value


class WindhagerGenericSensor(WindhagerBaseSensor):
    """Generic sensor implementation."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        super().__init__(coordinator, device_info)
        self._device_class = device_info.get("device_class")
        self._state_class = device_info.get("state_class")
        self._unit = device_info.get("unit")

    @property
    def device_class(self) -> str | None:
        return self._device_class

    @property
    def state_class(self) -> str | None:
        return self._state_class

    @property
    def native_value(self) -> float | None:
        return self._get_oid_value()

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._unit


class WindhagerPelletSensor(WindhagerBaseSensor):
    """Pellet sensor implementation."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        super().__init__(coordinator, device_info)
        self._state_class = device_info.get("type")

    @property
    def state_class(self) -> str | None:
        return self._state_class

    @property
    def native_value(self) -> float | None:
        return self._get_oid_value()

    @property
    def native_unit_of_measurement(self) -> str:
        return "t"


class WindhagerSelectSensor(WindhagerBaseSensor):
    """Select sensor implementation."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        super().__init__(coordinator, device_info)
        self._options = device_info.get("options")

    @property
    def raw_value(self) -> int | None:
        return parse_value(self._get_oid_value(), int, self._oid)

    @property
    def native_value(self) -> str | None:
        # TODO use translations to return the correct text for each language (e.g. "1" -> "Self-test"/"Autotest"...); remove the options value in client.py
        raw_value = self.raw_value
        if raw_value is None:
            return None
        return self._options[raw_value]
