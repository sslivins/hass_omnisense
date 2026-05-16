<h1 align="center">
  <img src="custom_components/omnisense/brand/icon.png" width="96" alt="OmniSense"><br>
  OmniSense for Home Assistant
</h1>

<p align="center">
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="https://github.com/sslivins/hass_omnisense/releases/latest"><img src="https://img.shields.io/github/v/release/sslivins/hass_omnisense?display_name=tag&sort=semver" alt="GitHub release"></a>
  <a href="https://github.com/sslivins/hass_omnisense/actions/workflows/hacs_validate.yml"><img src="https://github.com/sslivins/hass_omnisense/actions/workflows/hacs_validate.yml/badge.svg" alt="HACS Validation"></a>
  <a href="https://github.com/sslivins/hass_omnisense/actions/workflows/hassfest.yml"><img src="https://github.com/sslivins/hass_omnisense/actions/workflows/hassfest.yml/badge.svg" alt="Hassfest"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/sslivins/hass_omnisense" alt="License"></a>
</p>

<p align="center">
  Pull live readings from your <a href="https://www.omnisense.com">OmniSense</a>
  wireless temperature / humidity sensors into Home Assistant — every
  site and every sensor on your account, discovered automatically.
</p>

---

## Features

- 🔌 **One-click install** via HACS (button below).
- 🌡️ **Temperature** sensor per OmniSense sensor.
- 💧 **Humidity** sensor per OmniSense sensor.
- 🔋 **Battery level** sensor per OmniSense sensor.
- 🏠 **Multi-site** — every site and every sensor on your account is
  discovered automatically.
- 🛠️ **Config-flow setup** — just enter your OmniSense credentials,
  no YAML needed.

## Quick install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sslivins&repository=hass_omnisense&category=Integration)

Click the button above on a device that has access to your Home
Assistant. It takes you straight to the **Add custom repository**
dialog in HACS with everything pre-filled.

After it installs:

1. **Restart Home Assistant.**
2. Go to **Settings → Devices & Services → Add Integration**, search
   for **OmniSense**.
3. Sign in with the same email + password you use on the OmniSense
   portal.

## Requirements

- Home Assistant **2024.2** or newer
- [HACS](https://hacs.xyz) installed
- A working OmniSense web account
- At least one OmniSense sensor already paired with your account

## Manual install (without HACS)

If you don't run HACS:

1. Copy the entire `custom_components/omnisense/` directory into your
   Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration from **Settings → Devices & Services**.

## How it works

The integration is a thin wrapper around
[`pyomnisense`](https://pypi.org/project/pyomnisense/), which talks to
the OmniSense web portal on your behalf. It walks every site on the
account and discovers every sensor, then polls them periodically and
exposes the readings as Home Assistant entities.

## Credentials

Your OmniSense password is stored only in the Home Assistant config
entry (encrypted at rest like every other HA credential) and is never
written to logs by this integration.

## Contributing

Bug reports and PRs welcome on the
[issue tracker](https://github.com/sslivins/hass_omnisense/issues).

For issues with the underlying API, see
[`pyomnisense`](https://github.com/sslivins/pyomnisense).

## License

[MIT](LICENSE) © [sslivins](https://github.com/sslivins)
