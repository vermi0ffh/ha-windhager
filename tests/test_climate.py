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


@pytest.mark.parametrize(("mode", "hvac_mode"), [("0", "off"), ("1", "heat"), ("4", "heat")])
async def test_a_circuit_on_standby_is_off(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, mode: str, hvac_mode: str
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/3/50/0": mode})

    assert hass.states.get("climate.heating_circuit").state == hvac_mode


async def set_hvac_mode(hass: HomeAssistant, hvac_mode: str) -> None:
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": "climate.heating_circuit", "hvac_mode": hvac_mode}, blocking=True
    )


async def heater_now_reads(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, mode: str) -> None:
    """The heater answering the next poll with the circuit on preset `mode`."""
    client.fetch_all.return_value = {"devices": [CIRCUIT], "oids": {**OIDS, "/1/15/0/0/3/50/0": mode}}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("remaining", "writes"),
    [
        ("0", [call("/1/15/0/0/3/50/0", "0")]),
        # As any preset, standby ends a running custom temperature
        ("120", [call("/1/15/0/0/3/50/0", "0"), call("/1/15/0/0/2/10/0", "0")]),
    ],
)
async def test_off_puts_the_circuit_on_standby(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, remaining: str, writes: list
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/2/10/0": remaining})

    await set_hvac_mode(hass, "off")

    assert client.update.await_args_list == writes


async def test_heat_brings_back_the_program_from_before_off(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/3/50/0": "4"})
    await set_hvac_mode(hass, "off")
    await heater_now_reads(hass, entry, client, "0")
    client.update.reset_mock()

    await set_hvac_mode(hass, "heat")

    client.update.assert_awaited_once_with("/1/15/0/0/3/50/0", "4")


async def test_heat_after_a_standby_set_elsewhere_goes_to_heating_program_1(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/3/50/0": "0"})

    await hass.services.async_call("climate", "turn_on", {"entity_id": "climate.heating_circuit"}, blocking=True)

    client.update.assert_awaited_once_with("/1/15/0/0/3/50/0", "1")


@pytest.mark.parametrize(("mode", "hvac_mode"), [("0", "off"), ("4", "heat")])
async def test_the_mode_the_circuit_is_already_in_writes_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, mode: str, hvac_mode: str
) -> None:
    await set_up_circuit(hass, entry, client, {**OIDS, "/1/15/0/0/3/50/0": mode})

    await set_hvac_mode(hass, hvac_mode)

    client.update.assert_not_awaited()


async def test_turn_off_puts_the_circuit_on_standby(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    await hass.services.async_call("climate", "turn_off", {"entity_id": "climate.heating_circuit"}, blocking=True)

    client.update.assert_awaited_once_with("/1/15/0/0/3/50/0", "0")
