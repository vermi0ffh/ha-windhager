import aiohttp
import logging

from cffi.model import void_type

from .aiohelper import DigestAuth
from .const import DEFAULT_USERNAME, CLIMATE_FUNCTION_TYPE, HEATER_FUNCTION_TYPE

_LOGGER = logging.getLogger(__name__)


class WindhagerHttpClient:
    """Raw API HTTP requests"""

    def __init__(self, host, password) -> None:
        self.host = host
        self.password = password
        self.oids = None
        self.devices = []
        self._session = None
        self._auth = None

    async def _ensure_session(self):
        """Ensure that we have an active client session"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._auth = DigestAuth(DEFAULT_USERNAME, self.password, self._session)

    async def close(self):
        """Close the client session"""
        if self._session:
            await self._session.close()
            self._session = None
            self._auth = None

    async def fetch(self, url):
        try:
            await self._ensure_session()
            ret = await self._auth.request(
                "GET", f"http://{self.host}/api/1.0/lookup{url}"
            )
            json = await ret.json()
            _LOGGER.debug("Fetched data for %s: %s", url, json)
            return json
        except Exception as e:
            _LOGGER.error("Failed to fetch data for %s: %s", url, str(e))
            raise

    async def update(self, oid, value):
        await self._ensure_session()
        await self._auth.request(
            "PUT",
            f"http://{self.host}/api/1.0/datapoint",
            data=bytes(f'{{"OID":"{oid}","value":"{value}"}}', "utf-8"),
        )

    @staticmethod
    def slugify(identifier_str):
        return identifier_str.replace(".", "-").replace("/", "-")

    async def fetch_all(self):
        if self.oids is None:
            self.oids = set()
            # Fetch all devices on the network
            json_devices = await self.fetch("/1")

            # Add devices
            for device in json_devices:
                device_id = f"/1/{str(device['nodeId'])}"

                if "functions" not in device:
                    _LOGGER.debug("Device %s has no functions, skipping.", device_id)
                    continue

                # Filter climate controls
                functions = list(
                    filter(
                        lambda f: (
                            f["fctType"] == CLIMATE_FUNCTION_TYPE and f["lock"] is False
                        ),
                        device["functions"],
                    )
                )
                if len(functions) > 0:
                    fct_id = f"/{str(functions[0]['fctId'])}"

                    # Climate control
                    self.devices.append(
                        {
                            "id": self.slugify(f"{self.host}{device_id}"),
                            "name": functions[0]["name"],
                            "type": "climate",
                            "prefix": device_id,
                            "oids": [
                                f"{fct_id}/0/1/0",
                                f"{fct_id}/1/1/0",
                                f"{fct_id}/3/50/0",
                                f"{fct_id}/2/10/0",
                                f"{fct_id}/3/58/0",
                            ],
                            "device_id": self.slugify(f"{self.host}{device_id}"),
                            "device_name": functions[0]["name"],
                        }
                    )
                    self.oids.update(
                        [
                            # Current temperature
                            f"{device_id}{fct_id}/0/1/0",
                            # Target temperature
                            f"{device_id}{fct_id}/1/1/0",
                            # Current selected mode
                            f"{device_id}{fct_id}/3/50/0",
                            # Duration of custom temperature (in minutes)
                            f"{device_id}{fct_id}/2/10/0",
                            # Outside temperature
                            f"{device_id}{fct_id}/0/0/0",
                            # Temp comfort correction
                            f"{device_id}{fct_id}/3/58/0",
                            # Tempe correction
                            f"{device_id}{fct_id}/3/7/0",
                        ]
                    )

                    # Current temperature
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/1/0/3/58/0"
                            ),
                            "name": f"{functions[0]['name']} Current Temperature",
                            "type": "temperature",
                            "correction_oid": f"{device_id}{fct_id}/3/58/0",
                            "oid": f"{device_id}{fct_id}/0/1/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )

                    # Current temperature (real)
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/1/0"
                            ),
                            "name": f"{functions[0]['name']} Current Temperature real",
                            "type": "temperature",
                            "oid": f"{device_id}{fct_id}/0/1/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )

                    # Comfort Temperature correction
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/3/58/0"
                            ),
                            "name": f"{functions[0]['name']} Comfort Temperature Correction",
                            "type": "sensor",
                            "device_class": None,
                            "state_class": None,
                            "unit": "K",
                            "oid": f"{device_id}{fct_id}/3/58/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Current Temperature correction
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/3/7/0"
                            ),
                            "name": f"{functions[0]['name']} Current Temperature Correction",
                            "type": "sensor",
                            "device_class": None,
                            "state_class": None,
                            "unit": "K",
                            "oid": f"{device_id}{fct_id}/3/7/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Target temperature
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/1/1/0"
                            ),
                            "name": f"{functions[0]['name']} Target Temperature",
                            "type": "temperature",
                            "correction_oid": f"{device_id}{fct_id}/3/58/0",
                            "oid": f"{device_id}{fct_id}/1/1/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Outside temperature
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/0/0"
                            ),
                            "name": f"{functions[0]['name']} Outside Temperature",
                            "type": "temperature",
                            "oid": f"{device_id}{fct_id}/0/0/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )

                # Filter heaters
                functions = list(
                    filter(
                        lambda f: (
                            f["fctType"] == HEATER_FUNCTION_TYPE and f["lock"] is False
                        ),
                        device["functions"],
                    )
                )
                if len(functions) > 0:
                    fct_id = f"/{str(functions[0]['fctId'])}"

                    self.oids.update(
                        [
                            # Heater power (percent)
                            f"{device_id}{fct_id}/0/9/0",
                            # Fumes temperature
                            f"{device_id}{fct_id}/0/11/0",
                            # Heater temperature
                            f"{device_id}{fct_id}/0/7/0",
                            # Combustion chamber temperature
                            f"{device_id}{fct_id}/0/45/0",
                            # Heater status
                            f"{device_id}{fct_id}/2/1/0",
                            # Pellet consumption
                            f"{device_id}{fct_id}/23/100/0",
                            f"{device_id}{fct_id}/23/103/0",
                            # Cleaning
                            f"{device_id}{fct_id}/20/61/0",
                            f"{device_id}{fct_id}/20/62/0",
                        ]
                    )

                    # Heater current power factor
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/9/0"
                            ),
                            "name": f"{functions[0]['name']} Power factor",
                            "type": "sensor",
                            "device_class": "power_factor",
                            "state_class": None,
                            "unit": "%",
                            "oid": f"{device_id}{fct_id}/0/9/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Fumes temperature
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/11/0"
                            ),
                            "name": f"{functions[0]['name']} Fumes Temperature",
                            "type": "temperature",
                            "oid": f"{device_id}{fct_id}/0/11/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Heater temperature
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/7/0"
                            ),
                            "name": f"{functions[0]['name']} Heater Temperature",
                            "type": "temperature",
                            "oid": f"{device_id}{fct_id}/0/7/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Combustion chamber temperature
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/0/45/0"
                            ),
                            "name": f"{functions[0]['name']} Combustion chamber Temperature",
                            "type": "temperature",
                            "oid": f"{device_id}{fct_id}/0/45/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Heater status
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/2/1/0"
                            ),
                            "name": f"{functions[0]['name']} Heater status",
                            "options": [
                                "Brûleur bloqué",
                                "Autotest",
                                "Eteindre gén. chaleur",
                                "Veille",
                                "Brûleur ARRET",
                                "Prérinçage",
                                "Phase d'allumage",
                                "Stabilisation flamme",
                                "Mode modulant",
                                "Chaudière bloqué",
                                "Veille temps différé",
                                "Ventilateur Arrêté",
                                "Porte de revêtement ouverte",
                                "Allumage prêt",
                                "Annuler phase d'allumage",
                                "Préchauffage en cours",
                            ],
                            "type": "select",
                            "oid": f"{device_id}{fct_id}/2/1/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Pellet consumption
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/23/100/0"
                            ),
                            "name": f"{functions[0]['name']} Pellet consumption",
                            "type": "total",
                            "oid": f"{device_id}{fct_id}/23/100/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )
                    # Total pellet consumption
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/23/103/0"
                            ),
                            "name": f"{functions[0]['name']} Total Pellet consumption",
                            "type": "total_increasing",
                            "oid": f"{device_id}{fct_id}/23/103/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )

                    # Running time until stage 1 cleaning
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/20/61/0"
                            ),
                            "name": f"{functions[0]['name']} Running time until stage 1 cleaning",
                            "type": "sensor",
                            "device_class": "duration",
                            "state_class": None,
                            "unit": "h",
                            "oid": f"{device_id}{fct_id}/20/61/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )

                    # Running time until stage 2 cleaning
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.host}/1/{str(device['nodeId'])}{fct_id}/20/62/0"
                            ),
                            "name": f"{functions[0]['name']} Running time until stage 2 cleaning",
                            "type": "sensor",
                            "device_class": "duration",
                            "state_class": None,
                            "unit": "h",
                            "oid": f"{device_id}{fct_id}/20/62/0",
                            "device_id": self.slugify(
                                f"{self.host}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                        }
                    )

        ret = {
            "devices": self.devices,
            "oids": {},
        }

        # Read all found OIDs
        for oid in self.oids:
            try:
                json = await self.fetch(oid)
                if "value" in json and json["value"] != "-.-":
                    ret["oids"][oid] = json["value"]
                else:
                    ret["oids"][oid] = None
                    _LOGGER.debug("Invalid or missing value for OID %s: %s", oid, json)
            except Exception as e:
                ret["oids"][oid] = None
                _LOGGER.error("Error while fetching OID %s: %s", oid, str(e))

        return ret

    async def full_system_scan(self):
        # Fetch all devices on the network
        json_devices = await self.fetch("/1")

        for device in json_devices:
            _LOGGER.info("Found device %s - %s", device["nodeId"], device["name"])
            if "functions" not in device:
                continue

            for function in device["functions"]:
                if function["fctType"] < 0:
                    continue

                _LOGGER.info("Found function /1/%s/%s - %s", device["nodeId"], function["fctId"], function["name"])
                await self.full_scan_function(device, function)


    async def full_scan_function(self, device, function):
        device_id = f"/1/{str(device['nodeId'])}"
        fct_id = f"/{str(function['fctId'])}"
        # Fetch all sensors
        json_sensors = await self.fetch(f"{device_id}{fct_id}")

        for sensor in json_sensors:
            _LOGGER.info(f"Found sensors {device_id}{fct_id}/%s : %s", sensor["id"], sensor["count"])
            await self.full_scan_sensor(device, function, sensor)


    async def full_scan_sensor(self, device, function, sensor):
        device_id = f"/1/{str(device['nodeId'])}"
        fct_id = f"/{str(function['fctId'])}"
        sensor_id = f"/{str(sensor['id'])}"

        json_readings = await self.fetch(f"{device_id}{fct_id}{sensor_id}")
        for reading in json_readings:
            _LOGGER.info(f"Found reading {device_id}{fct_id}{sensor_id} : %s", reading)