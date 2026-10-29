"""Config flow for Windhager heater integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
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
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required("password"): str})


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

    client = WindhagerHttpClient(
        host=host,
        password=data["password"],
    )
    try:
        _LOGGER.debug("Testing connection by fetching root device info")
        await client.fetch("/1")
        _LOGGER.info("Successfully connected to Windhager device at %s", host)
    except InvalidAuth:
        raise
    except Exception as err:
        _LOGGER.error("Connection test failed for %s: %s", host, str(err))
        raise CannotConnect from err
    finally:
        await client.close()

    return {
        "title": f"Windhager Heater ({host})",
        "host": host,  # Return the cleaned host
    }


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
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """The heater refused the password: ask for the new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Check the new password against the heater, then reload the entry with it."""
        entry = self._get_reauth_entry()
        errors = {}

        if user_input is not None:
            try:
                await validate_input(
                    self.hass,
                    {"host": entry.data["host"], "password": user_input["password"]},
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"password": user_input["password"]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"host": entry.data["host"]},
            errors=errors,
        )
