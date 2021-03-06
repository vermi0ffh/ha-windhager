import aiohttp
import logging
from .aiohelper import DigestAuth

_LOGGER = logging.getLogger(__name__)


class WindhagerHttpClient:
    """Raw API HTTP requests"""

    def __init__(self, host, password) -> None:
        self.host = host
        self.password = password
        self.oids = None
        self.devices = []

    async def fetch(self, url):
        client = aiohttp.ClientSession()
        auth = DigestAuth("USER", self.password, client)
        ret = await auth.request("GET", "http://" + self.host + "/api/1.0/lookup" + url)
        json = await ret.json()
        await client.close()
        return json

    async def update(self, oid, value):
        client = aiohttp.ClientSession()
        auth = DigestAuth("USER", self.password, client)
        await auth.request(
            "PUT",
            "http://" + self.host + "/api/1.0/datapoint",
            data=bytes('{"OID":"' + oid + '","value":"' + value + '"}', "utf-8"),
        )
        await client.close()

    async def fetch_all(self):
        if self.oids is None:
            self.oids = set()
            # Fetch all devices on the network
            json_devices = await self.fetch("/1")

            # Add devices
            for device in json_devices:
                device_id = "/1/" + str(device["nodeId"])

                # Filter climate controls
                functions = list(
                    filter(
                        lambda f: (f["fctType"] == 14 and f["lock"] is False),
                        device["functions"],
                    )
                )
                if len(functions) > 0:
                    fct_id = "/" + str(functions[0]["fctId"])

                    # Climate control
                    self.devices.append(
                        {
                            "id": (self.host + device_id)
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"],
                            "type": "climate",
                            "prefix": device_id,
                            "oids": [
                                fct_id + "/0/1/0",
                                fct_id + "/1/1/0",
                                fct_id + "/3/50/0",
                                fct_id + "/2/10/0",
                                fct_id + "/3/58/0",
                            ],
                        }
                    )
                    self.oids.update(
                        [
                            # Current temperature
                            device_id + fct_id + "/0/1/0",
                            # Target temperature
                            device_id + fct_id + "/1/1/0",
                            # Current selected mode
                            device_id + fct_id + "/3/50/0",
                            # Duration of custom temperature (in minutes)
                            device_id + fct_id + "/2/10/0",
                            # Outside temperature
                            device_id + fct_id + "/0/0/0",
                            # Temp confort correction
                            device_id + fct_id + "/3/58/0",
                            # Tempe correction
                            device_id + fct_id + "/3/7/0",
                        ]
                    )

                    # Current temperature
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/1/0"
                                + "/3/58/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Current Temperature",
                            "type": "temperature",
                            "correction_oid": device_id + fct_id + "/3/58/0",
                            "oid": device_id + fct_id + "/0/1/0",
                        }
                    )

                    # Current temperature (real)
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/1/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"]
                            + " - Current Temperature real",
                            "type": "temperature",
                            "oid": device_id + fct_id + "/0/1/0",
                        }
                    )

                    # Comfort Temperature correction
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/3/58/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"]
                            + " - Comfort Temperature Correction",
                            "type": "sensor",
                            "device_class": None,
                            "state_class": None,
                            "unit": "K",
                            "oid": device_id + fct_id + "/3/58/0",
                        }
                    )
                    # Current Temperature correction
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/3/7/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"]
                            + " - Current Temperature Correction",
                            "type": "sensor",
                            "device_class": None,
                            "state_class": None,
                            "unit": "K",
                            "oid": device_id + fct_id + "/3/7/0",
                        }
                    )
                    # Target temperature
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/1/1/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Target Temperature",
                            "type": "temperature",
                            "correction_oid": device_id + fct_id + "/3/58/0",
                            "oid": device_id + fct_id + "/1/1/0",
                        }
                    )
                    # Outside temperature
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/0/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Outside Temperature",
                            "type": "temperature",
                            "oid": device_id + fct_id + "/0/0/0",
                        }
                    )

                # Filter heaters
                functions = list(
                    filter(
                        lambda f: (f["fctType"] == 9 and f["lock"] is False),
                        device["functions"],
                    )
                )
                if len(functions) > 0:
                    fct_id = "/" + str(functions[0]["fctId"])

                    self.oids.update(
                        [
                            # Heater power (percent)
                            device_id + fct_id + "/0/9/0",
                            # Fumes temperature
                            device_id + fct_id + "/0/11/0",
                            # Heater temperature
                            device_id + fct_id + "/0/7/0",
                            # Combusion chamber temperature
                            device_id + fct_id + "/0/45/0",
                            # Heater status
                            device_id + fct_id + "/2/1/0",
                            # Pellet consumption
                            device_id + fct_id + "/23/100/0",
                            device_id + fct_id + "/23/103/0",
                        ]
                    )

                    # Heater current power factor
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/9/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Power factor",
                            "type": "sensor",
                            "device_class": "power_factor",
                            "state_class": None,
                            "unit": "%",
                            "oid": device_id + fct_id + "/0/9/0",
                        }
                    )
                    # Fumes temperature
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/11/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Fumes Temperature",
                            "type": "temperature",
                            "oid": device_id + fct_id + "/0/11/0",
                        }
                    )
                    # Heater temperature
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/7/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Heater Temperature",
                            "type": "temperature",
                            "oid": device_id + fct_id + "/0/7/0",
                        }
                    )
                    # Combustion chamber temperature
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/0/45/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"]
                            + " - Combustion chamber Temperature",
                            "type": "temperature",
                            "oid": device_id + fct_id + "/0/45/0",
                        }
                    )
                    # Heater status
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/2/1/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Heater status",
                            "options": [
                                "Br??leur bloqu??",
                                "Autotest",
                                "Eteindre g??n. chaleur",
                                "Veille",
                                "Br??leur ARRET",
                                "Pr??rin??age",
                                "Phase d'allumage",
                                "Stabilisation flamme",
                                "Mode modulant",
                                "Chaudi??re bloqu??",
                                "Veille temps diff??r??",
                                "Ventilateur Arr??t??",
                                "Porte de rev??tement ouverte",
                                "Allumage pr??t",
                                "Annuler phase d'allumage",
                                "Pr??chauffage en cours",
                            ],
                            "type": "select",
                            "oid": device_id + fct_id + "/2/1/0",
                        }
                    )
                    # Pellet consumption
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/23/100/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"] + " - Pellet consumption",
                            "type": "total",
                            "oid": device_id + fct_id + "/23/100/0",
                        }
                    )
                    # Total pellet consumption
                    self.devices.append(
                        {
                            "id": (
                                self.host
                                + "/1/"
                                + str(device["nodeId"])
                                + fct_id
                                + "/23/103/0"
                            )
                            .replace(".", "-")
                            .replace("/", "-"),
                            "name": functions[0]["name"]
                            + " - Total Pellet consumption",
                            "type": "total_increasing",
                            "oid": device_id + fct_id + "/23/103/0",
                        }
                    )

        ret = {
            "devices": self.devices,
            "oids": {},
        }

        # Lecture de tous les OIDs trouv??s
        for oid in self.oids:
            json = await self.fetch(oid)
            ret["oids"][oid] = json["value"]

        return ret
