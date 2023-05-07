"""The Stream Deck integration."""
from __future__ import annotations

import asyncio
import logging
import re

from mdiicons import MDI
from streamdeckapi import SDWebsocketMessage, StreamDeckApi
import voluptuous as vol

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_SW_VERSION,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_BRIGHTNESS,
    CONF_ENTITY_ID,
    CONF_EVENT_DATA,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_NAME,
    EVENT_STATE_CHANGED,
    SERVICE_TOGGLE,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_POSITION,
    ATTR_UUID,
    CONF_BUTTONS,
    CONF_ENABLED_PLATFORMS,
    DEFAULT_PLATFORMS,
    DOMAIN,
    EVENT_LONG_PRESS,
    EVENT_SHORT_PRESS,
    MANUFACTURER,
    MDI_DEFAULT,
    MDI_PREFIX,
    SELECT_DEFAULT_OPTIONS,
    SELECT_OPTION_DELETE,
    SELECT_OPTION_DOWN,
    SELECT_OPTION_UP,
    TOGGLEABLE_PLATFORMS,
    UP_DOWN_PLATFORMS,
    UP_DOWN_STEPS,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SELECT]


def setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Stream Deck Integration."""

    async def sevice_sdinfo(call: ServiceCall) -> None:
        """Handle Service sdinfo."""
        entries: list[ConfigEntry] = hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            _LOGGER.info(entry.entry_id)
            api: StreamDeckApi = hass.data[DOMAIN][entry.entry_id]
            if not isinstance(api, StreamDeckApi):
                return
            info = await api.get_info()
            if info is not None:
                hass.bus.async_fire(
                    f"{DOMAIN}_status", {CONF_HOST: api.host, CONF_EVENT_DATA: info}
                )

    hass.services.register(DOMAIN, "sdinfo", sevice_sdinfo, schema=vol.Schema({}))

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stream Deck from a config entry."""

    host = entry.data.get(CONF_HOST, "")
    api: StreamDeckApi | None = None

    def on_button_press(uuid: str):
        if api is None:
            _LOGGER.warning("Method on_button_press: api is None")
            return
        # Update entity if possible (automatically triggers icon update)
        entity = get_button_entity(hass, entry.entry_id, uuid)
        if entity is None:
            _LOGGER.warning("Method on_button_press: entity is None")
            return

        # Handle UP and DOWN buttons
        base_entity = entity
        if entity in (SELECT_OPTION_UP, SELECT_OPTION_DOWN):
            base_entity = hass.data[DOMAIN][f"{entry.entry_id}_current"]
            if base_entity is None:
                return

        state = hass.states.get(base_entity)
        if state is None:
            _LOGGER.warning("Method on_button_press: state is None")
            return
        if state.domain in TOGGLEABLE_PLATFORMS:
            if entity == SELECT_OPTION_UP:
                option_up(hass, state)
            elif entity == SELECT_OPTION_DOWN:
                option_down(hass, state)
            else:
                asyncio.run_coroutine_threadsafe(
                    hass.services.async_call(
                        state.domain,
                        SERVICE_TOGGLE,
                        target={CONF_ENTITY_ID: base_entity},
                    ),
                    hass.loop,
                )
        # Save last pressed entity to use for UP and DOWN buttons
        hass.data[DOMAIN][f"{entry.entry_id}_current"] = base_entity
        # TODO: Update icons for UP and DOWN buttons

    def on_ws_message(msg: SDWebsocketMessage):
        hass.bus.async_fire(
            f"{DOMAIN}_{msg.event}", {CONF_HOST: host, CONF_EVENT_DATA: msg.args}
        )
        if msg.event == EVENT_SHORT_PRESS and isinstance(msg.args, str):
            on_button_press(msg.args)
        elif msg.event == EVENT_LONG_PRESS and isinstance(msg.args, str):
            entity = get_button_entity(hass, entry.entry_id, msg.args)
            if entity is None:
                return
            hass.data[DOMAIN][f"{entry.entry_id}_current"] = entity
            _LOGGER.info("Set current button to %s", entity)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = StreamDeckApi(
        host,
        on_ws_message=on_ws_message,
        on_ws_connect=lambda: init_all_buttons(hass, entry.entry_id),
    )
    hass.data[DOMAIN][f"{entry.entry_id}_current"] = None

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
#   Entities
#


class StreamDeckSelect(SelectEntity):
    """Stream Deck Select sensor."""

    def __init__(
        self,
        entry_title: str,
        device: DeviceInfo | None,
        uuid: str,
        entry_id: str,
        enabled_platforms: list[str],
        position: str,
        button_device: str,
        initial: str = "",
    ) -> None:
        """Init the select sensor."""
        self._attr_name = f"{entry_title} {uuid} ({position})"
        self._attr_unique_id = get_unique_id(f"{entry_title} {uuid}")
        self._attr_device_info = device
        self._sd_entry_id = entry_id
        self._btn_uuid = uuid
        self._enabled_platforms = enabled_platforms
        self._attr_options = SELECT_DEFAULT_OPTIONS
        self._attr_current_option = initial
        self._attr_extra_state_attributes = {
            ATTR_UUID: uuid,
            ATTR_POSITION: position,
            ATTR_DEVICE_ID: button_device,
        }

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        # Update config entry
        entry = self.hass.config_entries.async_get_entry(self._sd_entry_id)
        if entry is None:
            _LOGGER.error(
                "Method async_select_option: Config entry %s not available",
                self._sd_entry_id,
            )
            return
        if entry.data.get(CONF_BUTTONS) is None:
            _LOGGER.error(
                "Method async_select_option: Config entry %s has no data for 'buttons'",
                self._sd_entry_id,
            )
            return
        changed = self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                **{
                    CONF_BUTTONS: {
                        **entry.data[CONF_BUTTONS],
                        **{self._btn_uuid: {ATTR_ENTITY_ID: option}},
                    }
                },
            },
        )
        if changed is False:
            _LOGGER.error(
                "Method async_select_option: Config entry %s has not been changed",
                self._sd_entry_id,
            )
        update_button_icon(self.hass, self._sd_entry_id, self._btn_uuid)

    async def async_set_options(self, options: list[str]) -> None:
        """Set options."""
        self._attr_options = options

        if self.current_option not in self.options:
            _LOGGER.warning(
                "Current option: %s no longer valid (possible options: %s)",
                self.current_option,
                ", ".join(self.options),
            )
            # self._attr_current_option = options[0]

        self.async_write_ha_state()


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
            (DOMAIN, entry.data.get(CONF_MAC, ""))
        },
        name=entry.data.get(CONF_NAME, None),
        manufacturer=MANUFACTURER,
        model=entry.data.get(CONF_MODEL, None),
        sw_version=entry.data.get(ATTR_SW_VERSION, None),
    )


def get_button_entity(hass: HomeAssistant, entry_id: str, uuid: str) -> str | None:
    """Get the selected entity for a button."""
    loaded_entry = hass.config_entries.async_get_entry(entry_id)
    if loaded_entry is None:
        return None
    buttons = loaded_entry.data.get(CONF_BUTTONS)
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
    entity = button_config.get(ATTR_ENTITY_ID)
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
    # Display default icon if nothing is selected
    if entity is None or entity == "" or entity == SELECT_OPTION_DELETE:
        _LOGGER.info(
            "Method update_button_icon: No entity selected for %s. Using default icon",
            uuid,
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">
            <rect width="72" height="72" fill="#a00" />
            <text text-anchor="middle" x="35" y="20" fill="#fff" font-size="13">{uuid.split("-")[0]}</text>
            <text text-anchor="middle" x="35" y="40" fill="#fff" font-size="13">{uuid.split("-")[1]}</text>
            <text text-anchor="middle" x="35" y="60" fill="#fff" font-size="13">{uuid.split("-")[2]}</text>
            </svg>"""
        asyncio.run_coroutine_threadsafe(api.update_icon(uuid, svg), hass.loop)
        return

    # Handle UP and DOWN options
    if entity == SELECT_OPTION_UP:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">
            <rect width="72" height="72" fill="#000" />
            <g transform="translate(16, 12) scale(0.5)">{MDI.get_icon("plus-box", "#fff")}</g>
            </svg>"""
        asyncio.run_coroutine_threadsafe(api.update_icon(uuid, svg), hass.loop)
        return

    if entity == SELECT_OPTION_DOWN:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">
            <rect width="72" height="72" fill="#000" />
            <g transform="translate(16, 12) scale(0.5)">{MDI.get_icon("minus-box", "#fff")}</g>
            </svg>"""
        asyncio.run_coroutine_threadsafe(api.update_icon(uuid, svg), hass.loop)
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
        mdi_string = MDI_DEFAULT

    if mdi_string.startswith(MDI_PREFIX):
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
    entity_id = event.data.get(ATTR_ENTITY_ID)
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

    # Update select options
    selects: list[StreamDeckSelect] = hass.data[DOMAIN][f"{entry_id}-select"]
    for select in selects:
        asyncio.run_coroutine_threadsafe(
            select.async_set_options(
                SELECT_DEFAULT_OPTIONS
                + hass.states.async_entity_ids(
                    domain_filter=loaded_entry.data.get(
                        CONF_ENABLED_PLATFORMS, DEFAULT_PLATFORMS
                    )
                )
            ),
            hass.loop,
        )

    buttons = loaded_entry.data.get(CONF_BUTTONS)
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
        if button_config.get(ATTR_ENTITY_ID) == entity_id:
            update_button_icon(hass, entry_id, uuid)


def init_all_buttons(hass: HomeAssistant, entry_id: str):
    """Initialize all buttons."""
    # Get config_entry
    loaded_entry = hass.config_entries.async_get_entry(entry_id)
    if loaded_entry is None:
        return None
    buttons = loaded_entry.data.get(CONF_BUTTONS)
    if not isinstance(buttons, dict):
        _LOGGER.error(
            "Method on_entity_state_change: Config entry %s has no data for 'buttons'",
            entry_id,
        )
        return

    for uuid, _ in buttons.items():
        update_button_icon(hass, entry_id, uuid)


def option_up(hass: HomeAssistant, state: State):
    """Handle service for UP buttons."""
    if state.domain not in UP_DOWN_PLATFORMS:
        _LOGGER.debug("%s has no service for UP", state.entity_id)
        return
    if state.domain == Platform.LIGHT:
        brightness = state.attributes.get(CONF_BRIGHTNESS)
        if not isinstance(brightness, int):
            _LOGGER.debug("%s has no %s", state.entity_id, CONF_BRIGHTNESS)
            return
        asyncio.run_coroutine_threadsafe(
            hass.services.async_call(
                state.domain,
                SERVICE_TURN_ON,
                target={CONF_ENTITY_ID: state.entity_id},
                service_data={CONF_BRIGHTNESS: brightness + UP_DOWN_STEPS},
            ),
            hass.loop,
        )


def option_down(hass: HomeAssistant, state: State):
    """Handle service for DOWN buttons."""
    if state.domain not in UP_DOWN_PLATFORMS:
        _LOGGER.debug("%s has no service for DOWN", state.entity_id)
        return
    if state.domain == Platform.LIGHT:
        brightness = state.attributes.get(CONF_BRIGHTNESS)
        if not isinstance(brightness, int):
            _LOGGER.debug("%s has no %s", state.entity_id, CONF_BRIGHTNESS)
            return
        asyncio.run_coroutine_threadsafe(
            hass.services.async_call(
                state.domain,
                SERVICE_TURN_ON,
                target={CONF_ENTITY_ID: state.entity_id},
                service_data={CONF_BRIGHTNESS: brightness - UP_DOWN_STEPS},
            ),
            hass.loop,
        )
