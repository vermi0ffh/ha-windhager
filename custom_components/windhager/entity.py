"""The base of the Windhager entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WindhagerDataUpdateCoordinator


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
        self._attr_translation_key = device_info.get("key")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_info.get("device_id"))},
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )
