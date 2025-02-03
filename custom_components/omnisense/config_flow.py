# config_flow.py
import re
import logging
import voluptuous as vol
import requests
from bs4 import BeautifulSoup

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import selector

_LOGGER = logging.getLogger(__name__)

DOMAIN = "omnisense"  # Must match the domain in your manifest.json

class OmnisenseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user enters credentials and site name."""
        errors = {}
        if user_input is not None:
            # Save credentials and site name for use in the next step.
            self.username = user_input.get(CONF_USERNAME)
            self.password = user_input.get(CONF_PASSWORD)
            self.site_name = user_input.get("site_name", "Home")
            return await self.async_step_sensors()
        
        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional("site_name", default="Home"): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_sensors(self, user_input=None):
        """Handle the sensor selection step."""
        errors = {}
        if user_input is not None:
            selected = user_input.get("selected_sensors", [])
            if not selected:
                errors["base"] = "At least one sensor must be selected."
            else:
                data = {
                    CONF_USERNAME: self.username,
                    CONF_PASSWORD: self.password,
                    "site_name": self.site_name,
                    "sensor_ids": selected,
                }
                return self.async_create_entry(title="Omnisense", data=data)
        
        # Fetch sensor list using provided credentials.
        sensors = await self.hass.async_add_executor_job(self._fetch_sensors)
        if not sensors:
            errors["base"] = "Could not retrieve sensor list. Please verify your credentials and site name."
            return self.async_show_form(step_id="sensors", data_schema=vol.Schema({}), errors=errors)
        
        # Create sensor options mapping sensor IDs to labels.
        sensor_options = {sid: f"{sid} - {info.get('description', '')}" for sid, info in sensors.items()}
        # Use the selector helper to render a multi-select as a list.
        schema = vol.Schema({
            vol.Required("selected_sensors"): selector({
                "select": {
                    "multiple": True,
                    "options": sensor_options,
                }
            })
        })
        # schema = vol.Schema({
        #     vol.Required("selected_sensors", default=""): str,
        # })        
        return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors)

    def _fetch_sensors(self):
        """Fetch sensor list using the stored credentials and site name.
        
        Returns:
            A dictionary mapping sensor IDs to a dictionary containing at least a 'description'.
        """
        
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
        except Exception:
            return {}
        try:
            response = session.get("https://www.omnisense.com/site_select.asp", timeout=10)
            if response.status_code != 200:
                return {}
            soup = BeautifulSoup(response.text, "html.parser")
            site_link = soup.find("a", text=lambda t: t and t.strip().lower() == self.site_name.lower())
            if not site_link:
                return {}
            onclick = site_link.get("onclick", "")
            match = re.search(r"ShowSiteDetail\('(\d+)'\)", onclick)
            if not match:
                return {}
            site_number = match.group(1)
            sensor_page_url = f"https://www.omnisense.com/sensor_select.asp?siteNbr={site_number}"
        except Exception:
            return {}
        try:
            response = session.get(sensor_page_url, timeout=10)
            if response.status_code != 200:
                return {}
            soup = BeautifulSoup(response.text, "html.parser")
            sensors = {}
            for table in soup.select("table.sortable.table"):
                for row in table.select("tr.sensorTable"):
                    tds = row.find_all("td")
                    if len(tds) >= 10:
                        sid = tds[0].get_text(strip=True)
                        desc = tds[1].get_text(strip=True)
                        sensors[sid] = {"description": desc}
                        
            _LOGGER.debug("Fetched sensors: %s", sensors)                        
                        
            return sensors
        except Exception:
            return {}
