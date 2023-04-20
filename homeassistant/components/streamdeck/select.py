"""Select Sensors for Stream Deck Integration."""

import re

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PLATFORMS, DOMAIN, MANUFACTURER
from .streamdeckapi.api import StreamDeckApi


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
        sensors_to_add.append(
            StreamDeckSelect(
                entry.title,
                device_info(entry),
                button_info.uuid,
                entry.entry_id,
                entry.data.get("enabled_platforms", DEFAULT_PLATFORMS),
                f"{button_info.position.x_pos}|{button_info.position.y_pos}",
            )
        )
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
        initial: str = "",
    ) -> None:
        """Init the select sensor."""
        self._attr_name = f"{entry_title} {uuid} ({position})"
        self._attr_unique_id = get_unique_id(f"{entry_title} {uuid}")
        self._attr_device_info = device
        self._attr_current_option = initial
        self._sd_entry_id = entry_id
        self._btn_uuid = uuid
        self._enabled_platforms = enabled_platforms

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options."""
        entities: list[str] = self.hass.states.async_entity_ids(
            domain_filter=self._enabled_platforms
        )
        return entities

    # async def async_select_option(self, option: str) -> None:
    #    """Change the selected option."""
    #    api: StreamDeck = self.hass.data[DOMAIN][self._sd_entry_id]
    #    await api.set_button_entity(self._btn_uuid, option)
    #    self._attr_current_option = option


#
#   Tools
#


def get_unique_id(name: str, sensor_type: str | None = None):
    """Generate an unique id."""
    res = re.sub("[^A-Za-z0-9]+", "_", name).lower()
    if sensor_type is not None:
        return f"{sensor_type}.{res}"
    return res


def device_info(entry) -> DeviceInfo:
    """Device info."""
    return DeviceInfo(
        identifiers={
            # Serial numbers are unique identifiers within a specific domain
            (DOMAIN, entry.data.get("mac", ""))
        },
        name=entry.data.get("name", None),
        manufacturer=MANUFACTURER,
        model=entry.data.get("model", None),
        sw_version=entry.data.get("version", None),
    )
