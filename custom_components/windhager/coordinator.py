"""The coordinator fetching the heater's values for all the entities."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .client import WindhagerHttpClient
from .const import DOMAIN, UPDATE_INTERVAL
from .exceptions import InvalidAuth

_LOGGER = logging.getLogger(__name__)

type WindhagerConfigEntry = ConfigEntry[WindhagerDataUpdateCoordinator]


class WindhagerDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Windhager data."""

    def __init__(
        self, hass: HomeAssistant, client: WindhagerHttpClient, entry: WindhagerConfigEntry
    ) -> None:
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
        # The diagnostics' API scan (diagnostics.ApiScan), started by the first download
        self.api_scan = None

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Starting data update from Windhager device")
            async with asyncio.timeout(20):
                data = await self.client.fetch_all()
                self.consecutive_timeouts = 0
                return data
        except InvalidAuth as err:
            # Home Assistant stops polling and asks the user for the new password
            raise ConfigEntryAuthFailed(str(err)) from err
        except asyncio.TimeoutError as err:
            self.consecutive_timeouts += 1
            _LOGGER.warning(
                "Timeout fetching data from %s after 20 seconds (attempt %d)",
                self.entry.data["host"],
                self.consecutive_timeouts,
            )
            if self.data is None:
                # Nothing to keep yet (the first refresh at start): a failure, so
                # that Home Assistant retries the setup instead of setting the
                # platforms up without any device
                raise UpdateFailed(f"Timeout communicating with API: {err}") from err
            if self.consecutive_timeouts >= 3:
                raise UpdateFailed(
                    f"Multiple consecutive timeouts communicating with API: {err}"
                ) from err
            # Keep the last known good data
            return self.data
        except Exception as err:
            _LOGGER.error(
                "Error fetching data from %s: %s", self.entry.data["host"], str(err)
            )
            raise UpdateFailed(f"Error communicating with API: {err}") from err
