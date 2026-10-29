"""A heater lost while polling: the entities unavailable, logged once, back when it answers."""

import logging
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.exceptions import CannotConnect

STATUS_OID = "/1/15/0/2/1/0"
DATA = {
    "devices": [
        {
            "id": "heater_status",
            "key": "heater_status",
            "type": "select",
            "oid": STATUS_OID,
            "device_id": "biowin",
            "device_name": "BioWIN",
        }
    ],
    "oids": {STATUS_OID: "3"},
}


def problems(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]


async def test_a_lost_heater_makes_its_entities_unavailable_and_is_logged_once(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    client.fetch_all.return_value = DATA
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    caplog.clear()

    client.fetch_all.side_effect = CannotConnect("no answer")
    for _ in range(3):
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.biowin_heater_status").state == "unavailable"
    [problem] = problems(caplog)
    assert "192.0.2.1" in problem

    client.fetch_all.side_effect = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.biowin_heater_status").state == "3"
    assert any("recovered" in record.getMessage() for record in caplog.records)


async def test_a_timeout_keeps_the_last_values_until_the_third(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    client.fetch_all.return_value = DATA
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    caplog.clear()

    client.fetch_all.side_effect = TimeoutError
    states = []
    for _ in range(3):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        states.append(hass.states.get("sensor.biowin_heater_status").state)

    assert states == ["3", "3", "unavailable"]
    assert len(problems(caplog)) == 1


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_polling_errors_are_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await hass.config_entries.async_setup(entry.entry_id)

    translations = await async_get_translations(hass, language, "exceptions", ["windhager"])

    for key in ("auth_failed", "timeout", "cannot_connect"):
        assert translations[f"component.windhager.exceptions.{key}.message"]
