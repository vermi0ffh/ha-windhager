"""The Windhager Heater integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    service,
)
from homeassistant.helpers.typing import ConfigType

from .client import WindhagerHttpClient, slugify
from .const import DOMAIN
from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services, once for all its entries."""
    # Registered here rather than with the climates, so that they exist, and say
    # why they fail, even while no entry is loaded
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "set_current_temp_compensation",
        entity_domain=CLIMATE_DOMAIN,
        schema={
            vol.Required("compensation"): vol.All(
                vol.Coerce(float), vol.Range(min=-3.5, max=3.5)
            ),
        },
        func="set_current_temp_compensation",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WindhagerConfigEntry) -> bool:
    """Set up windhager integration from a config entry."""
    _LOGGER.info("Setting up Windhager integration for %s", entry.data["host"])

    client = WindhagerHttpClient(
        host=entry.data["host"],
        password=entry.data["password"],
    )

    coordinator = WindhagerDataUpdateCoordinator(hass, client, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except (ConfigEntryNotReady, ConfigEntryAuthFailed):
        # Home Assistant retries, or asks for the password, with a new client: close
        # this one's session
        await client.close()
        raise

    entry.runtime_data = coordinator
    _async_set_heater_id(hass, entry, coordinator.data.get("heater_id"))
    # Before the platforms, so that they find their entities and devices under the new ids
    await _async_migrate_unique_ids(hass, entry, coordinator.data.get("heater_id"))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_remove_empty_devices(hass, entry)

    return True


def _async_remove_empty_devices(hass: HomeAssistant, entry: WindhagerConfigEntry) -> None:
    """Remove the entry's devices left without any entity.

    Before 2026-10-29 a circuit's climates had a device of their own, apart from the
    circuit's sensors: set up again, they join their module's device and leave that
    one empty. A device that still has entities stays, even if its module did not
    answer this time: removing it would remove them.
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        ):
            device_registry.async_remove_device(device.id)


def _async_set_heater_id(
    hass: HomeAssistant, entry: WindhagerConfigEntry, heater_id: str | None
) -> None:
    """Give an entry added before the heater's identity was known its unique id."""
    if entry.unique_id is not None or heater_id is None:
        return
    others = hass.config_entries.async_entries(DOMAIN)
    if any(other.unique_id == heater_id for other in others):
        _LOGGER.warning(
            "Another entry already holds the heater at %s: remove one of them",
            entry.data["host"],
        )
        return
    hass.config_entries.async_update_entry(entry, unique_id=heater_id)


async def _async_migrate_unique_ids(
    hass: HomeAssistant, entry: WindhagerConfigEntry, heater_id: str | None
) -> None:
    """Rename the entities and devices named after the host to the heater's Neuron ID.

    Their unique ids started with the host, so a new address made new entities and lost
    the history; the registry keeps the entity ids, their settings and their history
    across the renaming. Done once: the renamed ids no longer start with the host.
    """
    if heater_id is None:
        return
    host_id = slugify(entry.data["host"])
    entity_registry = er.async_get(hass)

    @callback
    def renamed(entity: er.RegistryEntry) -> dict[str, str] | None:
        if not entity.unique_id.startswith(host_id):
            return None
        unique_id = heater_id + entity.unique_id.removeprefix(host_id)
        if entity_registry.async_get_entity_id(entity.domain, DOMAIN, unique_id):
            # Another entry of the same heater (added twice) took it first
            _LOGGER.warning("%s is not renamed: %s is taken", entity.entity_id, unique_id)
            return None
        return {"new_unique_id": unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, renamed)

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        identifiers = {
            (domain, heater_id + identifier.removeprefix(host_id))
            if domain == DOMAIN and identifier.startswith(host_id)
            else (domain, identifier)
            for domain, identifier in device.identifiers
        }
        if identifiers == device.identifiers:
            continue
        try:
            device_registry.async_update_device(device.id, new_identifiers=identifiers)
        except dr.DeviceIdentifierCollisionError:
            _LOGGER.warning("Device %s is not renamed: its new id is taken", device.name)


async def async_unload_entry(hass: HomeAssistant, entry: WindhagerConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Windhager integration for %s", entry.data["host"])
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.close()

    return unload_ok
