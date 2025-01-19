"""Config flow for Windhager heater integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .client import WindhagerHttpClient
from .exceptions import CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("password"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    host = data["host"].strip().rstrip("/")

    # Remove any protocol prefix and additional paths if present
    if "://" in host:
        parsed = urlparse(host)
        host = parsed.netloc or parsed.path
    else:
        # Handle case where user just pasted a URL without protocol
        host = host.split("/")[0]

    # Remove any port number if present
    if ":" in host:
        host = host.split(":")[0]

    # Final cleanup of any remaining slashes or spaces
    host = host.strip("/")

    _LOGGER.info("Validating Windhager connection - Host: %s", host)

    try:
        client = WindhagerHttpClient(
            host=host,
            password=data["password"],
        )

        try:
            _LOGGER.debug("Testing connection by fetching root device info")
            await client.fetch("/1")
            _LOGGER.info("Successfully connected to Windhager device at %s", host)
        except Exception as err:
            _LOGGER.error("Connection test failed for %s: %s", host, str(err))
            raise CannotConnect from err
        finally:
            await client.close()

        return {
            "title": f"Windhager Heater ({host})",
            "host": host,  # Return the cleaned host
        }

    except Exception as err:
        _LOGGER.exception("Unexpected exception during validation: %s", str(err))
        raise CannotConnect from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for heater."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            _LOGGER.debug("Showing initial config flow form")
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        _LOGGER.debug("Attempting to validate config for host %s", user_input["host"])

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
            # Create a new dict with cleaned host value
            cleaned_data = {
                "host": info["host"],  # Use the cleaned host
                "password": user_input["password"],
            }
            return self.async_create_entry(title=info["title"], data=cleaned_data)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
