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

#
# --- YAML Setup (Legacy) ---
#
def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Omnisense sensor from YAML configuration."""
    site_name = config.get(CONF_SITE_NAME)
    sensor_ids = config.get(CONF_SENSOR_IDS)
    username = config.get(CONF_USERNAME) or os.environ.get("OMNISENSE_USERNAME")
    password = config.get(CONF_PASSWORD) or os.environ.get("OMNISENSE_PASSWORD")

    if not username or not password:
        _LOGGER.error("Missing credentials: please supply username and password via configuration or environment variables")
        return

    entities = []
    if sensor_ids:
        for sid in sensor_ids:
            sensor_name = f"{site_name.capitalize()} Sensor {sid}"
            entities.append(OmniSenseSensor(sensor_name, username, password, site_name, sensor_id=sid))
    else:
        entities.append(OmniSenseSensor(site_name.capitalize(), username, password, site_name, sensor_id=None))
    add_entities(entities, True)


#
# --- Helper Function: Data Fetching ---
#
def _fetch_sensor_data(username, password, site_name, sensor_ids):
    """Fetch sensor data from Omnisense and return a dictionary of sensor data.
    
    This function runs synchronously and is intended to be called in an executor.
    """
    session = requests.Session()
    # --- Login ---
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

    # --- Determine Sensor Page URL ---
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

    # --- Fetch and Parse Sensor Data ---
    try:
        response = session.get(sensor_page_url, timeout=10)
        if response.status_code != 200:
            raise Exception("Error fetching sensor data.")
        soup = BeautifulSoup(response.text, "html.parser")
        sensors = {}
        # Iterate over each table that holds sensor data.
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
                    sensors[sid] = {
                        "description": tds[1].get_text(strip=True),
                        "last_activity": tds[2].get_text(strip=True),
                        "status": tds[3].get_text(strip=True),
                        "temperature": temperature,
                        "humidity": tds[5].get_text(strip=True),
                        "gpkg": tds[6].get_text(strip=True),
                        "dew_point": tds[7].get_text(strip=True),
                        "wood_pct": tds[8].get_text(strip=True),
                        "battery_voltage": tds[9].get_text(strip=True),
                        "sensor_type": sensor_type,
                    }
        return sensors
    except Exception as err:
        _LOGGER.error("Error fetching/parsing sensor data: %s", err)
        return {}

#
# --- Config Entry Setup (UI Integration) using DataUpdateCoordinator ---
#
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
        update_interval=timedelta(minutes=60),
    )

    # Fetch initial data.
    await coordinator.async_config_entry_first_refresh()

    entities = []
    if sensor_ids:
        for sid in sensor_ids:
            sensor_name = f"{site_name.capitalize()} Sensor {sid}"
            entities.append(OmniSenseSensor(sensor_name, site_name, coordinator, sensor_id=sid))
    else:
        entities.append(OmniSenseSensor(site_name.capitalize(), site_name, coordinator, sensor_id=None))

    async_add_entities(entities)
    return True

#
# --- Sensor Entity Class using Coordinator ---
#
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

    async def async_update(self):
        """Request an update from the coordinator."""
        await self.coordinator.async_request_refresh()
