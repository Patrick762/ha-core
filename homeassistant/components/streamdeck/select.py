"""Select Sensors for Stream Deck Integration."""


from streamdeckapi import StreamDeckApi

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import StreamDeckSelect, device_info, update_button_icon
from .const import CONF_BUTTONS, CONF_ENABLED_PLATFORMS, DEFAULT_PLATFORMS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Stream Deck select sensors."""
    api: StreamDeckApi = hass.data[DOMAIN][entry.entry_id]
    info = await api.get_info()
    if isinstance(info, bool):
        return

    sensors_to_add = []
    for _, button_info in info.buttons.items():
        initial = ""
        buttons = entry.data.get(CONF_BUTTONS)
        if isinstance(buttons, dict):
            button_config = buttons.get(button_info.uuid)
            if isinstance(button_config, dict):
                entity = button_config.get(ATTR_ENTITY_ID)
                if isinstance(entity, str):
                    initial = entity

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

        # Initialize button icon on load
        if initial != "":
            update_button_icon(hass, entry.entry_id, button_info.uuid)

    hass.data[DOMAIN][f"{entry.entry_id}-select"] = sensors_to_add

    async_add_entities(sensors_to_add)
