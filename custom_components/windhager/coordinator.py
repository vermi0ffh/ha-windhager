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

# A poll's timeout follows the requests it makes, one after the other: 0.26 s each on
# average and up to 0.56 s for one, on a BioWIN 2 with five circuits on 2026-11-05 (77
# requests, 16.4 and 20.0 s a poll), so 0.5 s each leaves room. A fixed 20 s made that
# heater's polls time out, its entities unavailable 28 times in three days
POLL_TIMEOUT_PER_REQUEST_S = 0.5
# Never less than before, for a small heater whose few requests may each be slow
POLL_TIMEOUT_MIN_S = 20
# The first poll also discovers the modules, so its size is unknown beforehand: on that
# heater about 98 requests (≈ 25 s), which a 20 s timeout turned into a setup retrying for good
FIRST_POLL_TIMEOUT_S = 120


def poll_timeout(requests: int | None) -> float:
    """The timeout of a poll making `requests` requests; None before discovery."""
    if requests is None:
        return FIRST_POLL_TIMEOUT_S
    return max(POLL_TIMEOUT_MIN_S, POLL_TIMEOUT_PER_REQUEST_S * requests)


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
        # The heater's texts of its enumerated values, by "group/member" then code
        # (client.fetch_enum_texts)
        self.enum_texts: dict[str, dict[str, str]] = {}

    def _reset_interval(self) -> None:
        """Back to the usual interval once the heater answers."""
        self.consecutive_failures = 0
        self.update_interval = timedelta(seconds=UPDATE_INTERVAL)

    def _back_off(self) -> None:
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
            self._back_off()
            raise
        if self.consecutive_timeouts:
            # A timeout that keeps the last values is still a poll the heater did not answer
            self._back_off()
        else:
            self._reset_interval()
        return data

    async def _fetch(self):
        """The raw poll, which keeps the last values on the first timeouts."""
        timeout = poll_timeout(self.client.requests_next_poll())
        try:
            _LOGGER.debug("Starting data update from Windhager device")
            async with asyncio.timeout(timeout):
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
                "Timeout fetching data from %s after %.0f seconds (attempt %d)",
                self.entry.data["host"],
                timeout,
                self.consecutive_timeouts,
            )
            if self.data is None or self.consecutive_timeouts >= 3:
                # Nothing to keep yet (the first refresh at start): a failure, so
                # that Home Assistant retries the setup instead of setting the
                # platforms up without any device. After three, the heater is lost.
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="timeout",
                    translation_placeholders={"host": self.entry.data["host"], "seconds": f"{timeout:.0f}"},
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
