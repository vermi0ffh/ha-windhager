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


class WindhagerDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Windhager data."""

    def __init__(self, hass, client, entry):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.client = client
        self.entry = entry
        self.consecutive_timeouts = 0

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Starting data update from Windhager device")
            async with async_timeout.timeout(20):
                data = await self.client.fetch_all()
                self.consecutive_timeouts = 0
                return data
        except asyncio.TimeoutError as err:
            self.consecutive_timeouts += 1
            _LOGGER.warning(
                "Timeout fetching data from %s after 20 seconds (attempt %d)",
                self.entry.data["host"],
                self.consecutive_timeouts,
            )
            if self.consecutive_timeouts >= 3:
                raise UpdateFailed(
                    f"Multiple consecutive timeouts communicating with API: {err}"
                ) from err
            # Return last known good data if available
            return self.data if self.data else None
        except Exception as err:
            _LOGGER.error(
                "Error fetching data from %s: %s", self.entry.data["host"], str(err)
            )
            raise UpdateFailed(f"Error communicating with API: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up windhager integration from a config entry."""
    _LOGGER.info("Setting up Windhager integration for %s", entry.data["host"])

    hass.data.setdefault(DOMAIN, {})

    client = WindhagerHttpClient(
        host=entry.data["host"],
        password=entry.data["password"],
    )

    coordinator = WindhagerDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_scan_system(call):
        for key in hass.data[DOMAIN].keys():
            await hass.data[DOMAIN][key].client.full_system_scan()

    if not hass.services.has_service(DOMAIN, "full_system_scan"):
        hass.services.async_register(DOMAIN, "full_system_scan", handle_scan_system)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Windhager integration for %s", entry.data["host"])

    if hass.services.has_service(DOMAIN, "full_system_scan"):
        hass.services.async_remove(DOMAIN, "full_system_scan")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.client.close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok