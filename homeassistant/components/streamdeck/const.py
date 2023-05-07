"""Constants for the Stream Deck integration."""

from homeassistant.components import input_boolean
from homeassistant.const import Platform

DOMAIN = "streamdeck"
MANUFACTURER = "Elgato"

# Data const
DATA_API = "api"
DATA_CURRENT_ENTITY = "current"
DATA_SELECT_ENTITIES = "select"

# Config entry const
CONF_BUTTONS = "buttons"
CONF_ENABLED_PLATFORMS = "enabled_platforms"
CONF_VERSION = "version"

TOGGLEABLE_PLATFORMS = [
    Platform.COVER,
    Platform.FAN,
    Platform.HUMIDIFIER,
    input_boolean.DOMAIN,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SIREN,
    Platform.SWITCH,
    Platform.VACUUM,
]
UP_DOWN_PLATFORMS = [Platform.LIGHT]
UP_DOWN_STEPS = 15

AVAILABLE_PLATFORMS: list[str] = TOGGLEABLE_PLATFORMS + [
    Platform.BINARY_SENSOR,
]
DEFAULT_PLATFORMS: list[str] = [Platform.SWITCH, input_boolean.DOMAIN]

SELECT_OPTION_DELETE = ">>DELETE<<"
SELECT_OPTION_UP = ">>UP<<"
SELECT_OPTION_DOWN = ">>DOWN<<"
SELECT_DEFAULT_OPTIONS = [
    "",
    SELECT_OPTION_DELETE,
    SELECT_OPTION_UP,
    SELECT_OPTION_DOWN,
]

EVENT_SHORT_PRESS = "singleTap"
EVENT_LONG_PRESS = "longPress"

MDI_PREFIX = "mdi:"
MDI_DEFAULT = "mdi:help"

ATTR_POSITION = "position"
ATTR_UUID = "uuid"
