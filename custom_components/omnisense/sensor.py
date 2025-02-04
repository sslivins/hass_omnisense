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

def _fetch_sensor_data(username, password, site_name, sensor_ids):
    """Fetch sensor data from Omnisense and return a dictionary of sensor data."""
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
        site_link = soup.find("a", text=lambda t: t and t.strip().lower() == site_name.lower())
        if not site_link:
            raise Exception(f"Site with name '{site_name}' not found.")
        onclick = site_link.get("onclick", "")
        match = re.search(r"ShowSiteDetail\('(\d+)'\)", onclick)
        if not match:
            raise Exception("Could not extract site number from onclick attribute.")
        site_number = match.group(1)
        sensor_page_url = f"https://www.omnisense.com/sensor_select.asp?siteNbr={site_number}"
    except Exception as err:
        _LOGGER.error("Error determining sensor page URL: %s", err)
        return {}

    try:
        response = session.get(sensor_page_url, timeout=10)
        if response.status_code != 200:
            raise Exception("Error fetching sensor data.")
        soup = BeautifulSoup(response.text, "html.parser")
        sensors = {}
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
                        sensor_type = m.group(1)
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

                    desc = tds[1].get_text(strip=True) #if the description isnt set then change it to an empty string
                    if desc == "~click to edit~":
                        desc = ""

                    sensors[sid] = {
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
        return sensors
    except Exception as err:
        _LOGGER.error("Error fetching/parsing sensor data: %s", err)
        return {}

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Omnisense sensor(s) from a config entry using DataUpdateCoordinator."""
    data = entry.data
    site_name = data.get("site_name", "Home")
    sensor_ids = data.get("sensor_ids", [])
    username = data.get("username")
    password = data.get("password")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Omnisense Data",
        update_method=lambda: hass.async_add_executor_job(
            _fetch_sensor_data, username, password, site_name, sensor_ids
        ),
        update_interval=timedelta(minutes=60),  # Change this value to update less frequently
    )

    await coordinator.async_config_entry_first_refresh()

    entities = []
    sensors_data = coordinator.data or {}
    for sid, sensor_info in sensors_data.items():
        if not sensor_ids or sid in sensor_ids:
            sensor_name = f"{sensor_info.get('description', 'Unknown')} - {site_name.capitalize()} - {sid}"
            entities.append(OmniSenseSensor(sensor_name, site_name, coordinator, sensor_id=sid))


    async_add_entities(entities)
    return True

class OmniSenseSensor(SensorEntity):
    """Sensor entity that retrieves its data from a DataUpdateCoordinator."""

    def __init__(self, name, site_name, coordinator, sensor_id=None):
        """Initialize the sensor."""
        self._name = name
        self._site_name = site_name
        # Normalize sensor_id to a list.
        self._sensor_ids = sensor_id if isinstance(sensor_id, list) else ([sensor_id] if sensor_id else [])
        self.coordinator = coordinator

    @property
    def name(self):
        """Return the sensor name."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID for this sensor entity.
        
        If there is exactly one sensor ID, we can use that (combined with the site name).
        Otherwise, return None so that the entity is not user-manageable.
        """
        if self._sensor_ids and len(self._sensor_ids) == 1:
            return f"{self._site_name.lower()}_{self._sensor_ids[0].lower()}"
        return None

    @property
    def state(self):
        """Return the sensor state.
        
        If filtering by sensor id and exactly one is provided, return its temperature.
        Otherwise, return the number of sensors found.
        """
        data = self.coordinator.data or {}
        if self._sensor_ids:
            if len(self._sensor_ids) == 1:
                sensor_data = data.get(self._sensor_ids[0])
                return sensor_data.get("temperature") if sensor_data else None
            return len({sid: data[sid] for sid in self._sensor_ids if sid in data})
        return len(data)

    @property
    def extra_state_attributes(self):
        """Return additional sensor data as attributes."""
        data = self.coordinator.data or {}
        if self._sensor_ids:
            if len(self._sensor_ids) == 1:
                return data.get(self._sensor_ids[0], {})
            return {"sensors": {sid: data[sid] for sid in self._sensor_ids if sid in data}}
        return {"sensors": data}

    @property
    def device_info(self):
        """Return device information about this sensor."""
        return {
            "identifiers": {(DOMAIN, self._sensor_id)},
            "name": f"{self._site_name} Sensor {self._sensor_id}",
            "manufacturer": "OmniSense",
            "model": "Sensor Model XYZ",  # Replace with actual model if available
            "sw_version": "1.0",
            "via_device": (DOMAIN, self._site_name),
        }        

    async def async_update(self):
        """Request an update from the coordinator."""
        await self.coordinator.async_request_refresh()
