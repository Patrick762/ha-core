"""Config flow for Stream Deck."""
from functools import partial
import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

from getmac import get_mac_address
import voluptuous as vol

from homeassistant.components import ssdp
from homeassistant.config_entries import ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, selector

from .const import AVAILABLE_PLATFORMS, DEFAULT_PLATFORMS, DOMAIN
from .streamdeckapi.api import StreamDeckApi
from .streamdeckapi.tools import get_model
from .streamdeckapi.types import SDInfo

_LOGGER = logging.getLogger(__name__)


class StreamDeckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow for Stream Deck Integration."""

    host: str | None = None
    mac: str | None = None

    async def async_step_ssdp(self, discovery_info: ssdp.SsdpServiceInfo) -> FlowResult:
        """Handle ssdp discovery flow."""
        location = discovery_info.ssdp_location
        hostname = urlparse(location).hostname
        if isinstance(hostname, str):
            self.host = hostname
            self.mac = await _async_get_mac_address(self.hass, self.host)
        _LOGGER.debug("Found Streamdeck at host %s with mac %s", self.host, self.mac)
        return self.async_show_form(step_id="user")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user config flow."""
        if user_input:
            self.host = user_input.get("host", "")
            if not isinstance(self.host, str):
                raise ValueError("Unknown type for host")
            self.mac = await _async_get_mac_address(self.hass, self.host)
            _LOGGER.info("Host %s has MAC %s", self.host, self.mac)

        errors: dict[str, str] = {}
        if self.host is not None and self.mac is not None:
            deck = StreamDeckApi(self.host)
            info = await deck.get_info()

            if info is False or not isinstance(info, SDInfo):
                errors["base"] = "cannot_connect"
                data_schema = vol.Schema(
                    {
                        vol.Required("name", default="Stream Deck"): str,
                        vol.Required("host", default=""): str,
                        vol.Required(
                            "enabled_platforms",
                            default=DEFAULT_PLATFORMS,
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=AVAILABLE_PLATFORMS,
                                multiple=True,
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        ),
                    }
                )
                return self.async_show_form(
                    step_id="user",
                    data_schema=data_schema,
                    errors=errors,
                )

            # Prevent double config
            await self.async_set_unique_id(self.mac)
            self._abort_if_unique_id_configured()

            if user_input is not None:
                data = {
                    "name": user_input["name"],
                    "host": self.host,
                    "mac": self.mac,
                    "model": get_model(info),
                    "version": info.application.version,
                    "enabled_platforms": user_input["enabled_platforms"],
                    "buttons": {},
                }
                return self.async_create_entry(title=user_input["name"], data=data)

        data_schema = vol.Schema(
            {
                vol.Required("name", default="Stream Deck"): str,
                vol.Required("host", default=self.host): str,
                vol.Required(
                    "enabled_platforms",
                    default=DEFAULT_PLATFORMS,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=AVAILABLE_PLATFORMS,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            last_step=True,
        )


# Copied from homeassistant/components/dlna_dmr/config_flow.py
async def _async_get_mac_address(hass: HomeAssistant, host: str) -> str | None:
    """Get mac address from host name, IPv4 address, or IPv6 address."""
    # Help mypy, which has trouble with the async_add_executor_job + partial call
    mac_address: str | None
    # getmac has trouble using IPv6 addresses as the "hostname" parameter so
    # assume host is an IP address, then handle the case it's not.
    try:
        ip_addr = ipaddress.ip_address(host)
    except ValueError:
        mac_address = await hass.async_add_executor_job(
            partial(get_mac_address, hostname=host)
        )
    else:
        if ip_addr.version == 4:
            mac_address = await hass.async_add_executor_job(
                partial(get_mac_address, ip=host)
            )
        else:
            # Drop scope_id from IPv6 address by converting via int
            ip_addr = ipaddress.IPv6Address(int(ip_addr))
            mac_address = await hass.async_add_executor_job(
                partial(get_mac_address, ip6=str(ip_addr))
            )

    if not mac_address:
        # !!! TESTING ONLY !!!
        if host == "10.1.4.5":
            return "80:61:5f:08:2B:e2"
        return None

    return dr.format_mac(mac_address)
