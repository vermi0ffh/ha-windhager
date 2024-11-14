"""Support for Windhager Climate."""
from __future__ import annotations
import logging

from homeassistant.const import (
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up WindHager lights from a config entry."""
    data_coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    for deviceInfo in data_coordinator.data.get("devices"):
        if deviceInfo.get("type") == "temperature":
            entity = WindhagerTemperatureSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif deviceInfo.get("type") == "sensor":
            entity = WindhagerGenericSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif deviceInfo.get("type") == "select":
            entity = WindhagerSelectSensor(data_coordinator, deviceInfo)
            entities.append(entity)
        elif (
            deviceInfo.get("type") == "total"
            or deviceInfo.get("type") == "total_increasing"
        ):
            entity = WindhagerPelletSensor(data_coordinator, deviceInfo)
            entities.append(entity)

    async_add_entities(entities)


class WindhagerTemperatureSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info):
        super().__init__(coordinator)
        self._id = device_info.get("id")
        self._name = device_info.get("name")
        self._oid = device_info.get("oid")
        self._correction_oid = device_info.get("correction_oid")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, device_info.get("device_id"))
            },
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def device_class(self):
        return "temperature"

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def native_value(self):
        oid_value = self.coordinator.data.get("oids").get(self._oid)

        if oid_value is None:
            return None

        ret = float(oid_value)

        if self._correction_oid is not None:
            ret -= float(self.coordinator.data.get("oids").get(self._correction_oid))

        return ret

    @property
    def native_unit_of_measurement(self):
        return UnitOfTemperature.CELSIUS


class WindhagerGenericSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info):
        super().__init__(coordinator)
        self._id = device_info.get("id")
        self._name = device_info.get("name")
        self._device_class = device_info.get("device_class")
        self._state_class = device_info.get("state_class")
        self._unit = device_info.get("unit")
        self._oid = device_info.get("oid")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, device_info.get("device_id"))
            },
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def device_class(self):
        return self._device_class

    @property
    def state_class(self):
        return self._state_class

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def native_value(self):
        oid_value = self.coordinator.data.get("oids").get(self._oid)

        if oid_value is None:
            return None

        return float(oid_value)

    @property
    def native_unit_of_measurement(self):
        return self._unit


class WindhagerPelletSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info):
        super().__init__(coordinator)
        self._id = device_info.get("id")
        self._name = device_info.get("name")
        self._oid = device_info.get("oid")
        self._state_class = device_info.get("type")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, device_info.get("device_id"))
            },
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def state_class(self):
        return self._state_class

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def native_value(self):
        oid_value = self.coordinator.data.get("oids").get(self._oid)

        if oid_value is None:
            return None

        return float(oid_value)

    @property
    def native_unit_of_measurement(self):
        return "t"


class WindhagerSelectSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device_info):
        super().__init__(coordinator)
        self._id = device_info.get("id")
        self._name = device_info.get("name")
        self._oid = device_info.get("oid")
        self._options = device_info.get("options")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, device_info.get("device_id"))
            },
            name=device_info.get("device_name"),
            manufacturer="Windhager",
            model=device_info.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def raw_value(self):
        oid_value = self.coordinator.data.get("oids").get(self._oid)

        if oid_value is None:
            return None

        return int(oid_value)

    @property
    def native_value(self):
        return self._options[self.raw_value]
