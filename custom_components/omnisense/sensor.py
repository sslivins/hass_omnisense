import os
import re
import logging
import requests
from datetime import timedelta
from bs4 import BeautifulSoup
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Configuration keys
CONF_SITE_NAME = "site_name"       # The name of the site (e.g., "home")
CONF_SENSOR_IDS = "sensor_ids"     # List of sensor IDs to extract (empty = all)
CONF_USERNAME = "username"         # Login username
CONF_PASSWORD = "password"         # Login password

# Defaults
DEFAULT_NAME = "Scraped Temperature Sensors"
DEFAULT_SENSOR_IDS = []   # if provided, filter sensors by these IDs (if empty, retrieve all)

# Fixed URLs
LOGIN_URL = "https://www.omnisense.com/user_login.asp"
SITE_LIST_URL = "https://www.omnisense.com/site_select.asp"

# Extend the platform schema (for YAML configuration)
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SITE_NAME): cv.string,
    vol.Optional(CONF_SENSOR_IDS, default=DEFAULT_SENSOR_IDS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_USERNAME): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
})

def _fetch_sensor_data(username, password, site_names, sensor_ids=None):
    """Fetch sensor data from Omnisense for specified sites and return a dictionary of sensor data."""
    session = requests.Session()
    payload = {
        "userId": username,
        "userPass": password,
        "btnAct": "Log-In",
        "target": ""
    }
    try:
        response = session.post(LOGIN_URL, data=payload, timeout=10)
        if response.status_code != 200 or "User Log-In" in response.text:
            raise Exception("Login failed; check your credentials.")
    except Exception as err:
        _LOGGER.error("Error during login: %s", err)
        return {}

    try:
        response = session.get(SITE_LIST_URL, timeout=10)
        if response.status_code != 200:
            raise Exception("Error fetching job sites page.")
        soup = BeautifulSoup(response.text, "html.parser")
        site_links = {
            link.get_text(strip=True).lower(): link.get("onclick", "")
            for link in soup.find_all("a")
        }
    except Exception as err:
        _LOGGER.error("Error fetching site list: %s", err)
        return {}

    all_sensors = {}
    for site_name in site_names:
        site_name_lower = site_name.lower()
        if site_name_lower not in site_links:
            _LOGGER.warning(f"Site with name '{site_name}' not found.")
            continue

        onclick = site_links[site_name_lower]
        match = re.search(r"ShowSiteDetail\('(\d+)'\)", onclick)
        if not match:
            _LOGGER.warning(f"Could not extract site number for site '{site_name}'.")
            continue

        site_number = match.group(1)
        sensor_page_url = f"https://www.omnisense.com/sensor_select.asp?siteNbr={site_number}"

        try:
            response = session.get(sensor_page_url, timeout=10)
            if response.status_code != 200:
                raise Exception(f"Error fetching sensor data for site '{site_name}'.")
            soup = BeautifulSoup(response.text, "html.parser")
            for table in soup.select("table.sortable.table"):
                sensor_type = None
                table_id = table.get("id", "")
                if table_id.startswith("sensorType"):
                    sensor_type = table_id[len("sensorType"):]
                if not sensor_type:
                    caption = table.find("caption")
                    if caption and caption.text:
                        m = re.search(r"Sensor Type\s*(\d+)", caption.text)
                        if m:
                            sensor_type = f"S-{m.group(1)}"
                for row in table.select("tr.sensorTable"):
                    tds = row.find_all("td")
                    if len(tds) >= 10:
                        sid = tds[0].get_text(strip=True)
                        if sensor_ids and sid not in sensor_ids:
                            continue
                        try:
                            temperature = float(tds[4].get_text(strip=True))
                        except ValueError:
                            temperature = None

                        desc = tds[1].get_text(strip=True)
                        if desc == "~click to edit~":
                            desc = "<empty>"

                        all_sensors[sid] = {
                            "description": desc,
                            "last_activity": tds[2].get_text(strip=True),
                            "status": tds[3].get_text(strip=True),
                            "temperature": temperature,
                            "humidity": tds[5].get_text(strip=True),
                            "gpkg": tds[6].get_text(strip=True),
                            "dew_point": tds[7].get_text(strip=True),
                            "wood_pct": tds[8].get_text(strip=True),
                            "battery_voltage": tds[9].get_text(strip=True),
                            "sensor_type": sensor_type,
                            "sensor_id": sid,
                            "site_name": site_name,
                        }
        except Exception as err:
            _LOGGER.error("Error fetching/parsing sensor data for site '%s': %s", site_name, err)

    return all_sensors


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Omnisense sensor(s) from a config entry using DataUpdateCoordinator."""
    data = entry.data
    site_names = data.get("selected_sites", "")
    sensor_ids = data.get("selected_sensor_ids", [])
    username = data.get("username")
    password = data.get("password")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Omnisense Data",
        update_method=lambda: hass.async_add_executor_job(
            _fetch_sensor_data, username, password, site_names, sensor_ids
        ),
        update_interval=timedelta(minutes=60), 
    )

    await coordinator.async_config_entry_first_refresh()

    entities = []

    sensors_data = coordinator.data or {}
    for sid, sensor_info in sensors_data.items():
        if not sensor_ids or sid in sensor_ids:
            sensor_name = f"{sensor_info.get('description', 'Unknown')}"
            entities.append(TemperatureSensor(sensor_name, sensor_info))

    async_add_entities(entities)
    return True

class TemperatureSensor(SensorEntity):
    """Sensor entity that retrieves its data from a DataUpdateCoordinator."""

    def __init__(self, sensor_info=None):
        """Initialize the sensor."""
        self._name = f"{sensor_info.get('description', 'Unknown')}"
        self._site_name = f"{sensor_info.get('site_name', 'Unknown')}"
        self._sensor_id = f"{sensor_info.get('sensor_id', 'Unknown')}"
        self._sensor_info = sensor_info

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:thermometer"        

    @property
    def name(self):
        """Return the sensor name."""
        return f"{self._name} Temperature"

    @property
    def unique_id(self):
        """Return a unique ID for this sensor entity.
        """
        if self._sensor_id:
            return f"{self._sensor_id}"
        return None

    # @property
    # def state(self):
    #     """Return the sensor state.
        
    #     If filtering by sensor id and exactly one is provided, return its temperature.
    #     Otherwise, return the number of sensors found.
    #     """
    #     data = self.coordinator.data or {}
    #     if self._sensor_id:
    #         sensor_data = data.get(self._sensor_id)
    #         return sensor_data.get("temperature") if sensor_data else None
    #     return len(data)

    # @property
    # def extra_state_attributes(self):
    #     """Return additional sensor data as attributes."""
    #     data = self.coordinator.data or {}
    #     if self._sensor_id:
    #             return data.get(self._sensor_id, {})
    #     return {"sensors": data}

    def _get_state(self) -> int:
        """Retrieve latest state."""
        return f"{self._sensor_info.get('temperature', 'Unknown')}"

    @property
    def device_info(self):
        """Return device information about this sensor."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": f"{self._name}",
            "manufacturer": "OmniSense",
            "model": f"{self._sensor_info.get('sensor_type', 'Unknown')}",
            "sw_version": "N/A",
            #"via_device": (DOMAIN, self._site_name),
        }        

    async def async_update(self):
        """Request an update from the coordinator."""
        await self.coordinator.async_request_refresh()
