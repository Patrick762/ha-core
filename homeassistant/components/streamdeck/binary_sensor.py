"""Binary Sensors for Stream Deck Integration."""

from streamdeckapi import StreamDeckApi

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import device_info, get_unique_id
from .const import ATTR_POSITION, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Stream Deck binary sensors."""
    api: StreamDeckApi = hass.data[DOMAIN][entry.entry_id]
    info = await api.get_info()
    if isinstance(info, bool):
        return

    sensors_to_add = []
    for _, button_info in info.buttons.items():
        sensors_to_add.append(
            StreamDeckButton(
                entry.title,
                device_info(entry),
                button_info.uuid,
                f"{button_info.position.x_pos}|{button_info.position.y_pos}",
                button_info.device,
            )
        )
    async_add_entities(sensors_to_add)


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
        self._attr_unique_id = get_unique_id(f"{entry_title} {uuid}")
        self._attr_device_info = device
        self._attr_is_on = False
        self._attr_extra_state_attributes = {
            ATTR_POSITION: position,
            ATTR_DEVICE_ID: button_device,
        }
