import os
import re
import logging
import requests
import async_timeout
from datetime import timedelta, datetime
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity, SensorDeviceClass
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed
from homeassistant.core import callback

import numpy as np
from scipy.interpolate import interp1d

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Configuration keys
CONF_SITE_NAME = "site_name"       # The name of the site (e.g., "home")
CONF_SENSOR_IDS = "sensor_ids"     # List of sensor IDs to extract (empty = all)
CONF_USERNAME = "username"         # Login username
CONF_PASSWORD = "password"         # Login password


# Fixed URLs
LOGIN_URL = "https://www.omnisense.com/user_login.asp"
SITE_LIST_URL = "https://www.omnisense.com/site_select.asp"
SENSOR_LIST_URL = "https://www.omnisense.com/sensor_select.asp"

async def _fetch_sensor_data(username, password, sites, sensor_ids=None):
    """Fetch sensor data from Omnisense for specified sites asynchronously and return a dictionary of sensor data."""
    payload = {
        "userId": username,
        "userPass": password,
        "btnAct": "Log-In",
        "target": ""
    }

    async with aiohttp.ClientSession() as session:
        try:
            # Perform login
            async with session.post(LOGIN_URL, data=payload, timeout=10) as response:
                if response.status != 200 or "User Log-In" in await response.text():
                    raise Exception("Login failed; check your credentials.")
        except Exception as err:
            _LOGGER.error("Error during login: %s", err)
            return {}

        try:
            # Fetch site list
            async with session.get(SITE_LIST_URL, timeout=10) as response:
                if response.status != 200:
                    raise Exception("Error fetching job sites page.")
                soup = BeautifulSoup(await response.text(), "html.parser")
        except Exception as err:
            _LOGGER.error("Error fetching site list: %s", err)
            return {}

        all_sensors = {}
        for site_id, site_name in sites.items():
            sensor_page_url = f"{SENSOR_LIST_URL}?siteNbr={site_id}"

            try:
                async with session.get(sensor_page_url, timeout=10) as response:
                    if response.status != 200:
                        raise Exception(f"Error fetching sensor data for site '{site_name}'.")
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    for table in soup.select("table.sortable.table"):
                        sensor_type = None
                        table_id = table.get("id", "")
                        if table_id.startswith("sensorType"):
                            sensor_type = f"S-{table_id[len("sensorType"):]}"
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
                                    "relative_humidity": tds[5].get_text(strip=True),
                                    "absolute_humidity": tds[6].get_text(strip=True),
                                    "dew_point": tds[7].get_text(strip=True),
                                    "wood_pct": tds[8].get_text(strip=True),
                                    "battery_voltage": tds[9].get_text(strip=True),
                                    "sensor_type": sensor_type,
                                    "sensor_id": sid,
                                    "site_name": site_name,
                                }
            except Exception as err:
                _LOGGER.error("Error fetching/parsing sensor data for site '%s': %s", site_name, err)

        _LOGGER.debug(f"Got Sensor Data: {all_sensors}")

        return all_sensors


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Omnisense sensor(s) from a config entry using DataUpdateCoordinator."""

    coordinator = OmniSenseCoordinator(hass, entry.data)

    await coordinator.async_config_entry_first_refresh()

    entities = []

    for idx, sid in enumerate(coordinator.data):
        entities.append(TemperatureSensor(coordinator, sid))
        entities.append(SensorBatteryLevel(coordinator, sid))
        entities.append(SensorLastActivity(coordinator, sid))
        entities.append(SensorRelativeHumidity(coordinator, sid))
        entities.append(SensorAbsoluteHumidity(coordinator, sid))
        entities.append(SensorWoodMoisture(coordinator, sid))
        entities.append(SensorDewPoint(coordinator, sid))
        
    async_add_entities(entities)

    return True

class OmniSenseCoordinator(DataUpdateCoordinator):
    """custom coordinator."""

    def __init__(self, hass, data):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=45),
            update_method=self._omnisense_async_update_data,
        )

        self.username = data.get("username")
        self.password = data.get("password")
        self.sites = data.get("selected_sites", [])
        self.sensor_ids = data.get("selected_sensor_ids", [])

    async def _async_setup(self):

        self.update_interval = timedelta(seconds=45)
    #     """Set up the coordinator

    #     This is the place to set up your coordinator,
    #     or to load data, that only needs to be loaded once.

    #     This method will be called automatically during
    #     coordinator.async_config_entry_first_refresh.
    #     """

    async def _omnisense_async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        _LOGGER.debug(f"Fetching new sensor data")
        async with async_timeout.timeout(10):
            return await _fetch_sensor_data(self.username, self.password, self.sites, self.sensor_ids)


class SensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Omnisense entities."""

    should_poll = True

    def __init__(self, coordinator=None, sid=None):

        super().__init__(coordinator)
        self._sid = sid

        self.sensor_data = self.coordinator.data.get(self._sid, {})

        self._sid = self.sensor_data.get('sensor_id', 'Unknown')
        self._sensor_name = self.sensor_data.get('description', 'Unknown')
        self._sensor_type = self.sensor_data.get('sensor_type', 'Unknown')

    @property
    def device_info(self):
        """Return device information about this sensor."""
        return {
            "identifiers": {(DOMAIN, self._sid)},
            "name": self._sensor_name,
            "manufacturer": "OmniSense",
            "model": self._sensor_type,
            "sw_version": "N/A",
        }

class TemperatureSensor(SensorBase):

    device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator=None, sid=None):
        """Initialize the sensor."""

        super().__init__(coordinator, sid)

        _LOGGER.debug(f"Initializing temperature entity for sensor: {self._sid}")        

        self._attr_unique_id = f"{self._sid}_temperature"
        self._attr_name = f"{self._sensor_name} Temperature"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        self._value = self.sensor_data.get('temperature', 'Unknown') 

    @callback
    def _handle_coordinator_update(self) -> None:
        self._extract_value()
        _LOGGER.debug(f"Updating sensor: {self._attr_name} = {self.native_value}{self.native_unit_of_measurement}")
        self.async_write_ha_state()
   
    @property
    def native_value(self) -> float:
        return self._value

    @property
    def native_unit_of_measurement(self):
        return "°C"    
    
class SensorBatteryLevel(SensorBase):
    #battery is a ER14505 3.6V Lithium Thionyl Chloride Battery
    voltage_soc_table = [
        (3.65, 100), (3.60, 95), (3.58, 90),
        (3.55, 85), (3.50, 80), (3.48, 75),
        (3.45, 70), (3.42, 60), (3.40, 50),
        (3.38, 40), (3.35, 30), (3.30, 20),
        (3.20, 10), (3.10, 5), (3.00, 2),
        (2.80, 1), (2.70, 0)
    ]

    device_class = SensorDeviceClass.BATTERY
    _attr_icon = "mdi:battery"
    # Extract separate lists for interpolation
    voltages, soc_values = zip(*voltage_soc_table)

    # Use cubic spline interpolation for smoothness
    soc_interpolator = interp1d(voltages, soc_values, kind='cubic', fill_value="extrapolate")

    def __init__(self, coordinator=None, sid=None):
        """Initialize the sensor."""

        super().__init__(coordinator, sid)

        _LOGGER.debug(f"Initializing battery entity for sensor: {self._sid}")        

        self._attr_unique_id = f"{self._sid}_battery"
        self._attr_name = f"{self._sensor_name} Battery Level"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        self.battery_voltage = self.sensor_data.get('battery_voltage', 'Unknown')
        self._value = self._estimate_soc(float(self.battery_voltage))      

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._extract_value()
        self.async_write_ha_state()

    
    def _estimate_soc(self, voltage):
        estimated_soc = self.soc_interpolator(voltage)
        return max(0, min(100, round(float(estimated_soc), 2)))
    
    @property    
    def native_value(self) -> float:
        return self._value
    
    @property
    def native_unit_of_measurement(self):
        return "%"
    
class SensorLastActivity(SensorBase):

    device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)

        self._attr_unique_id = f"{self._sid}_last_activity"
        self._attr_name = f"{self._sensor_name} Last Activity"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        last_activity = self.sensor_data.get('last_activity', 'Unknown')
        self._value = datetime.strptime(last_activity, "%y-%m-%d %H:%M:%S") #24-12-30 10:59:40

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._extract_value()
        self.async_write_ha_state()

    @property    
    def native_value(self) -> datetime:
        return self._value
    
    
class SensorRelativeHumidity(SensorBase):

    device_class = SensorDeviceClass.HUMIDITY
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)

        self._attr_unique_id = f"{self._sid}_relative_humidity"
        self._attr_name = f"{self._sensor_name} Relative Humidity"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        self._value = self.sensor_data.get('relative_humidity', 'Unknown')

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._extract_value()
        self.async_write_ha_state()

    @property    
    def native_value(self) -> float:
        return self._value
    
    @property
    def native_unit_of_measurement(self):
        return "%"   
    

class SensorAbsoluteHumidity(SensorBase):

    device_class = SensorDeviceClass.HUMIDITY
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)

        self._attr_unique_id = f"{self._sid}_absolute_humidity"
        self._attr_name = f"{self._sensor_name} Absolute Humidity"
        self._value = None 
        self._extract_value()

    def _extract_value(self):
        self._value = self.sensor_data.get('absolute_humidity', 'Unknown')

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._extract_value()
        self.async_write_ha_state()

    @property    
    def native_value(self) -> float:
        return self._value
    
    @property
    def native_unit_of_measurement(self):
        return "g/m³" 
    
class SensorWoodMoisture(SensorBase):

    device_class = SensorDeviceClass.MOISTURE
    _attr_icon = "mdi:water"

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)

        self._attr_unique_id = f"{self._sid}_wood_moisture"
        self._attr_name = f"{self._sensor_name} Wood Moistute"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        self._value = self.sensor_data.get('wood_pct', 'Unknown')

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._extract_value()
        self.async_write_ha_state()

    @property    
    def native_value(self) -> float:
        return self._value
    
    @property
    def native_unit_of_measurement(self):
        return "%"     
    

class SensorDewPoint(SensorBase):

    device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)

        self._attr_unique_id = f"{self._sid}_dew_point"
        self._attr_name = f"{self._sensor_name} Dew Point"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        self._value = self.sensor_data.get('dew_point', 'Unknown')

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._extract_value()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def native_unit_of_measurement(self):
        return "°C"   