"""Support for Windhager Climate."""

from __future__ import annotations
import logging
from typing import Optional

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .coordinator import WindhagerConfigEntry
from .entity import WindhagerEntity, async_add_module_entities
from .const import DOMAIN
from .exceptions import CannotConnect, InvalidAuth, WriteFailed
from .helpers import get_oid_value

_LOGGER = logging.getLogger(__name__)

# One write at a time to the heater: its API answers the requests one after the other
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: WindhagerConfigEntry, async_add_entities
) -> None:
    """Set up Windhager climates from a config entry, and those of a circuit added later."""
    coordinator = entry.runtime_data

    def climates_of(device_info: dict) -> list[WindhagerBaseThermostat]:
        if device_info.get("type") != "climate":
            return []
        return [
            WindhagerThermostatClimate(coordinator, device_info),
            WindhagerThermostatClimateWithoutBias(coordinator, device_info),
        ]

    async_add_module_entities(entry, async_add_entities, climates_of)


class WindhagerBaseThermostat(WindhagerEntity, ClimateEntity):
    """Base class for Windhager thermostats."""

    def __init__(self, coordinator, device_info: dict):
        """Initialize the thermostat."""
        super().__init__(coordinator, device_info)
        self.client = self.coordinator.client
        self._prefix = device_info.get("prefix", "")
        self._preset_modes = ["0", "1", "2", "3", "4", "5", "6", "7"]
        # Not named in the translations: the climate takes its circuit's name
        self._attr_translation_key = "windhager_climate"

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def target_temperature_step(self) -> float:
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def hvac_mode(self) -> str:
        """Return hvac operation mode."""
        return HVACMode.HEAT

    @property
    def hvac_modes(self) -> list[str]:
        """Return the list of available hvac operation modes."""
        return [HVACMode.HEAT, HVACMode.OFF]

    @property
    def preset_modes(self) -> list[str]:
        """Return a list of available preset modes."""
        return self._preset_modes

    def get_oid_value(self, path: str, default: str = "0") -> Optional[float]:
        """Get OID value with error handling."""
        return get_oid_value(self.coordinator, path, self._prefix, default)

    def raw_selected_mode(self) -> Optional[int]:
        """Get raw selected mode value."""
        return int(self.get_oid_value("/0/3/50/0") or 0)

    def raw_custom_temp_remaining_time(self) -> Optional[int]:
        """Get raw custom temperature remaining time."""
        return int(self.get_oid_value("/0/2/10/0") or 0)

    def raw_preset_mode(self) -> Optional[int]:
        """Get raw preset mode."""
        return self.raw_selected_mode()

    @property
    def hvac_action(self) -> str:
        """Return the current running hvac operation."""
        if self.raw_preset_mode() == 0:
            return HVACAction.OFF
        return HVACAction.HEATING

    @property
    def preset_mode(self) -> Optional[str]:
        """Return the current preset mode."""
        if self.raw_custom_temp_remaining_time() > 0:
            return self._preset_modes[7]
        mode = self.raw_preset_mode()
        return self._preset_modes[mode] if mode is not None else None

    async def _async_write(self, path: str, value: str) -> None:
        """Write a datapoint of the circuit; a failure is an error the user sees."""
        try:
            await self.client.update(f"{self._prefix}{path}", value)
        except InvalidAuth as err:
            # As when polling: Home Assistant asks the user for the new password
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_auth_failed"
            ) from err
        except WriteFailed as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_refused",
                translation_placeholders={"status": str(err.status)},
            ) from err
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_cannot_connect"
            ) from err

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        id_mode = self._preset_modes.index(preset_mode)
        await self._async_write("/0/3/50/0", str(id_mode))

        if self.raw_custom_temp_remaining_time() > 0:
            await self._async_write("/0/2/10/0", "0")
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        # Home Assistant refuses a range (target_temp_low / high) before calling it: the
        # entity does not support TARGET_TEMPERATURE_RANGE
        temp = kwargs[ATTR_TEMPERATURE]
        await self._async_write("/0/3/4/0", str(temp))
        await self._async_write("/0/2/10/0", "400")
        await self.coordinator.async_request_refresh()

    async def set_current_temp_compensation(self, compensation: float) -> None:
        """Set the temperature compensation value."""
        # The circuit's own correction: both climates of a circuit write the same one (the
        # action targets either of them)
        await self._async_write("/0/3/58/0", str(compensation))
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        # Implement if needed
        pass


class WindhagerThermostatClimate(WindhagerBaseThermostat):
    """Windhager climate with temperature bias."""

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        current = self.get_oid_value("/0/0/1/0")
        bias = self.get_oid_value("/0/3/58/0")

        if current is None or bias is None:
            return None

        return current - bias

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        target = self.get_oid_value("/0/1/1/0")
        bias = self.get_oid_value("/0/3/58/0")

        if target is None or bias is None:
            return None

        return target - bias


class WindhagerThermostatClimateWithoutBias(WindhagerBaseThermostat):
    """Windhager climate without temperature bias."""

    def __init__(self, coordinator, device_info: dict):
        """Initialize the thermostat."""
        device_info = device_info.copy()
        device_info["id"] = f"{device_info.get('id', '')}_nobias"
        super().__init__(coordinator, device_info)
        self._attr_translation_key = "windhager_climate_without_bias"

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.get_oid_value("/0/0/1/0")

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.get_oid_value("/0/1/1/0")
