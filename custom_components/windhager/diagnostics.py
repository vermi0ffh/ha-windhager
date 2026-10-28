"""Diagnostics for the Windhager Heater integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .client import WindhagerHttpClient
from .const import DOMAIN

TO_REDACT = {CONF_HOST, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """The entry, the data the entities read, and a full scan of the heater's API."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # A client of its own: the scan's many requests do not share the coordinator's
    # session and digest authentication state
    client = WindhagerHttpClient(entry.data[CONF_HOST], entry.data[CONF_PASSWORD])
    try:
        scan = await client.scan()
    finally:
        await client.close()

    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "coordinator_data": coordinator.data,
        "scan": scan,
    }
