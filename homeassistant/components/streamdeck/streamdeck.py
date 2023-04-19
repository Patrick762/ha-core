"""Stream Deck API."""

import json
import logging
import re

from mdiicons import MDI
import requests
from websockets.client import connect
from websockets.exceptions import WebSocketException

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, STATE_OFF, STATE_ON, Platform
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PLATFORMS, DOMAIN, MANUFACTURER

PLUGIN_PORT = 6153
PLUGIN_INFO = "/sd/info"
PLUGIN_ICON = "/sd/icon"

_LOGGER = logging.getLogger(__name__)

#
#   Types
#


class SDApplication:
    """Stream Deck Application Type."""

    font: str
    language: str
    platform: str
    platform_version: str
    version: str

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Application object."""
        self.font = obj["font"]
        self.language = obj["language"]
        self.platform = obj["platform"]
        self.platform_version = obj["platformVersion"]
        self.version = obj["version"]


class SDSize:
    """Stream Deck Size Type."""

    columns: int
    rows: int

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Size object."""
        self.columns = obj["columns"]
        self.rows = obj["rows"]


class SDDevice:
    """Stream Deck Device Type."""

    id: str
    name: str
    type: int
    size: SDSize

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Device object."""
        self.id = obj["id"]
        self.name = obj["name"]
        self.type = obj["type"]
        self.size = SDSize(obj["size"])


class SDButtonPosition:
    """Stream Deck Button Position Type."""

    x_pos: int
    y_pos: int

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Button Position object."""
        self.x_pos = obj["x"]
        self.y_pos = obj["y"]


class SDButton:
    """Stream Deck Button Type."""

    uuid: str
    device: str
    position: SDButtonPosition
    svg: str

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Button object."""
        self.uuid = obj["uuid"]
        self.device = obj["device"]
        self.svg = obj["svg"]
        self.position = SDButtonPosition(obj["position"])


class SDInfo(dict):
    """Stream Deck Info Type."""

    application: SDApplication
    devices: list[SDDevice] = []
    buttons: dict[str, SDButton] = {}

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Info object."""
        dict.__init__(self, obj)
        self.application = SDApplication(obj["application"])
        for device in obj["devices"]:
            self.devices.append(SDDevice(device))
        for _id in obj["buttons"]:
            self.buttons.update({_id: SDButton(obj["buttons"][_id])})


class SDWebsocketMessage:
    """Stream Deck Websocket Message Type."""

    event: str
    args: SDInfo | str | dict

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Websocket Message object."""
        self.event = obj["event"]
        if obj["args"] == {}:
            self.args = {}
            return
        if isinstance(obj["args"], str):
            self.args = obj["args"]
            return
        self.args = SDInfo(obj["args"])


#
#   Binary sensors
#


class StreamDeckButton(BinarySensorEntity):
    """Stream Deck Button sensor."""

    def __init__(
        self,
        entry_title: str,
        device: DeviceInfo | None,
        uuid: str,
        position: str,
        button_device: str,
    ) -> None:
        """Initialize the binary sensor."""
        self._attr_name = f"{entry_title} {uuid}"
        self._attr_unique_id = StreamDeck.get_unique_id(f"{entry_title} {uuid}")
        self._attr_device_info = device
        self._attr_is_on = False
        self._attr_extra_state_attributes = {
            "Position": position,
            "Device ID": button_device,
        }


#
#   Select sensors
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
        initial: str = "",
    ) -> None:
        """Init the select sensor."""
        self._attr_name = f"{entry_title} {uuid} ({position})"
        self._attr_unique_id = StreamDeck.get_unique_id(f"{entry_title} {uuid}")
        self._attr_device_info = device
        self._attr_current_option = initial
        self._sd_entry_id = entry_id
        self._btn_uuid = uuid
        self._enabled_platforms = enabled_platforms

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        # NOT UPDATING EVERY TIME A NEW ENTITY IS ADDED!!!
        entities: list[str] = self.hass.states.async_entity_ids(
            domain_filter=self._enabled_platforms
        )
        return entities

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Changed select to %s", option)
        api: StreamDeck = self.hass.data[DOMAIN][self._sd_entry_id]
        await api.set_button_entity(self._btn_uuid, option)
        self._attr_current_option = option


#
#   Main class
#


class StreamDeck:
    """Stream Deck API Class."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry | None = None,
        host: str | None = None,
    ) -> None:
        """Init Stream Deck API object."""
        self.hass = hass
        self.entry = entry
        if host is not None:
            self.host = host
        elif entry is not None:
            self.host = entry.data.get("host", "")
        else:
            self.host = ""
        self._async_add_binary_sensors: AddEntitiesCallback | None = None
        self._async_add_select_sensors: AddEntitiesCallback | None = None
        self._running = False
        self._stop_listener: CALLBACK_TYPE | None = None
        self._button_dict: dict[str, str] = {}

    #
    #   Properties
    #

    @property
    def info_url(self) -> str:
        """URL to info endpoint."""
        return f"http://{self.host}:{PLUGIN_PORT}{PLUGIN_INFO}"

    @property
    def icon_url(self) -> str:
        """URL to icon endpoint."""
        return f"http://{self.host}:{PLUGIN_PORT}{PLUGIN_ICON}/"

    @property
    def websocket_url(self) -> str:
        """URL to websocket."""
        return f"ws://{self.host}:{PLUGIN_PORT}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Device info."""
        if self.entry is None:
            return None

        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.entry.data.get("host", ""))
            },
            name=self.entry.data.get("name", None),
            manufacturer=MANUFACTURER,
            model=self.entry.data.get("model", None),
            sw_version=self.entry.data.get("version", None),
        )

    #
    #   API Methods
    #

    @staticmethod
    def get_request(url: str) -> bool | requests.Response:
        """Handle GET requests."""
        try:
            res = requests.get(url, timeout=5)
        except requests.RequestException:
            _LOGGER.debug(
                "Error retrieving data from Stream Deck Plugin (exception). Is it offline?"
            )
            return False
        if res.status_code != 200:
            _LOGGER.debug(
                "Error retrieving data from Stream Deck Plugin (response code). Is it offline?"
            )
            return False
        return res

    @staticmethod
    def post_request(url: str, data: str, headers) -> bool | requests.Response:
        """Handle POST requests."""
        try:
            res = requests.post(url, data, headers=headers, timeout=5)
        except requests.RequestException:
            _LOGGER.error("Error sending data to Stream Deck Plugin (exception)")
            return False
        if res.status_code != 200:
            _LOGGER.info(
                "Error sending data to Stream Deck Plugin (%s). Is the button currently visible?",
                res.reason,
            )
            return False
        return res

    async def get_info(self) -> bool | SDInfo:
        """Get info about Stream Deck."""
        res = await self.hass.async_add_executor_job(self.get_request, self.info_url)
        if isinstance(res, bool) or res.status_code != 200:
            return False
        try:
            rjson = res.json()
        except requests.JSONDecodeError:
            _LOGGER.error("Error decoding response from %s", self.info_url)
            return False
        try:
            info = SDInfo(rjson)
        except KeyError:
            _LOGGER.error("Error parsing response from %s to SDInfo", self.info_url)
            return False
        return info

    async def get_icon(self, btn: str) -> bool | str:
        """Get svg icon from Stream Deck button."""
        url = f"{self.icon_url}{btn}"
        res = await self.hass.async_add_executor_job(self.get_request, url)
        if isinstance(res, bool) or res.status_code != 200:
            return False
        if res.headers.get("Content-Type", "") != "image/svg+xml":
            _LOGGER.error("Invalid content type received from %s", url)
            return False
        return res.text

    async def update_icon(self, btn: str, svg: str) -> bool:
        """Update svg icon of Stream Deck button."""
        url = f"{self.icon_url}{btn}"
        res = await self.hass.async_add_executor_job(
            self.post_request,
            url,
            svg.encode("utf-8"),
            {"Content-Type": "image/svg+xml"},
        )
        return isinstance(res, requests.Response) and res.status_code == 200

    #
    #   Websocket Methods
    #

    def on_button_change(self, uuid: str | dict, state: str):
        """Handle button down event."""
        if self.entry is None:
            _LOGGER.debug("Method on_button_change: entry is None")
            return
        if not isinstance(uuid, str):
            _LOGGER.debug("Method on_button_change: uuid is not str")
            return
        # Update binary sensor of button
        button_entity = StreamDeck.get_unique_id(
            f"{self.entry.title} {uuid}", sensor_type=Platform.BINARY_SENSOR
        )
        button_entity_state = self.hass.states.get(button_entity)
        if button_entity_state is None:
            _LOGGER.info("Method on_button_change: button_entity_state is None")
            return
        self.hass.states.async_set(button_entity, state, button_entity_state.attributes)
        # Update selected entity
        if state == "off":
            _LOGGER.debug("Method on_button_change: state is off")
            return
        if self._button_dict[uuid] is None:
            _LOGGER.debug("Method on_button_change: dict entry is None")
            return
        if not self._button_dict[uuid].startswith((Platform.SWITCH, "input_boolean")):
            _LOGGER.debug("Method on_button_change: selected entity can't be displayed")
            return
        entity_id = self._button_dict[uuid]
        current_state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.debug("Method on_button_change: state is None")
            return
        if current_state is None:
            _LOGGER.debug("Method on_button_change: current_state is None")
            return
        new_state = current_state.state
        if current_state.state == STATE_ON:
            new_state = STATE_OFF
        elif current_state.state == STATE_OFF:
            new_state = STATE_ON
        self.hass.states.async_set(entity_id, new_state, current_state.attributes)

    def on_status_update(self, info: SDInfo | str | dict):
        """Handle Stream Deck status update event."""
        if self.entry is None:
            _LOGGER.debug("Method on_status_update: entry is None")
            return
        if not isinstance(info, SDInfo):
            _LOGGER.debug("Method on_status_update: info is not SDInfo")
            return
        _LOGGER.info("Status OK. Updating entities and device")

    def on_message(self, msg: str):
        """Handle websocket messages."""
        if not isinstance(msg, str):
            return

        _LOGGER.debug(msg)

        try:
            datajson = json.loads(msg)
        except json.JSONDecodeError:
            _LOGGER.warning("Websocket message couldn't get parsed")
            return
        try:
            data = SDWebsocketMessage(datajson)
        except KeyError:
            _LOGGER.warning(
                "Websocket message couldn't get parsed to SDWebsocketMessage"
            )
            return

        self.hass.bus.async_fire(
            f"streamdeck-{data.event}", {"host": self.host, "data": data.args}
        )

        match data.event:
            case "keyDown":
                self.on_button_change(data.args, "on")
            case "keyUp":
                self.on_button_change(data.args, "off")
            case "status":
                self.on_status_update(data.args)
            case _:
                _LOGGER.debug(
                    "Unknown event from Stream Deck Plugin received (%s)", data.event
                )

    async def websocket_loop(self):
        """Start the websocket client."""
        self._running = True
        while self._running:
            info = await self.get_info()
            if isinstance(info, SDInfo):
                _LOGGER.info("Streamdeck online")
                try:
                    async with connect(self.websocket_url) as websocket:
                        try:
                            while self._running:
                                data = await websocket.recv()
                                self.on_message(data)
                            await websocket.close()
                            _LOGGER.info("Websocket closed")
                        except WebSocketException:
                            _LOGGER.warning("Websocket client crashed. Restarting it")
                except WebSocketException:
                    _LOGGER.warning("Websocket client not connecting. Restarting it")

    #
    #   Helper Methods
    #

    async def on_entity_state_change(self, event: Event):
        """Handle entity state changes."""
        entity_id = event.data.get("entity_id")
        if entity_id is None:
            return
        if entity_id not in self._button_dict.values():
            return
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        icon = await self.build_button_icon(
            state.name, state.attributes.get("icon", "help"), state.state
        )
        for uuid, entity in self._button_dict.items():
            if entity == entity_id:
                await self.update_icon(uuid, icon)

    def start(self):
        """Start the streamdeck client."""
        _LOGGER.info("Starting Stream Deck Websocket")
        self.hass.async_create_background_task(
            self.websocket_loop(), f"{self.entry.entry_id}_websocket"
        )
        _LOGGER.info("Stream Deck Websocket started")
        _LOGGER.info("Starting Stream Deck Entity change listener")
        self._stop_listener = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self.on_entity_state_change
        )
        _LOGGER.info("Stream Deck Entity change listener started")

    def stop(self):
        """Stop the streamdeck client."""
        self._running = False
        self._stop_listener()

    #
    #   Tools
    #

    async def build_button_icon(
        self,
        name: str,
        mdi_string: str,
        status: str,
        bg_color: str = "000",
        icon_color: str = "fff",
        color: str = "fff",
    ) -> str:
        """Build the svg icon for a button."""
        # Limit name and status len
        if status == STATE_ON:
            icon_color = "#0e0"
        elif status == STATE_OFF:
            icon_color = "#e00"

        if mdi_string.startswith("mdi:"):
            mdi_string = mdi_string.split(":", 1)[1]
        mdi = MDI.get_icon(mdi_string, icon_color)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">
            <rect width="72" height="72" fill="#{bg_color}" />
            <text text-anchor="middle" x="35" y="15" fill="#{color}" font-size="12">{status}</text>
            <text text-anchor="middle" x="35" y="65" fill="#{color}" font-size="12">{name}</text>
            <g transform="translate(16, 18) scale(0.5)">{mdi}</g>
            </svg>"""
        return svg

    @staticmethod
    def get_model(info: SDInfo) -> str:
        """Get Stream Deck model."""
        if len(info.devices) == 0:
            return "None"
        size = info.devices[0].size
        if size.columns == 3 and size.rows == 2:
            return "Stream Deck Mini"
        if size.columns == 5 and size.rows == 3:
            return "Stream Deck MK.2"
        if size.columns == 4 and size.rows == 2:
            return "Stream Deck +"
        if size.columns == 8 and size.rows == 4:
            return "Stream Deck XL"
        return "Unknown"

    @staticmethod
    def get_unique_id(name: str, sensor_type: str | None = None):
        """Generate an unique id."""
        res = re.sub("[^A-Za-z0-9]+", "_", name).lower()
        if sensor_type is not None:
            return f"{sensor_type}.{res}"
        return res

    async def add_entities(
        self,
        binary: AddEntitiesCallback | None = None,
        select: AddEntitiesCallback | None = None,
    ):
        """Add entities."""
        new_binary_sensors = False
        new_select_sensors = False

        if binary is not None:
            self._async_add_binary_sensors = binary
            new_binary_sensors = True

        if select is not None:
            self._async_add_select_sensors = select
            new_select_sensors = True

        if self.entry is None:
            _LOGGER.debug("Method add_entities: entry is None")
            return

        info = await self.get_info()
        if isinstance(info, bool):
            _LOGGER.debug("Method add_entities: Info not provided")
            return

        # Get positions and device ids of buttons
        positions: dict[str, str] = {}
        button_devices: dict[str, str] = {}
        for _, button_info in info.buttons.items():
            pos = button_info.position
            positions[button_info.uuid] = f"{pos.x_pos}|{pos.y_pos}"
            button_devices[button_info.uuid] = button_info.device

        # Read config_entry
        self._button_dict = self.entry.data.get("buttons", {})
        if not isinstance(self._button_dict, dict):
            _LOGGER.warning(
                "Invalid config_entry. Try removing and adding the device again"
            )
            return

        # List already configured buttons
        _LOGGER.info(
            "Found %s buttons already configured", len(self._button_dict.keys())
        )
        for uuid, entity in self._button_dict.items():
            _LOGGER.info("Button: %s, Entity: %s", uuid, entity)

        # Add sensors
        if self._async_add_binary_sensors is not None and new_binary_sensors:
            for _, button in info.buttons.items():
                if button.uuid not in self._button_dict.keys():
                    _LOGGER.info("Adding new button %s", button.uuid)
                    self._button_dict[button.uuid] = ""

            binary_sensors: list[StreamDeckButton] = []
            for uuid in self._button_dict:
                position = positions.get(uuid, "unknown")
                button_device = button_devices.get(uuid, "unknown")
                binary_sensor = StreamDeckButton(
                    self.entry.title, self.device_info, uuid, position, button_device
                )
                binary_sensors.append(binary_sensor)
            self._async_add_binary_sensors(binary_sensors, True)
            _LOGGER.debug(
                "Loaded streamdeck entities (%d binary sensors)", len(binary_sensors)
            )

        if self._async_add_select_sensors is not None and new_select_sensors:
            for _, button in info.buttons.items():
                if button.uuid not in self._button_dict.keys():
                    _LOGGER.info("Adding new button %s", button.uuid)
                    self._button_dict[button.uuid] = ""

            select_sensors: list[StreamDeckSelect] = []
            for uuid, entity_id in self._button_dict.items():
                position = positions.get(uuid, "unknown")
                select_sensor = StreamDeckSelect(
                    self.entry.title,
                    self.device_info,
                    uuid,
                    self.entry.entry_id,
                    self.entry.data.get("enabled_platforms", DEFAULT_PLATFORMS),
                    position,
                    entity_id,
                )
                select_sensors.append(select_sensor)
            self._async_add_select_sensors(select_sensors, True)
            _LOGGER.debug(
                "Loaded streamdeck entities (%d select sensors)", len(select_sensors)
            )

        # Update config_entry
        updates = {"buttons": self._button_dict}
        self.hass.config_entries.async_update_entry(
            self.entry, data=self.entry.data | updates
        )

    async def set_button_entity(self, uuid: str, entity_id: str):
        """Add an entity to a button."""
        self._button_dict[uuid] = entity_id

        if self.entry is None:
            _LOGGER.debug("Method set_button_entity: entry is None")
            return

        # NOT SAVING!!!
        # Update config_entry
        updates = {"buttons": self._button_dict}
        self.hass.config_entries.async_update_entry(
            self.entry, data=self.entry.data | updates
        )
        _LOGGER.info(
            "Method set_button_entity: config_entry %s saved", self.entry.entry_id
        )

        # List configured buttons
        _LOGGER.info("Found %s configured buttons ", len(self._button_dict.keys()))
        for button, entity in self._button_dict.items():
            _LOGGER.info("Button: %s, Entity: %s", button, entity)

        state = self.hass.states.get(entity_id)
        if state is None:
            return
        icon = await self.build_button_icon(
            state.name, state.attributes.get("icon", "help"), state.state
        )
        await self.update_icon(uuid, icon)
