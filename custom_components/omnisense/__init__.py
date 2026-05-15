"""The Omnisense integration."""
import logging
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

_LOGGER = logging.getLogger(__name__)

DOMAIN = "omnisense"
PLATFORMS = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Omnisense from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    # The coordinator (created by the sensor platform) will register
    # itself at hass.data[DOMAIN][entry.entry_id].

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None and getattr(coordinator, "omnisense", None) is not None:
            try:
                await coordinator.omnisense.close()
            except Exception as err:  # pragma: no cover - best-effort cleanup
                _LOGGER.warning("Error closing Omnisense session on unload: %s", err)

    return unload_ok
