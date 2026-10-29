"""The integration's icon, served by Home Assistant from the integration itself."""

from http import HTTPStatus
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components import windhager

ICON = Path(windhager.__file__).parent / "brand" / "icon.png"


async def test_home_assistant_serves_the_integrations_icon(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()

    # placeholder=no: a missing icon is a 404, not Home Assistant's placeholder
    response = await client.get("/api/brands/integration/windhager/icon.png?placeholder=no")

    assert response.status == HTTPStatus.OK
    assert await response.read() == ICON.read_bytes()
