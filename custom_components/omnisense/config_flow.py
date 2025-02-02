# config_flow.py
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

DOMAIN = "omnisense"

class OmnisenseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="Omnisense", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional("site_name", default="Home"): str,
            vol.Optional("sensor_ids", default=[]): list,
        })
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
