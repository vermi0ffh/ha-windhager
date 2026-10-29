"""The base of the Windhager entities."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WindhagerDataUpdateCoordinator


class WindhagerEntity(CoordinatorEntity[WindhagerDataUpdateCoordinator]):
    """An entity of a Windhager device, as the client describes it, refreshed by the coordinator."""

    def __init__(
        self, coordinator: WindhagerDataUpdateCoordinator, device_info: dict[str, Any]
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = device_info.get("id")
        self._attr_name = device_info.get("name")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_info.get("device_id"))},
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )
