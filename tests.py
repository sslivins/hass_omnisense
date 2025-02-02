# test_integration.py
import os
from dotenv import load_dotenv
from custom_components.omnisense.sensor import OmniSenseSensor

load_dotenv()

# Create a test configuration dictionary
config = {
    "site_name": "home",
    "name": "Test Omnisense Sensor",
    "sensor_ids": ["2F360025"],
    "username": os.environ.get("OMNISENSE_USERNAME"),
    "password": os.environ.get("OMNISENSE_PASSWORD"),
}

# Create an instance of your sensor (for one sensor, or loop for multiple sensors)
sensor = OmniSenseSensor(
    name=config["name"],
    site_name=config["site_name"],
    username=config["username"],
    password=config["password"],
    sensor_id=["2F360025","2F360223","2F3603E0","2F36001F","2F360009","2F36022E","2F360022","2F3600E1","2F360142","2F3603AE"]
)

# Run an update and print the output
sensor.update()
print("Sensor state:", sensor.state)
print("Attributes:", sensor.extra_state_attributes)
