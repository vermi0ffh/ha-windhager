"""Diagnostics for the Windhager Heater integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .client import WindhagerHttpClient
from .coordinator import WindhagerConfigEntry

_LOGGER = logging.getLogger(__name__)

# The MAC address that discovery stores in the entry identifies the heater as its host does
TO_REDACT = {CONF_HOST, CONF_MAC, CONF_PASSWORD}


@dataclass
class ApiScan:
    """A full scan of the heater's API, run in the background."""

    started_at: datetime
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.finished_at is None:
            return {
                "status": "running",
                "started_at": self.started_at.isoformat(),
                "hint": "Download the diagnostics again once the log says the scan has finished",
            }
        return {
            "status": "done",
            "started_at": self.started_at.isoformat(),
            "duration_s": round((self.finished_at - self.started_at).total_seconds(), 1),
            **(self.result or {}),
        }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WindhagerConfigEntry
) -> dict[str, Any]:
    """The entry, the data the entities read, and a full scan of the heater's API.

    The scan takes longer than the 30 s for which Home Assistant signs the download link
    (its requests go one after the other): on 2026-10-28, about 100 s for 63 requests, two
    of them timing out after 20 s; a phone used the link after 70 s, refused, and nothing
    downloaded. So the first download starts
    the scan in the background, and the following ones hold its result, kept until the
    entry is reloaded.
    """
    coordinator = entry.runtime_data
    if coordinator.api_scan is None:
        coordinator.api_scan = ApiScan(started_at=dt_util.utcnow())
        entry.async_create_background_task(
            hass, _async_scan(entry, coordinator.api_scan), "windhager API scan"
        )

    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "coordinator_data": coordinator.data,
        "scan": coordinator.api_scan.as_dict(),
    }


async def _async_scan(entry: WindhagerConfigEntry, scan: ApiScan) -> None:
    # A client of its own: the scan's many requests do not share the coordinator's
    # session and digest authentication state
    client = WindhagerHttpClient(entry.data[CONF_HOST], entry.data[CONF_PASSWORD])
    try:
        scan.result = await client.scan()
    # The scan records its failed requests; anything else ends it, still reported
    except Exception as err:
        scan.result = {"error": repr(err)}
    finally:
        await client.close()
    scan.finished_at = dt_util.utcnow()
    _LOGGER.info(
        "Windhager API scan finished in %.0f s: download the diagnostics again to get it",
        (scan.finished_at - scan.started_at).total_seconds(),
    )
