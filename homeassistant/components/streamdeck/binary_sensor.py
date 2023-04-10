"""Binary Sensors for Stream Deck Integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .streamdeck import StreamDeck


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Stream Deck binary sensors."""
    api: StreamDeck = hass.data[DOMAIN][entry.entry_id]
    await api.add_entities(binary=async_add_entities)
