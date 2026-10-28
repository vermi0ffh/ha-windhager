"""Shared fixtures: the integration loads, its HTTP client is a mock."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import windhager


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """The integration lives in custom_components/: Home Assistant loads it only with this fixture."""


@pytest.fixture
def client() -> Iterator[MagicMock]:
    """The client the integration creates, answering with no device: no request reaches a heater."""
    with patch.object(windhager, "WindhagerHttpClient") as client_class:
        client = client_class.return_value
        client.fetch_all = AsyncMock(return_value={"devices": [], "oids": {}})
        client.close = AsyncMock()
        yield client


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry for a heater on a documentation address."""
    entry = MockConfigEntry(domain="windhager", data={"host": "192.0.2.1", "password": "secret"})
    entry.add_to_hass(hass)
    return entry
