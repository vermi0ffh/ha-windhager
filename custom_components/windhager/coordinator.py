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
from .const import DOMAIN, MAX_UPDATE_INTERVAL, UPDATE_INTERVAL
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
        # Failed polls in a row, whatever the error: each one doubles the wait before the next poll
        self.consecutive_failures = 0
        # The diagnostics' API scan (diagnostics.ApiScan), started by the first download
        self.api_scan = None
        # The heater's texts of its error codes, by code (client.fetch_error_texts)
        self.error_texts: dict[str, str] = {}

    def _poll_again_soon(self) -> None:
        """Back to the usual interval once the heater answers."""
        self.consecutive_failures = 0
        self.update_interval = timedelta(seconds=UPDATE_INTERVAL)

    def _poll_again_later(self) -> None:
        """Wait twice as long after each failed poll, up to MAX_UPDATE_INTERVAL.

        The InfoWIN Touch handles one request at a time: polled every minute while it restarts or is
        busy, it gets no rest to recover.
        """
        self.consecutive_failures += 1
        seconds = min(UPDATE_INTERVAL * 2**self.consecutive_failures, MAX_UPDATE_INTERVAL)
        self.update_interval = timedelta(seconds=seconds)
        _LOGGER.debug("Next poll of %s in %d seconds", self.entry.data["host"], seconds)

    async def _async_update_data(self):
        """Fetch data from API endpoint, polling less often while the heater does not answer."""
        try:
            data = await self._fetch()
        except UpdateFailed:
            self._poll_again_later()
            raise
        if self.consecutive_timeouts:
            # A timeout that keeps the last values is still a poll the heater did not answer
            self._poll_again_later()
        else:
            self._poll_again_soon()
        return data

    async def _fetch(self):
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Starting data update from Windhager device")
            async with asyncio.timeout(20):
                data = await self.client.fetch_all()
                self.consecutive_timeouts = 0
                return data
        except InvalidAuth as err:
            # Home Assistant stops polling and asks the user for the new password
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"host": self.entry.data["host"]},
            ) from err
        except asyncio.TimeoutError as err:
            self.consecutive_timeouts += 1
            # Debug: the coordinator logs once when the heater is lost, and once back
            _LOGGER.debug(
                "Timeout fetching data from %s after 20 seconds (attempt %d)",
                self.entry.data["host"],
                self.consecutive_timeouts,
            )
            if self.data is None or self.consecutive_timeouts >= 3:
                # Nothing to keep yet (the first refresh at start): a failure, so
                # that Home Assistant retries the setup instead of setting the
                # platforms up without any device. After three, the heater is lost.
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="timeout",
                    translation_placeholders={"host": self.entry.data["host"]},
                ) from err
            # Keep the last known good data
            return self.data
        except Exception as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={
                    "host": self.entry.data["host"],
                    "error": str(err),
                },
            ) from err
