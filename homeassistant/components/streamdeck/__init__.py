"""The Stream Deck integration."""
from __future__ import annotations

import asyncio
import logging
import re

from mdiicons import MDI
from streamdeckapi import SDWebsocketMessage, StreamDeckApi

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_STATE_CHANGED,
    SERVICE_TOGGLE,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import Context, Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER, TOGGLEABLE_PLATFORMS

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
            _LOGGER.info("Method set_binary_sensor_state: button_entity_state is None")
            return
        hass.states.async_set(button_entity, state, button_entity_state.attributes)

    def on_button_press(uuid: str):
        set_binary_sensor_state(uuid, "on")
        if api is None:
            _LOGGER.warning("Method on_button_press: api is None")
            return
        # Update entity if possible (automatically triggers icon update)
        entity = get_button_entity(hass, entry.entry_id, uuid)
        if entity is None:
            _LOGGER.warning("Method on_button_press: entity is None")
            return
        state = hass.states.get(entity)
        if state is None:
            _LOGGER.warning("Method on_button_press: state is None")
            return
        if state.domain in TOGGLEABLE_PLATFORMS:
            asyncio.run_coroutine_threadsafe(
                hass.services.async_call(
                    state.domain,
                    SERVICE_TOGGLE,
                    target={"entity_id": entity},
                    context=Context(user_id=entry.domain),
                ),
                hass.loop,
            )

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

    # Add listener for entity change events
    hass.bus.async_listen(
        EVENT_STATE_CHANGED,
        lambda event: on_entity_state_change(hass, entry.entry_id, event),
    )

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


def get_button_entity(hass: HomeAssistant, entry_id: str, uuid: str) -> str | None:
    """Get the selected entity for a button."""
    loaded_entry = hass.config_entries.async_get_entry(entry_id)
    if loaded_entry is None:
        return None
    buttons = loaded_entry.data.get("buttons")
    if not isinstance(buttons, dict):
        _LOGGER.error(
            "Method get_button_entity: Config entry %s has no data for 'buttons'",
            entry_id,
        )
        return None
    button_config = buttons.get(uuid)
    if not isinstance(button_config, dict):
        _LOGGER.info(
            "Method get_button_entity: Config entry %s has no data for buttons.%s",
            entry_id,
            uuid,
        )
        return None
    entity = button_config.get("entity")
    if not isinstance(entity, str):
        _LOGGER.info(
            "Method get_button_entity: Config entry %s has no data for buttons.%s.entity",
            entry_id,
            uuid,
        )
        return None
    return entity


def update_button_icon(hass: HomeAssistant, entry_id: str, uuid: str):
    """Update the icon shown on a button."""
    api: StreamDeckApi = hass.data[DOMAIN][entry_id]

    entity = get_button_entity(hass, entry_id, uuid)
    if entity is None:
        return

    # Get state of entity
    state = hass.states.get(entity)
    if state is None:
        _LOGGER.info("Method update_button_icon: State for entity %s is None", entity)
        return

    icon_color = "#000"
    if state.state == STATE_ON:
        icon_color = "#0e0"
    elif state.state == STATE_OFF:
        icon_color = "#e00"

    mdi_string: str | None = state.attributes.get("icon")
    if mdi_string is None:
        _LOGGER.info("Method update_button_icon: Icon of entity %s is None", entity)
        # Set default icon for entity
        mdi_string = "mdi:help"

    if mdi_string.startswith("mdi:"):
        mdi_string = mdi_string.split(":", 1)[1]

    mdi = MDI.get_icon(mdi_string, icon_color)

    # Change this part if necessary
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">
        <rect width="72" height="72" fill="#000" />
        <text text-anchor="middle" x="35" y="15" fill="#fff" font-size="12">{state.state}{state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")}</text>
        <text text-anchor="middle" x="35" y="65" fill="#fff" font-size="12">{state.name}</text>
        <g transform="translate(16, 12) scale(0.5)">{mdi}</g>
        </svg>"""

    asyncio.run_coroutine_threadsafe(api.update_icon(uuid, svg), hass.loop)


def on_entity_state_change(hass: HomeAssistant, entry_id: str, event: Event):
    """Handle entity state changes."""
    entity_id = event.data.get("entity_id")
    if entity_id is None:
        _LOGGER.error("Method on_entity_state_change: Event entity_id is None")
        return

    _LOGGER.debug(
        "Method on_entity_state_change: Received event for entity %s", entity_id
    )

    # Get config_entry
    loaded_entry = hass.config_entries.async_get_entry(entry_id)
    if loaded_entry is None:
        return None
    buttons = loaded_entry.data.get("buttons")
    if not isinstance(buttons, dict):
        _LOGGER.error(
            "Method on_entity_state_change: Config entry %s has no data for 'buttons'",
            entry_id,
        )
        return None

    state = hass.states.get(entity_id)
    if state is None:
        return
    for uuid, button_config in buttons.items():
        if not isinstance(button_config, dict):
            continue
        if button_config.get("entity") == entity_id:
            update_button_icon(hass, entry_id, uuid)
