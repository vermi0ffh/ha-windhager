"""The base of the Windhager entities."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WindhagerConfigEntry, WindhagerDataUpdateCoordinator


@callback
def async_add_module_entities(
    entry: WindhagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entities_of: Callable[[dict[str, Any]], Iterable[Entity]],
) -> None:
    """Add a platform's entities for the modules listed now, then for each one listed later.

    The client discovers the modules again when the heater lists others: a module added
    to the heater gets its entities without a reload.
    """
    coordinator = entry.runtime_data
    known: set[str | None] = set()

    @callback
    def add_new() -> None:
        new: list[Entity] = []
        for device_info in coordinator.data.get("devices", []):
            if device_info.get("id") in known:
                continue
            known.add(device_info.get("id"))
            new.extend(entities_of(device_info))
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class WindhagerEntity(CoordinatorEntity[WindhagerDataUpdateCoordinator]):
    """An entity of a Windhager device, as the client describes it, refreshed by the coordinator."""

    # Named "<device> <entity>", the entity's part translated. The registry keeps the
    # entity ids already created; Home Assistant builds new ones from the names in the
    # instance's language (English: the ids the client's names used to give)
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = device_info.get("id")
        self._module_device_id = device_info.get("device_id")
        self._attr_translation_key = device_info.get("key")
        self._attr_entity_category = (
            EntityCategory(category)
            if (category := device_info.get("entity_category"))
            else None
        )
        # Read by Home Assistant only when it creates the entity: an existing one keeps
        # its state, enabled or not
        self._attr_entity_registry_enabled_default = device_info.get(
            "enabled_default", True
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_info.get("device_id"))},
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_model"),
            serial_number=device_info.get("device_serial_number"),
            # The InfoWIN Touch's own web page
            configuration_url=f"http://{coordinator.entry.data['host']}",
        )

    @property
    def available(self) -> bool:
        """Unavailable once the heater no longer lists the entity's module.

        Its entities stay until the user deletes the device (__init__.py): their
        datapoints are no longer read, and would show the readings' defaults.
        """
        return super().available and any(
            device.get("device_id") == self._module_device_id
            for device in self.coordinator.data.get("devices", [])
        )
