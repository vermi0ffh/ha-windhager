"""The Windhager Heater integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import ConfigType

from .client import WindhagerHttpClient
from .const import DOMAIN
from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services, once for all its entries."""
    # Registered here rather than with the climates, so that they exist, and say
    # why they fail, even while no entry is loaded
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "set_current_temp_compensation",
        entity_domain=CLIMATE_DOMAIN,
        schema={
            vol.Required("compensation"): vol.All(
                vol.Coerce(float), vol.Range(min=-3.5, max=3.5)
            ),
        },
        func="set_current_temp_compensation",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WindhagerConfigEntry) -> bool:
    """Set up windhager integration from a config entry."""
    _LOGGER.info("Setting up Windhager integration for %s", entry.data["host"])

    client = WindhagerHttpClient(
        host=entry.data["host"],
        password=entry.data["password"],
    )

    coordinator = WindhagerDataUpdateCoordinator(hass, client, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # Home Assistant retries with a new client: close this one's session
        await client.close()
        raise

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: WindhagerConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Windhager integration for %s", entry.data["host"])
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.close()

    return unload_ok
