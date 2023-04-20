"""The Stream Deck integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .streamdeckapi.api import StreamDeckApi

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stream Deck from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = StreamDeckApi(entry.data.get("host", ""))

    api: StreamDeckApi = hass.data[DOMAIN][entry.entry_id]
    info = await api.get_info()
    if isinstance(info, bool):
        _LOGGER.error("Stream Deck not available at %s", api.host)
        raise ConfigEntryNotReady(f"Timeout while connecting to {api.host}")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    api.start_websocket_loop()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    api: StreamDeckApi = hass.data[DOMAIN][entry.entry_id]
    api.stop_websocket_loop()
    if unload_ok := await hass.config_entries.async_forward_entry_unload(
        entry, Platform.BINARY_SENSOR
    ) and await hass.config_entries.async_forward_entry_unload(entry, Platform.SELECT):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
