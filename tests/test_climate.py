"""The climates and their temperature compensation service."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.exceptions import CannotConnect, InvalidAuth, WriteFailed

# A heating circuit as the client describes it: its function's values under its prefix
CIRCUIT = {
    "id": "circuit",
    "name": "Heating circuit",
    "type": "climate",
    "prefix": "/1/15/0",
    "device_id": "circuit",
    "device_name": "Heating circuit",
}
OIDS = {
    "/1/15/0/0/0/1/0": "20.5",
    "/1/15/0/0/1/1/0": "21.0",
    "/1/15/0/0/3/50/0": "1",
    "/1/15/0/0/2/10/0": "0",
    "/1/15/0/0/3/58/0": "0.5",
}


async def set_up_circuit(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, oids: dict[str, str | None] = OIDS
) -> None:
    client.fetch_all.return_value = {"devices": [CIRCUIT], "oids": oids}
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_circuit_has_a_climate_with_its_bias_removed_and_one_without(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    temperatures = {
        state.entity_id: state.attributes["current_temperature"] for state in hass.states.async_all("climate")
    }

    assert temperatures == {"climate.heating_circuit": 20.0, "climate.heating_circuit_without_bias": 20.5}


@pytest.mark.parametrize(("mode", "action"), [("0", "off"), ("1", "heating")])
async def test_a_circuit_in_standby_is_not_heating(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, mode: str, action: str
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/3/50/0": mode})

    assert hass.states.get("climate.heating_circuit").attributes["hvac_action"] == action


async def test_a_custom_temperature_running_shows_as_its_own_preset(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/2/10/0": "120"})

    assert hass.states.get("climate.heating_circuit").attributes["preset_mode"] == "7"


async def test_without_the_bias_the_corrected_temperatures_are_unknown(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/3/58/0": None})

    attributes = hass.states.get("climate.heating_circuit").attributes
    assert (attributes["current_temperature"], attributes["temperature"]) == (None, None)
    assert hass.states.get("climate.heating_circuit_without_bias").attributes["current_temperature"] == 20.5


async def test_a_new_temperature_is_written_with_the_custom_temperature_duration(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": "climate.heating_circuit", "temperature": 21.5}, blocking=True
    )

    assert client.update.await_args_list == [call("/1/15/0/0/3/4/0", "21.5"), call("/1/15/0/0/2/10/0", "400")]


@pytest.mark.parametrize(
    ("remaining", "writes"),
    [
        ("0", [call("/1/15/0/0/3/50/0", "4")]),
        # A custom temperature running would keep the circuit on it: it is ended
        ("120", [call("/1/15/0/0/3/50/0", "4"), call("/1/15/0/0/2/10/0", "0")]),
    ],
)
async def test_a_preset_is_written_and_ends_a_custom_temperature(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, remaining: str, writes: list
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/2/10/0": remaining})

    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": "climate.heating_circuit", "preset_mode": "4"}, blocking=True
    )

    assert client.update.await_args_list == writes


async def test_the_compensation_service_writes_the_circuit_bias(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    await hass.services.async_call(
        "windhager",
        "set_current_temp_compensation",
        {"entity_id": "climate.heating_circuit", "compensation": -1.5},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/0/3/58/0", "-1.5")


async def test_the_compensation_service_on_the_climate_without_bias_writes_the_same_bias(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    await hass.services.async_call(
        "windhager",
        "set_current_temp_compensation",
        {"entity_id": "climate.heating_circuit_without_bias", "compensation": 1.0},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/0/3/58/0", "1.0")


@pytest.mark.parametrize(
    ("failure", "translation_key"),
    [
        (WriteFailed("/1/15/0/0/3/4/0", 500), "write_refused"),
        (CannotConnect("no answer"), "write_cannot_connect"),
        (InvalidAuth("refused"), "write_auth_failed"),
    ],
)
async def test_a_failed_write_fails_the_action_with_its_reason(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, failure: Exception, translation_key: str
) -> None:
    await set_up_circuit(hass, entry, client)
    client.update.side_effect = failure

    with pytest.raises(HomeAssistantError) as failed:
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": "climate.heating_circuit", "temperature": 21},
            blocking=True,
        )

    assert failed.value.translation_domain == "windhager"
    assert failed.value.translation_key == translation_key


async def test_a_write_refusing_the_password_asks_for_the_new_one(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)
    client.update.side_effect = InvalidAuth("refused")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": "climate.heating_circuit", "preset_mode": "4"},
            blocking=True,
        )
    await hass.async_block_till_done()

    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == "reauth"


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_write_errors_are_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await set_up_circuit(hass, entry, client)

    translations = await async_get_translations(hass, language, "exceptions", ["windhager"])

    for key in ("write_refused", "write_cannot_connect", "write_auth_failed"):
        assert translations[f"component.windhager.exceptions.{key}.message"]


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_compensation_action_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await hass.config_entries.async_setup(entry.entry_id)

    translations = await async_get_translations(hass, language, "services", ["windhager"])

    action = "component.windhager.services.set_current_temp_compensation"
    for key in ("name", "description", "fields.compensation.name", "fields.compensation.description"):
        assert translations[f"{action}.{key}"]


# The heater's operating mode, as the client describes it
OPERATING_MODE_OID = "/1/60/0/2/59/0"
OPERATING_MODE = {
    "id": "operating_mode",
    "key": "operating_mode",
    "type": "operating_mode",
    "oid": OPERATING_MODE_OID,
    "device_id": "biowin",
    "device_name": "BioWIN",
}


async def set_up_with_heater(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, operating_mode: str | None
) -> None:
    client.fetch_all.return_value = {
        "devices": [CIRCUIT, OPERATING_MODE],
        "oids": {**OIDS, OPERATING_MODE_OID: operating_mode},
    }
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# 2026-10-31: 0 once the heater was switched off on its screen, 5 once switched back on
@pytest.mark.parametrize(
    ("operating_mode", "hvac_mode", "action"),
    [("5", "heat", "heating"), ("0", "off", "off"), ("1", "off", "off"), ("8", "heat", "heating")],
)
async def test_the_climate_is_off_while_the_heater_is_switched_off_on_its_screen(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, operating_mode: str, hvac_mode: str, action: str
) -> None:
    await set_up_with_heater(hass, entry, client, operating_mode)

    for entity_id in ("climate.heating_circuit", "climate.heating_circuit_without_bias"):
        state = hass.states.get(entity_id)
        assert (state.state, state.attributes["hvac_modes"]) == (hvac_mode, [hvac_mode])
        assert state.attributes["hvac_action"] == action


async def test_without_the_heater_operating_mode_the_climate_heats(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_with_heater(hass, entry, client, None)

    assert hass.states.get("climate.heating_circuit").state == "heat"


async def test_without_a_heater_module_the_climate_heats(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    assert hass.states.get("climate.heating_circuit").state == "heat"


@pytest.mark.parametrize(("operating_mode", "hvac_mode"), [("5", "off"), ("0", "heat")])
async def test_home_assistant_cannot_switch_the_heater_on_or_off(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, operating_mode: str, hvac_mode: str
) -> None:
    await set_up_with_heater(hass, entry, client, operating_mode)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": "climate.heating_circuit", "hvac_mode": hvac_mode}, blocking=True
        )
    for service in ("turn_on", "turn_off"):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call("climate", service, {"entity_id": "climate.heating_circuit"}, blocking=True)

    client.update.assert_not_awaited()


async def test_choosing_the_current_mode_writes_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_with_heater(hass, entry, client, "5")

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": "climate.heating_circuit", "hvac_mode": "heat"}, blocking=True
    )

    client.update.assert_not_awaited()
