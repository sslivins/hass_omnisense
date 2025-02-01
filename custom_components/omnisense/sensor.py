import os
import re
import logging
import requests
from bs4 import BeautifulSoup
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

# Configuration keys
CONF_SITE_NAME = "site_name"       # The name of the site (e.g., "home")
CONF_SENSOR_IDS = "sensor_ids"     # List of sensor IDs to extract (empty = all)
CONF_USERNAME = "username"         # Login username
CONF_PASSWORD = "password"         # Login password

# Defaults
DEFAULT_NAME = "Scraped Temperature Sensors"
DEFAULT_JOB_SITES_URL = "https://www.omnisense.com/site_select.asp"
DEFAULT_SENSOR_IDS = []   # if provided, filter sensors by these IDs (if empty, retrieve all)

# Fixed URLs
LOGIN_URL = "https://www.omnisense.com/user_login.asp"
SITE_LIST_URL = "https://www.omnisense.com/site_select.asp"

# Extend the platform schema
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SITE_NAME): cv.string,
    vol.Optional(CONF_SENSOR_IDS, default=DEFAULT_SENSOR_IDS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_USERNAME): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
})

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Omnisense sensor."""
    site_name = config.get(CONF_SITE_NAME)
    sensor_ids = config.get(CONF_SENSOR_IDS)
    username = config.get(CONF_USERNAME) or os.environ.get("OMNISENSE_USERNAME")
    password = config.get(CONF_PASSWORD) or os.environ.get("OMNISENSE_PASSWORD")

    if not username or not password:
        _LOGGER.error("Missing credentials: please supply username and password via configuration or environment variables")
        return

    entities = []
    # If sensor_ids are provided, create one entity per sensor.
    if sensor_ids:
        for sid in sensor_ids:
            sensor_name = f"{site_name.capitalize()} Sensor {sid}"
            entities.append(OmniSenseSensor(sensor_name, username, password, site_name, sensor_id=sid))
    else:
        # Otherwise, create a single entity that aggregates all sensors.
        entities.append(OmniSenseSensor(site_name.capitalize(), username, password, site_name, sensor_id=None))
    add_entities(entities, True)

class OmniSenseSensor(SensorEntity):
    """Representation of a sensor entity that scrapes sensor data from an HTML table.

    If sensor_ids (a list) is non-empty, only include rows whose sensor id is in that list.
    Otherwise, retrieve data for all sensors.
    If exactly one sensor id is provided and found, the state is that sensor's temperature.
    Otherwise, the state is the count of sensors found.
    An additional attribute 'sensor_type' is added for each sensor.
    """

    def __init__(self, name, username, password, site_name, sensor_id=None):
        """Initialize the sensor."""
        self._name = name
        self._username = username
        self._password = password
        self._site_name = site_name
        self._sensor_ids = sensor_id if isinstance(sensor_id, list) else ([sensor_id] if sensor_id else [])
        self._state = None
        self._attributes = {}

    @property
    def name(self):
        """Return the sensor name."""
        return self._name

    @property
    def state(self):
        """Return the sensor state."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return additional sensor data as attributes."""
        return self._attributes

    def login(self):
        """Log in to the website and return a session with authenticated cookies."""
        session = requests.Session()
        payload = {
            "userId": self._username,
            "userPass": self._password,
            "btnAct": "Log-In",
            "target": ""
        }
        try:
            _LOGGER.info(f"Logging in as {self._username}")
            response = session.post(LOGIN_URL, data=payload, timeout=10)
            if response.status_code == 200:
                if "User Log-In" in response.text:
                    _LOGGER.error("Login appears to have failed; check your credentials.")
                    return None
                return session
            else:
                _LOGGER.error("Login failed: HTTP %s", response.status_code)
                return None
        except requests.RequestException as err:
            _LOGGER.error("Error during login request: %s", err)
            return None

    def get_sensor_page_url(self, session):
        """
        Determine the sensor page URL.

        If a site name is provided, load the job sites page,
        locate the row for that site, extract its site number, and
        construct the sensor page URL.
        """
        if self._site_name:
            try:
                response = session.get(DEFAULT_JOB_SITES_URL, timeout=10)
                if response.status_code != 200:
                    _LOGGER.error("Error fetching job sites page: HTTP %s", response.status_code)
                    return None
                soup = BeautifulSoup(response.text, "html.parser")
                # Look for the <a> element whose text matches the site name (case-insensitive).
                site_link = soup.find("a", text=lambda t: t and t.strip().lower() == self._site_name.lower())
                if not site_link:
                    _LOGGER.error("Site with name '%s' not found", self._site_name)
                    return None
                # The site number is embedded in the onclick attribute, e.g.: ShowSiteDetail('119345');
                onclick = site_link.get("onclick", "")
                match = re.search(r"ShowSiteDetail\('(\d+)'\)", onclick)
                if not match:
                    _LOGGER.error("Could not extract site number from onclick attribute: %s", onclick)
                    return None
                site_number = match.group(1)
                sensor_page_url = f"https://www.omnisense.com/sensor_select.asp?siteNbr={site_number}"
                _LOGGER.debug("Constructed sensor page URL: %s", sensor_page_url)
                return sensor_page_url
            except requests.RequestException as err:
                _LOGGER.error("Error fetching job sites page: %s", err)
                return None
        else:
            _LOGGER.error("No site name provided; cannot determine sensor page URL.")
            return None

    def update(self):
        """Perform login, select the site, load the sensor page, and parse sensor data."""
        session = self.login()
        if not session:
            _LOGGER.error("Unable to log in; skipping update.")
            return

        sensor_page_url = self.get_sensor_page_url(session)
        if not sensor_page_url:
            _LOGGER.error("Could not determine sensor page URL.")
            return

        try:
            response = session.get(sensor_page_url, timeout=10)
            if response.status_code != 200:
                _LOGGER.error("Error fetching sensor data: HTTP %s", response.status_code)
                return

            soup = BeautifulSoup(response.text, "html.parser")
            sensors = {}

            # Iterate over each table that is expected to hold sensor data.
            for table in soup.select("table.sortable.table"):
                # Try to determine sensor type from the table's id, e.g., "sensorType11" or "sensorType100"
                sensor_type = None
                table_id = table.get("id", "")
                if table_id.startswith("sensorType"):
                    sensor_type = table_id[len("sensorType"):]
                # If not found via id, try to parse the caption text.
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
                        # If a sensor_ids filter is applied, skip rows not in that list.
                        if self._sensor_ids and sid not in self._sensor_ids:
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
            # If a filter on sensor_ids was applied:
            if self._sensor_ids:
                # If exactly one sensor id is provided and found, use its temperature as the state.
                if len(self._sensor_ids) == 1 and sensors:
                    sensor_data = sensors.get(self._sensor_ids[0])
                    if sensor_data:
                        self._state = sensor_data.get("temperature")
                        self._attributes = sensor_data
                        return
                # Otherwise, state is the number of matching sensors.
                self._state = len(sensors)
                self._attributes = {"sensors": sensors}
            else:
                # No filter: aggregate all sensor data.
                self._state = len(sensors)
                self._attributes = {"sensors": sensors}
        except requests.RequestException as err:
            _LOGGER.error("Error fetching sensor data: %s", err)
