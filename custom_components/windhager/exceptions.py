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


class WriteFailed(WindhagerError):
    """Error to indicate the heater answered a write with an error status."""

    def __init__(self, oid: str, status: int) -> None:
        super().__init__(f"The heater answered {status} writing {oid}")
        self.status = status

