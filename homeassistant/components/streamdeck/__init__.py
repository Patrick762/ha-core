"""The Stream Deck integration."""
from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .streamdeckapi.api import StreamDeckApi
from .streamdeckapi.types import SDWebsocketMessage

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stream Deck from a config entry."""

    host = entry.data.get("host", "")
    api: StreamDeckApi | None = None

    def set_binary_sensor_state(uuid: str, state: str):
        button_entity = get_unique_id(
            f"{entry.title} {uuid}", sensor_type=Platform.BINARY_SENSOR
        )
        button_entity_state = hass.states.get(button_entity)
        if button_entity_state is None:
            _LOGGER.info("Method on_button_press: button_entity_state is None")
            return
        hass.states.async_set(button_entity, state, button_entity_state.attributes)

    def on_button_press(uuid: str):
        set_binary_sensor_state(uuid, "on")
        # Update selected entity
        if api is None:
            _LOGGER.warning("Method on_button_press: api is None")
            return
        update_button_icon(hass, entry.entry_id, api, uuid)

    def on_button_release(uuid: str):
        set_binary_sensor_state(uuid, "off")

    def on_ws_message(msg: SDWebsocketMessage):
        hass.bus.async_fire(f"streamdeck_{msg.event}", {"host": host, "data": msg.args})

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = StreamDeckApi(
        host,
        on_button_press=on_button_press,
        on_button_release=on_button_release,
        on_ws_message=on_ws_message,
    )

    api = hass.data[DOMAIN][entry.entry_id]

    if api is None:
        return False

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


#
#   Tools
#


def get_unique_id(name: str, sensor_type: str | None = None):
    """Generate an unique id."""
    res = re.sub("[^A-Za-z0-9]+", "_", name).lower()
    if sensor_type is not None:
        return f"{sensor_type}.{res}"
    return res


def device_info(entry) -> DeviceInfo:
    """Device info."""
    return DeviceInfo(
        identifiers={
            # Serial numbers are unique identifiers within a specific domain
            (DOMAIN, entry.data.get("mac", ""))
        },
        name=entry.data.get("name", None),
        manufacturer=MANUFACTURER,
        model=entry.data.get("model", None),
        sw_version=entry.data.get("version", None),
    )


def update_button_icon(
    hass: HomeAssistant, entry_id: str, api: StreamDeckApi, uuid: str
):
    """Update the icon shown on a button."""
    loaded_entry = hass.config_entries.async_get_entry(entry_id)
    if loaded_entry is None:
        return
    buttons = loaded_entry.data.get("buttons")
    if not isinstance(buttons, dict):
        _LOGGER.error(
            "Method update_button_icon: Config entry %s has no data for 'buttons'",
            entry_id,
        )
        return
    button_config = buttons.get(uuid)
    if not isinstance(button_config, dict):
        _LOGGER.info(
            "Method update_button_icon: Config entry %s has no data for buttons.%s",
            entry_id,
            uuid,
        )
        return
    entity = button_config.get("entity")
    if not isinstance(entity, str):
        _LOGGER.info(
            "Method update_button_icon: Config entry %s has no data for buttons.%s.entity",
            entry_id,
            uuid,
        )
        return
    _LOGGER.info("Method update_button_icon: Updating icon for %s", uuid)
