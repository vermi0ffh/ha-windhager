"""Exceptions for Windhager integration."""

from homeassistant.exceptions import HomeAssistantError


class WindhagerError(HomeAssistantError):
    """Base exception for Windhager integration."""

    pass


class CannotConnect(WindhagerError):
    """Error to indicate we cannot connect."""

    pass


class InvalidAuth(WindhagerError):
    """Error to indicate there is invalid auth."""

    pass


class WindhagerValueError(WindhagerError):
    """Error to indicate invalid values."""

    pass
