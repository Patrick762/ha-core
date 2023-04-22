"""Select Sensors for Stream Deck Integration."""


import logging

from streamdeckapi import StreamDeckApi

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import device_info, get_unique_id, update_button_icon
from .const import (
    ATTR_POSITION,
    ATTR_UUID,
    CONF_BUTTONS,
    CONF_ENABLED_PLATFORMS,
    DEFAULT_PLATFORMS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


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

    async_add_entities(sensors_to_add)


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
        button_device: str,
        initial: str = "",
    ) -> None:
        """Init the select sensor."""
        self._attr_name = f"{entry_title} {uuid} ({position})"
        self._attr_unique_id = get_unique_id(f"{entry_title} {uuid}")
        self._attr_device_info = device
        self._sd_entry_id = entry_id
        self._btn_uuid = uuid
        self._enabled_platforms = enabled_platforms
        self._attr_current_option = initial
        self._attr_extra_state_attributes = {
            ATTR_UUID: uuid,
            ATTR_POSITION: position,
            ATTR_DEVICE_ID: button_device,
        }

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        # NOT ADDING NEW ENTITIES (only after selecting a new one)!!!
        entities: list[str] = [""] + self.hass.states.async_entity_ids(
            domain_filter=self._enabled_platforms
        )
        return entities

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        # Update config entry
        entry = self.hass.config_entries.async_get_entry(self._sd_entry_id)
        if entry is None:
            _LOGGER.error(
                "Method async_select_option: Config entry %s not available",
                self._sd_entry_id,
            )
            return
        if entry.data.get(CONF_BUTTONS) is None:
            _LOGGER.error(
                "Method async_select_option: Config entry %s has no data for 'buttons'",
                self._sd_entry_id,
            )
            return
        changed = self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                **{
                    CONF_BUTTONS: {
                        **entry.data[CONF_BUTTONS],
                        **{self._btn_uuid: {ATTR_ENTITY_ID: option}},
                    }
                },
            },
        )
        if changed is False:
            _LOGGER.error(
                "Method async_select_option: Config entry %s has not been changed",
                self._sd_entry_id,
            )
        update_button_icon(self.hass, self._sd_entry_id, self._btn_uuid)
