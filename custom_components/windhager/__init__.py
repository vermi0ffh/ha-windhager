"""The Windhager Heater integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .client import WindhagerHttpClient
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up windhager integration from a config entry."""
    _LOGGER.info("Setting up Windhager integration for %s", entry.data["host"])

    hass.data.setdefault(DOMAIN, {})

    client = WindhagerHttpClient(
        host=entry.data["host"],
        password=entry.data["password"],
    )

    async def async_update_data():
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Starting data update from Windhager device")
            async with async_timeout.timeout(20):
                return await client.fetch_all()
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Timeout fetching data from %s after 20 seconds", entry.data["host"]
            )
            raise UpdateFailed(f"Timeout communicating with API: {err}") from err
        except Exception as err:
            _LOGGER.error(
                "Error fetching data from %s: %s", entry.data["host"], str(err)
            )
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
    )
    coordinator.client = client

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Windhager integration for %s", entry.data["host"])
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.client.close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
