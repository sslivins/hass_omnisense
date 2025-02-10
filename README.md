# hass_omnisense

![HACS validation](https://github.com/sslivins/pyomnisense/actions/workflows/hacs_validate.yml/badge.svg)
![Hassfest Validation](https://github.com/sslivins/pyomnisense/actions/workflows/hassfest.yml/badge.svg)

Home Assistant integration for OmniSense sensors.

## Overview

This integration allows you to connect and monitor OmniSense sensors (omnisense.com) within your Home Assistant setup. It supports various sensor types including temperature, humidity, battery level, and more.

## Features

- Monitor temperature, humidity, battery level, and other sensor data.
- Supports multiple OmniSense sites and sensors.
- Easy setup through Home Assistant's configuration flow.

## Installation

1. Open the Home Assistant web interface.
2. Navigate to `HACS`.
3. Click on the three dots and select `Custom Repositories`
4. Set the _Repository_ to `https://github.com/sslivins/hass_omnisense` and the _Type_ to `Integration`
6. Restart Home Assistant.

## Configuration

1. Go to the Home Assistant web interface.
2. Navigate to `Settings` > `Devices and Services`.
3. Click on the `+ Add Integration` button.
4. Search for `OmniSense` and follow the setup instructions.

## Usage

Once configured, the integration will automatically add sensors for the selected OmniSense sites and sensors. You can view and manage these sensors from the Home Assistant dashboard.

