"""Support for Windhager Climate."""
from __future__ import annotations
import logging

from homeassistant.const import (
    TEMP_CELSIUS,
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
    def __init__(self, coordinator, deviceInfo):
        super().__init__(coordinator)
        self._id = deviceInfo.get("id")
        self._name = deviceInfo.get("name")
        self._oid = deviceInfo.get("oid")
        self._correction_oid = deviceInfo.get("correction_oid")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, deviceInfo.get("device_id"))
            },
            name=deviceInfo.get("device_name"),
            manufacturer="Windhager",
            model=deviceInfo.get("device_name"),
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
        return self._device_info;

    @property
    def native_value(self):
        ret = float(self.coordinator.data.get("oids").get(self._oid))

        if self._correction_oid is not None:
            ret -= float(self.coordinator.data.get("oids").get(self._correction_oid))

        return ret

    @property
    def native_unit_of_measurement(self):
        return TEMP_CELSIUS


class WindhagerGenericSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, deviceInfo):
        super().__init__(coordinator)
        self._id = deviceInfo.get("id")
        self._name = deviceInfo.get("name")
        self._device_class = deviceInfo.get("device_class")
        self._state_class = deviceInfo.get("state_class")
        self._unit = deviceInfo.get("unit")
        self._oid = deviceInfo.get("oid")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, deviceInfo.get("device_id"))
            },
            name=deviceInfo.get("device_name"),
            manufacturer="Windhager",
            model=deviceInfo.get("device_name"),
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
        return self._device_info;

    @property
    def native_value(self):
        return float(self.coordinator.data.get("oids").get(self._oid))

    @property
    def native_unit_of_measurement(self):
        return self._unit


class WindhagerPelletSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, deviceInfo):
        super().__init__(coordinator)
        self._id = deviceInfo.get("id")
        self._name = deviceInfo.get("name")
        self._oid = deviceInfo.get("oid")
        self._state_class = deviceInfo.get("type")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, deviceInfo.get("device_id"))
            },
            name=deviceInfo.get("device_name"),
            manufacturer="Windhager",
            model=deviceInfo.get("device_name"),
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
        return self._device_info;

    @property
    def native_value(self):
        return float(self.coordinator.data.get("oids").get(self._oid))

    @property
    def native_unit_of_measurement(self):
        return "t"


class WindhagerSelectSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, deviceInfo):
        super().__init__(coordinator)
        self._id = deviceInfo.get("id")
        self._name = deviceInfo.get("name")
        self._oid = deviceInfo.get("oid")
        self._options = deviceInfo.get("options")
        self._device_info = DeviceInfo(
            identifiers={
                (DOMAIN, deviceInfo.get("device_id"))
            },
            name=deviceInfo.get("device_name"),
            manufacturer="Windhager",
            model=deviceInfo.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info;

    @property
    def raw_value(self):
        return int(self.coordinator.data.get("oids").get(self._oid))

    @property
    def native_value(self):
        return self._options[self.raw_value]
