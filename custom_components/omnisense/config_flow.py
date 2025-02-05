import re
import logging
import voluptuous as vol
import requests
from bs4 import BeautifulSoup

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN

class OmnisenseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user enters credentials."""
        errors = {}
        if user_input is not None:
            self.username = user_input.get(CONF_USERNAME)
            self.password = user_input.get(CONF_PASSWORD)

            # Validate credentials and fetch available sites
            sites = await self.hass.async_add_executor_job(self._fetch_sites)
            if sites:
                self.available_sites = sites
                return await self.async_step_select_site()
            else:
                errors["base"] = "invalid_auth"

        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_site(self, user_input=None):
        """Handle the site selection step."""
        errors = {}
        if user_input is not None:
            selected_sites = user_input.get("selected_sites", [])
            if selected_sites:
                self.selected_sites = selected_sites
                return await self.async_step_sensors()
            else:
                errors["base"] = "select_at_least_one_site"

        # Create site options mapping site IDs to labels
        site_options = {site_id: site_name for site_id, site_name in self.available_sites.items()}

        schema = vol.Schema({
            vol.Required("selected_sites"): cv.multi_select(site_options)
        })
        return self.async_show_form(step_id="select_site", data_schema=schema, errors=errors)

    async def async_step_sensors(self, user_input=None):
        """Handle the sensor selection step."""
        errors = {}
        if user_input is not None:
            selected_sensors = user_input.get("selected_sensors", [])
            if selected_sensors:
                data = {
                    CONF_USERNAME: self.username,
                    CONF_PASSWORD: self.password,
                    "selected_sites": self.selected_sites,
                    "selected_sensor_ids": selected_sensors,
                }
                return self.async_create_entry(title="Omnisense", data=data)
            else:
                errors["base"] = "select_at_least_one_sensor"

        # Fetch sensors for the selected sites
        sensors = await self.hass.async_add_executor_job(self._fetch_sensors)
        if not sensors:
            errors["base"] = "no_sensors_found"
            return self.async_show_form(step_id="sensors", data_schema=vol.Schema({}), errors=errors)

        # Create sensor options mapping sensor IDs to labels
        available_sensors = {sid: f"{sid} - {info.get('description', '<empty>')}" for sid, info in sensors.items()}

        schema = vol.Schema({
            vol.Required("selected_sensors"): cv.multi_select(available_sensors)
        })
        return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors)

    def _fetch_sites(self):
        """Fetch available sites using the provided credentials."""
        session = requests.Session()
        payload = {
            "userId": self.username,
            "userPass": self.password,
            "btnAct": "Log-In",
            "target": ""
        }
        try:
            response = session.post("https://www.omnisense.com/user_login.asp", data=payload, timeout=10)
            if response.status_code != 200 or "User Log-In" in response.text:
                return {}

            response = session.get("https://www.omnisense.com/site_select.asp", timeout=10)
            if response.status_code != 200:
                return {}

            soup = BeautifulSoup(response.text, "html.parser")
            sites = {}
            for link in soup.find_all("a", onclick=True):
                onclick = link.get("onclick", "")
                match = re.search(r"ShowSiteDetail\('(\d+)'\)", onclick)
                if match:
                    site_id = match.group(1)
                    site_name = link.get_text(strip=True)
                    sites[site_id] = site_name
            return sites
        except Exception as e:
            _LOGGER.error("Error fetching sites: %s", e)
            return {}

    def _fetch_sensors(self):
        """Fetch sensors for the selected sites using the stored credentials."""
        session = requests.Session()
        payload = {
            "userId": self.username,
            "userPass": self.password,
            "btnAct": "Log-In",
            "target": ""
        }
        try:
            response = session.post("https://www.omnisense.com/user_login.asp", data=payload, timeout=10)
            if response.status_code != 200 or "User Log-In" in response.text:
                return {}

            sensors = {}
            for site_id in self.selected_sites:
                sensor_page_url = f"https://www.omnisense.com/sensor_select.asp?siteNbr={site_id}"
                response = session.get(sensor_page_url, timeout=10)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                for table in soup.select("table.sortable.table"):
                    for row in table.select("tr.sensorTable"):
                        tds = row.find_all("td")
                        if len(tds) >= 10:
                            sid = tds[0].get_text(strip=True)
                            desc = tds[1].get_text(strip=True)
                            if desc == "~click to edit~":
                                desc = "<description not set>"
                            sensors[sid] = {"description": desc}

            _LOGGER.debug("Fetched sensors: %s", sensors)
            return sensors
        except Exception as e:
            _LOGGER.error("Error fetching sensors: %s", e)
            return {}
