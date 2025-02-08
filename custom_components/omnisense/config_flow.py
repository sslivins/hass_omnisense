import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from .const import CONF_SELECTED_SITES, CONF_SELECTED_SENSORS
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import SelectSelector
from .omnisense import Omnisense

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN

class OmnisenseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self):
        self.omnisense = Omnisense()

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user enters credentials."""
        errors = {}
        if user_input is not None:
            self.username = user_input.get(CONF_USERNAME)
            self.password = user_input.get(CONF_PASSWORD)

            try:
                 await self.omnisense.login(self.username, self.password)
            except Exception as err:  # or a more specific exception if known
                _LOGGER.error("Failed to create Omnisense instance: %s", err)
                errors["base"] = "omnisense_login_failed"
   
            # Validate credentials and fetch available sites
            try:
                sites = await self.omnisense.get_site_list()
                if sites:
                    self.available_sites = sites
                    return await self.async_step_select_site()
                else:
                    errors["base"] = "no_sites_found"
            except Exception as err:  # or a more specific exception if known
                _LOGGER.error("Error fetching site list: %s", err)
                errors["base"] = "failed_to_get_sites"

        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_site(self, user_input=None):
        """Handle the site selection step."""
        errors = {}
        if user_input is not None:
            selected_sites = user_input.get(CONF_SELECTED_SITES, [])
            if selected_sites:
                self.selected_sites = {site_id: self.available_sites[site_id] for site_id in selected_sites}
                return await self.async_step_sensors()
            else:
                errors["base"] = "select_at_least_one_site"

        # Create site options mapping site IDs to labels
        # site_options = {site_id: site_name for site_id, site_name in self.available_sites.items()}

        # schema = vol.Schema({
        #     vol.Required("selected_sites"): cv.multi_select(site_options)
        # })

        schema = vol.Schema({
            vol.Required("selected_sites"): SelectSelector({
                "options": [
                    {"value": site_id, "label": site_name} for site_id, site_name in self.available_sites.items()
                ],
                "multiple": True,
            })
        })

        return self.async_show_form(step_id="select_site", data_schema=schema, errors=errors)

    async def async_step_sensors(self, user_input=None):
        """Handle the sensor selection step."""
        errors = {}
        if user_input is not None:
            selected_sensors = user_input.get(CONF_SELECTED_SENSORS, [])
            if selected_sensors:
                data = {
                    CONF_USERNAME: self.username,
                    CONF_PASSWORD: self.password,
                    CONF_SELECTED_SITES: self.selected_sites,
                    CONF_SELECTED_SENSORS: selected_sensors,
                }
                return self.async_create_entry(title="Omnisense", data=data)
            else:
                errors["base"] = "no_sensors_selected"

        # Fetch sensors for the selected sites
        #sensors = await self.hass.async_add_executor_job(self._fetch_sensors)
        sensors = await self.omnisense.get_site_sensor_list(self.selected_sites.keys())
        if not sensors:
            errors["base"] = "no_sensors_found"
            return self.async_show_form(step_id="sensors", data_schema=vol.Schema({}), errors=errors)

        # Create sensor options mapping sensor IDs to labels
        available_sensors = {sid: f"{sid} - {info.get('sensor_type', "")} - {info.get('description', '<empty>')}" for sid, info in sensors.items()}

        # schema = vol.Schema({
        #     vol.Required("selected_sensors"): cv.multi_select(available_sensors)
        # })

        schema = vol.Schema({
            vol.Required("selected_sensors"): SelectSelector({
                "options": [
                    {"value": sid, "label": name} for sid, name in available_sensors.items()
                ],
                "multiple": True,
                "mode" : "list"
            })
        })

        return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors)
    
    async def async_finish_flow(self, result):
        if self.omnisense:
            await self.omnisense.close()

        return result
        
