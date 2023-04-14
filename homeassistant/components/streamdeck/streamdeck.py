"""Stream Deck API."""

import json
import logging
import re

import requests
from websockets.client import connect
from websockets.exceptions import WebSocketException

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER

PLUGIN_PORT = 6153
PLUGIN_INFO = "/sd/info"
PLUGIN_ICON = "/sd/icon/"

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


class SDButton:
    """Stream Deck Button Type."""

    uuid: str
    svg: str

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Button object."""
        self.uuid = obj["uuid"]
        self.svg = obj["svg"]


class SDInfo(dict):
    """Stream Deck Info Type."""

    uuid: str
    application: SDApplication
    devices: list[SDDevice] = []
    buttons: dict[str, SDButton] = {}

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Info object."""
        dict.__init__(self, obj)
        if obj["uuid"]:
            self.uuid = obj["uuid"]
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
        self, entry_title: str, device: DeviceInfo | None, button: SDButton
    ) -> None:
        """Initialize the binary sensor."""
        self._attr_name = f"{entry_title} {button.uuid}"
        self._attr_unique_id = StreamDeck.get_unique_id(f"{entry_title} {button.uuid}")
        self._attr_device_info = device
        self._attr_is_on = False


#
#   Select sensors
#


class StreamDeckSelect(SelectEntity):
    """Stream Deck Select sensor."""

    def __init__(
        self, entry_title: str, device: DeviceInfo | None, button: SDButton
    ) -> None:
        """Init the select sensor."""
        self._attr_name = f"{entry_title} {button.uuid}"
        self._attr_unique_id = StreamDeck.get_unique_id(f"{entry_title} {button.uuid}")
        self._attr_device_info = device
        self._attr_current_option = ""

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        states = self.hass.states.async_all()
        entities: list[str] = []
        for state in states:
            if state.domain == Platform.BINARY_SENSOR:
                entities.append(state.entity_id)
        return entities

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Changed select to %s", option)


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
            _LOGGER.error("Error sending data to Stream Deck Plugin (response code)")
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

    def on_button_change(self, uuid: str | dict, state: str):
        """Handle button down event."""
        if self.entry is None:
            return
        if not isinstance(uuid, str):
            return
        self.hass.states.async_set(
            "binary_sensor." + self.get_unique_id(f"{self.entry.title} {uuid}"), state
        )

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

    def stop(self):
        """Stop the websocket client."""
        self._running = False

    #
    #   Tools
    #

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
    def get_unique_id(name: str):
        """Generate an unique id."""
        res = re.sub("[^A-Za-z0-9]+", "_", name).lower()
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
            return

        info = await self.get_info()
        if isinstance(info, bool):
            return

        if self._async_add_binary_sensors is not None and new_binary_sensors:
            binary_sensors: list[StreamDeckButton] = []
            for _, button in info.buttons.items():
                binary_sensor = StreamDeckButton(
                    self.entry.title, self.device_info, button
                )
                binary_sensors.append(binary_sensor)
            self._async_add_binary_sensors(binary_sensors, True)
            _LOGGER.debug(
                "Loaded streamdeck entities (%d binary sensors)", len(binary_sensors)
            )

        if self._async_add_select_sensors is not None and new_select_sensors:
            select_sensors: list[StreamDeckSelect] = []
            for _, button in info.buttons.items():
                select_sensor = StreamDeckSelect(
                    self.entry.title, self.device_info, button
                )
                select_sensors.append(select_sensor)
            self._async_add_select_sensors(select_sensors, True)
            _LOGGER.debug(
                "Loaded streamdeck entities (%d select sensors)", len(select_sensors)
            )
