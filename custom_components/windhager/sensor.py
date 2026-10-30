"""Support for Windhager Climate."""

from __future__ import annotations
import logging
from typing import Any

from homeassistant.const import (
    UnitOfTemperature,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant

from .coordinator import WindhagerConfigEntry
from .entity import WindhagerEntity
from .helpers import parse_value, get_oid_value

_LOGGER = logging.getLogger(__name__)

# Read only, from the coordinator's data: no limit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities
) -> None:
    """Set up WindHager lights from a config entry."""
    data_coordinator = entry.runtime_data

    entities = []

    for deviceInfo in data_coordinator.data.get("devices"):
        if deviceInfo.get("type") == "temperature":
            entity = WindhagerTemperatureSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif deviceInfo.get("type") == "sensor":
            entity = WindhagerGenericSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif deviceInfo.get("type") == "error":
            entity = WindhagerErrorSensor(data_coordinator, deviceInfo)
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


class WindhagerBaseSensor(WindhagerEntity, SensorEntity):
    """Base class for Windhager sensors."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_info)
        self._oid = device_info.get("oid")

    def _get_oid_value(self, oid: str | None = None) -> Any | None:
        """Get value from coordinator data for given OID."""
        return get_oid_value(self.coordinator, oid or self._oid)


class WindhagerTemperatureSensor(WindhagerBaseSensor):
    """Temperature sensor implementation."""

    def __init__(self, coordinator: Any, device_info: dict) -> None:
        super().__init__(coordinator, device_info)
        self._correction_oid = device_info.get("correction_oid")

    # A measurement: Home Assistant keeps its long-term statistics
    _attr_state_class = SensorStateClass.MEASUREMENT

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


# The heater status codes the translations name: those of the InfoWIN Touch's
# res/xml/AufzaehlTexte_<language>.xml (2026-10-30)
HEATER_STATUSES = [str(code) for code in range(18)]


class WindhagerSelectSensor(WindhagerBaseSensor):
    """Select sensor implementation."""

    _attr_translation_key = "heater_status"
    # An enum: Home Assistant shows the translated status and offers the known
    # ones in the automation editor
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEATER_STATUSES

    @property
    def raw_value(self) -> int | None:
        return parse_value(self._get_oid_value(), int, self._oid)

    @property
    def native_value(self) -> str | None:
        raw_value = self.raw_value
        if raw_value is None:
            return None
        if str(raw_value) not in HEATER_STATUSES:
            _LOGGER.debug(
                "Unknown status value %s for sensor %s",
                raw_value,
                self.entity_id,
            )
            return None
        return str(raw_value)


# The error code's value without an error (2026-10-30: "-" before a fault, "42" during it)
NO_ERROR = "-"
# Home Assistant's limit for a state
MAX_STATE_LENGTH = 255


class WindhagerErrorSensor(WindhagerBaseSensor):
    """The heater's error: its code and the heater's own text for it, or none."""

    @property
    def _code(self) -> str | None:
        """The error code as the heater gives it: NO_ERROR without one, None if unknown."""
        return self.coordinator.data.get("oids", {}).get(self._oid)

    @property
    def native_value(self) -> str | None:
        code = self._code
        if code is None:
            return None
        if code == NO_ERROR:
            # Translated: "No error"
            return "none"
        text = self.coordinator.error_texts.get(code)
        return f"{code}: {text}"[:MAX_STATE_LENGTH] if text else code

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The code alone, for automations: the text depends on the heater's language."""
        code = self._code
        return {"code": parse_value(code, int, self._oid) if code not in (None, NO_ERROR) else None}
