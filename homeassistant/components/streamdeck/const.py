"""Constants for the Stream Deck integration."""

from homeassistant.components import input_boolean
from homeassistant.const import Platform

DOMAIN = "streamdeck"
MANUFACTURER = "Elgato"
AVAILABLE_PLATFORMS: list[str] = [
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    input_boolean.DOMAIN,
]
DEFAULT_PLATFORMS: list[str] = [Platform.SWITCH, input_boolean.DOMAIN]
