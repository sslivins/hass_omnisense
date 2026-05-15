import os
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
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from .const import CONF_SELECTED_SITES, CONF_SELECTED_SENSORS

from pyomnisense import Omnisense, OmnisenseAuthError, OmnisenseError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Omnisense sensor(s) from a config entry using DataUpdateCoordinator."""

    coordinator = OmniSenseCoordinator(hass, entry.data)
    await coordinator._async_setup()  # Ensure login/setup is done before first refresh

    # Store the coordinator keyed by entry_id so multiple config entries
    # can coexist and async_unload_entry can find it.
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

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
        entities.append(SensorBatteryVoltage(coordinator, sid))
        
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
            update_interval=timedelta(minutes=15),
            update_method=self._omnisense_async_update_data,
        )

        self.username = data.get(CONF_USERNAME)
        self.password = data.get(CONF_PASSWORD)
        self.sites = data.get(CONF_SELECTED_SITES, [])
        self.sensor_ids = data.get(CONF_SELECTED_SENSORS, [])

        self.omnisense = Omnisense()

    async def _async_setup(self):

        try:
            success = await self.omnisense.login(self.username, self.password)
        except OmnisenseAuthError as err:
            _LOGGER.error("Omnisense login rejected: %s", err)
            raise UpdateFailed("Failed to login to Omnisense with provided credentials")
        except OmnisenseError as err:
            _LOGGER.error("Omnisense login failed: %s", err)
            raise UpdateFailed(f"Failed to login to Omnisense: {err}")

        if not success:
            _LOGGER.error("Failed to login to omnisense with provided credentials")
            raise UpdateFailed("Failed to login to Omnisense with provided credentials")
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
        async with async_timeout.timeout(30):
            try:
                data = await self.omnisense.get_sensor_data(self.sites, self.sensor_ids)
                _LOGGER.debug(f"Fetched sensor data: {data}")
            except OmnisenseAuthError as err:
                _LOGGER.error("Omnisense authentication failed during fetch: %s", err)
                raise UpdateFailed(f"Authentication failed: {err}")
            except OmnisenseError as err:
                _LOGGER.error("Error fetching sensor data: %s", err)
                raise UpdateFailed(f"Error fetching sensor data: {err}")

            return data


class SensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Omnisense entities."""

    should_poll = False

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator)
        self._sid = sid

        # These can be set once, as they are static
        sid = self._get_sensor_data('sensor_id')
        if sid != self._sid:
            _LOGGER.warning(f"Sensor ID mismatch: expected {self._sid}, got {sid}. Using {self._sid} instead.")
        
        self._sensor_name = self._get_sensor_data('description')
        self._sensor_type = self._get_sensor_data('sensor_type')

    def _get_sensor_data(self, field=None, error_value='Unknown'):
        data = self.coordinator.data.get(self._sid, {})
        if field is None:
            return data
        value = data.get(field, error_value)
        if value is None:
            return error_value
        return value

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
        self._value = self._get_sensor_data('temperature', error_value=None)

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
    device_class = SensorDeviceClass.BATTERY
    _attr_icon = "mdi:battery"

    FULL_VOLTAGE = 3.40  # Voltage of a new battery
    EMPTY_VOLTAGE = 2.80  # Voltage considered empty
    STEP_VOLTAGE = 0.03   # Voltage drop per 10% step

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)
        _LOGGER.debug(f"Initializing battery entity for sensor: {self._sid}")        
        self._attr_unique_id = f"{self._sid}_battery"
        self._attr_name = f"{self._sensor_name} Battery Level"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        # pyomnisense >= 0.3.0 returns battery_voltage as Optional[float].
        self.battery_voltage = self._get_sensor_data(
            'battery_voltage', error_value=None,
        )
        voltage = self.battery_voltage if self.battery_voltage is not None else 0
        self._value = self._estimate_soc(voltage)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._extract_value()
        self.async_write_ha_state()

    def _estimate_soc(self, voltage):
        if voltage >= self.FULL_VOLTAGE:
            return 100
        if voltage <= self.EMPTY_VOLTAGE:
            return 0
        percent = ((voltage - self.EMPTY_VOLTAGE) / (self.FULL_VOLTAGE - self.EMPTY_VOLTAGE)) * 100
        return round(percent)

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
        # pyomnisense >= 0.3.0 returns last_activity as a tz-aware UTC
        # datetime (or None when the cell is missing). HA renders it in
        # the user's local timezone via SensorDeviceClass.TIMESTAMP.
        self._value = self._get_sensor_data('last_activity', error_value=None)

        _LOGGER.debug(f"Updating sensor: {self._attr_name} = last activity at {self._value}")

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
        self._value = self._get_sensor_data('relative_humidity', error_value=None)           

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

    device_class = None
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)

        self._attr_unique_id = f"{self._sid}_absolute_humidity"
        self._attr_name = f"{self._sensor_name} Absolute Humidity"
        self._value = None 
        self._extract_value()

    def _extract_value(self):

        self._value = self._get_sensor_data('absolute_humidity')           
        

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

        self._value = self._get_sensor_data('wood_pct', error_value=None)

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
        
        self._value = self._get_sensor_data('dew_point', error_value=None)           
        

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
    
class SensorBatteryVoltage(SensorBase):
    device_class = SensorDeviceClass.VOLTAGE
    _attr_icon = "mdi:battery"
    _attr_suggested_display_precision = 1  # Show 1 decimal place

    def __init__(self, coordinator=None, sid=None):
        super().__init__(coordinator, sid)
        self._attr_unique_id = f"{self._sid}_battery_voltage"
        self._attr_name = f"{self._sensor_name} Battery Voltage"
        self._value = None
        self._extract_value()

    def _extract_value(self):
        # pyomnisense >= 0.3.0 returns battery_voltage as Optional[float].
        value = self._get_sensor_data('battery_voltage', error_value=None)
        self._value = round(value, 1) if value is not None else None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._extract_value()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def native_unit_of_measurement(self):
        return "V"