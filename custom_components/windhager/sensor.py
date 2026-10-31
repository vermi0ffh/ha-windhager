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
from .entity import WindhagerEntity, async_add_module_entities
from .helpers import parse_value, get_oid_value

_LOGGER = logging.getLogger(__name__)

# Read only, from the coordinator's data: no limit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities
) -> None:
    """Set up the Windhager sensors from a config entry, and those of a module added later."""
    coordinator = entry.runtime_data

    def sensors_of(device_info: dict) -> list[WindhagerBaseSensor]:
        sensor_class = SENSOR_CLASSES.get(device_info.get("type"))
        return [sensor_class(coordinator, device_info)] if sensor_class else []

    async_add_module_entities(entry, async_add_entities, sensors_of)


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
        if str(raw_value) not in self.options:
            _LOGGER.debug(
                "Unknown status value %s for sensor %s",
                raw_value,
                self.entity_id,
            )
            return None
        return str(raw_value)


# The operating mode codes the translations name: those of the InfoWIN Touch's
# res/xml/AufzaehlTexte_<language>.xml (2026-10-31: 0 once switched off on the
# heater's screen, 5 once switched back on)
OPERATING_MODES = [str(code) for code in range(12)]


class WindhagerOperatingModeSensor(WindhagerSelectSensor):
    """The heater's operating mode: on, switched off on its screen, manual mode…"""

    _attr_translation_key = "operating_mode"
    _attr_options = OPERATING_MODES


# A heating circuit's operating mode codes the translations name: those of the InfoWIN
# Touch's res/xml/AufzaehlTexte_<language>.xml for group 2, member 9 (2026-10-31: 1
# Heizbetrieb on a heating circuit, 8 Standby Heizgrenze on one at its heating limit)
CIRCUIT_OPERATING_MODES = [str(code) for code in range(17)]


class WindhagerCircuitOperatingModeSensor(WindhagerSelectSensor):
    """A heating circuit's operating mode: heating, setback, standby at its heating limit…"""

    _attr_options = CIRCUIT_OPERATING_MODES


# The error code's value without an error (2026-10-30: "-" before a fault, "42" during it)
NO_ERROR = "-"
# Home Assistant's limit for a state
MAX_STATE_LENGTH = 255


# A heat pump's operating phase codes: its "Betriebsphase" enumerates 0 to 15 (the API's
# scan, 2026-10-31); the translations name those seen in the heater's app (3 Standby, 4
# Heizen), and Home Assistant shows the others as their code
HEAT_PUMP_PHASES = [str(code) for code in range(16)]


class WindhagerHeatPumpPhaseSensor(WindhagerSelectSensor):
    """A heat pump's operating phase: standby, heating…"""

    _attr_options = HEAT_PUMP_PHASES


# The SG Ready state codes: the datapoint enumerates 0 to 15 (the API's scan, 2026-10-31);
# the translations name SG Ready's four states, as the heater's app does ("Zustand 2")
SG_READY_STATES = [str(code) for code in range(16)]


class WindhagerSgReadySensor(WindhagerSelectSensor):
    """The SG Ready state the hybrid manager runs in: the signal of an energy manager."""

    _attr_options = SG_READY_STATES


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


# The sensor of each type the client describes
SENSOR_CLASSES: dict[str | None, type[WindhagerBaseSensor]] = {
    "temperature": WindhagerTemperatureSensor,
    "sensor": WindhagerGenericSensor,
    "error": WindhagerErrorSensor,
    "select": WindhagerSelectSensor,
    "operating_mode": WindhagerOperatingModeSensor,
    "circuit_operating_mode": WindhagerCircuitOperatingModeSensor,
    "heat_pump_phase": WindhagerHeatPumpPhaseSensor,
    "sg_ready_state": WindhagerSgReadySensor,
    "total": WindhagerPelletSensor,
    "total_increasing": WindhagerPelletSensor,
}
