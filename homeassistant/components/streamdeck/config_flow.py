"""Config flow for Stream Deck."""
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.components import ssdp
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .streamdeck import SDInfo, StreamDeck

_LOGGER = logging.getLogger(__name__)


class StreamDeckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow for Stream Deck Integration."""

    host: str | None = None

    async def async_step_ssdp(self, discovery_info: ssdp.SsdpServiceInfo) -> FlowResult:
        """Handle ssdp discovery flow."""
        location = discovery_info.ssdp_location
        hostname = urlparse(location).hostname
        if isinstance(hostname, str):
            self.host = hostname
        _LOGGER.debug("Found Streamdeck at host %s", self.host)
        return self.async_show_form(step_id="user")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user config flow."""
        if user_input:
            self.host = user_input.get("host", "")

        errors: dict[str, str] = {}
        if self.host is not None:
            deck = StreamDeck(self.hass, host=self.host)
            info = await deck.get_info()

            if info is False or not isinstance(info, SDInfo):
                errors["base"] = "cannot_connect"
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required("name", None, "Stream Deck"): str,
                            vol.Required("host", None, ""): str,
                        }
                    ),
                    errors=errors,
                )

            # Prevent double config
            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()

            if user_input is not None:
                data = {
                    "name": user_input["name"],
                    "host": self.host,
                    "model": StreamDeck.get_model(info),
                    "version": info.application.version,
                    "buttons": {},
                }
                return self.async_create_entry(title=user_input["name"], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", None, "Stream Deck"): str,
                    vol.Required("host", None, self.host): str,
                }
            ),
            errors=errors,
            last_step=True,
        )
