"""Stream Deck API."""

import logging

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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


class SDInfo:
    """Stream Deck Info Type."""

    uuid: str
    application: SDApplication
    devices: list[SDDevice] = []
    buttons: dict[str, SDButton] = {}

    def __init__(self, obj: dict) -> None:
        """Init Stream Deck Info object."""
        if obj["uuid"]:
            self.uuid = obj["uuid"]
        self.application = SDApplication(obj["application"])
        for device in obj["devices"]:
            self.devices.append(SDDevice(device))
        for _id in obj["buttons"]:
            self.buttons.update({_id: SDButton(obj["buttons"][_id])})


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
