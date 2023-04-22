"""Constants for the Stream Deck integration."""

from homeassistant.components import input_boolean
from homeassistant.const import Platform

DOMAIN = "streamdeck"
MANUFACTURER = "Elgato"

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
AVAILABLE_PLATFORMS: list[str] = TOGGLEABLE_PLATFORMS + [
    Platform.BINARY_SENSOR,
]
DEFAULT_PLATFORMS: list[str] = [Platform.SWITCH, input_boolean.DOMAIN]

MDI_PREFIX = "mdi:"
MDI_DEFAULT = "mdi:help"

CONF_ENABLED_PLATFORMS = "enabled_platforms"
CONF_BUTTONS = "buttons"

ATTR_POSITION = "position"
ATTR_UUID = "uuid"
