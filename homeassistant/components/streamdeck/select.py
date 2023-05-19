"""Select Sensors for Stream Deck Integration."""


from streamdeckapi import StreamDeckApi

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import StreamDeckButton, StreamDeckSelect, device_info
from .const import (
    CONF_BUTTONS,
    CONF_ENABLED_PLATFORMS,
    DATA_API,
    DATA_SELECT_ENTITIES,
    DEFAULT_PLATFORMS,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Stream Deck select sensors."""
    api: StreamDeckApi = hass.data[DOMAIN][entry.entry_id][DATA_API]
    info = await api.get_info()
    if isinstance(info, bool):
        return

    sensors_to_add = []
    for _, button_info in info.buttons.items():
        initial = ""
        buttons = entry.data.get(CONF_BUTTONS)
        if isinstance(buttons, dict):
            button_config = buttons.get(button_info.uuid)
            button = StreamDeckButton(button_info.uuid, hass, entry.entry_id)
            if isinstance(button_config, dict):
                entity = button.get_entity()
                if isinstance(entity, str):
                    initial = entity
                    # Initialize button icon on load
                    button.update_icon()

        sensors_to_add.append(
            StreamDeckSelect(
                entry.title,
                device_info(entry),
                button_info.uuid,
                entry.entry_id,
                entry.data.get(CONF_ENABLED_PLATFORMS, DEFAULT_PLATFORMS),
                f"{button_info.position.x_pos}|{button_info.position.y_pos}",
                button_info.device,
                initial,
            )
        )

    hass.data[DOMAIN][entry.entry_id][DATA_SELECT_ENTITIES] = sensors_to_add

    async_add_entities(sensors_to_add)
