# config_flow.py
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

DOMAIN = "omnisense"  # Must match the domain in your manifest.json

class OmnisenseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Convert the sensor_ids input (a comma separated string) into a list.
            sensor_ids_str = user_input.get("sensor_ids", "")
            if sensor_ids_str:
                user_input["sensor_ids"] = [s.strip() for s in sensor_ids_str.split(",") if s.strip()]
            else:
                user_input["sensor_ids"] = []
            return self.async_create_entry(title="Omnisense", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional("site_name", default="Home"): str,
            # Use a string input for sensor_ids. The user can enter a comma-separated list.
            vol.Optional("sensor_ids", default=""): str,
        })
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
