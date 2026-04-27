"""Config flow for SVP BV District Heating integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import SVPBVApiClient, SVPBVApiError, SVPBVAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Optional("scan_interval", default=60): vol.All(
            vol.Coerce(int), vol.Range(min=15, max=1440)
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate credentials by attempting a login."""
    session = async_create_clientsession(hass)
    try:
        client = SVPBVApiClient(data["username"], data["password"], session)
        await client.async_login()
        all_data = await client.async_get_all_data()
        return {"title": all_data.get("customer_name") or data["username"]}
    finally:
        await session.close()


class SVPBVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SVP BV."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except SVPBVAuthError as err:
                _LOGGER.warning("SVP BV auth error: %s", err)
                errors["base"] = "invalid_auth"
            except SVPBVApiError as err:
                _LOGGER.warning("SVP BV api error: %s", err)
                errors["base"] = "invalid_auth"
            except aiohttp.ClientConnectorError as err:
                _LOGGER.warning("SVP BV connect error: %s", err)
                errors["base"] = "cannot_connect"
            except aiohttp.ClientResponseError as err:
                _LOGGER.warning("SVP BV HTTP error %s: %s", err.status, err)
                if err.status == 403:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during SVP BV config flow: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "portal_url": "https://mijn.svpbv.nl",
            },
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Handle import from configuration.yaml."""
        await self.async_set_unique_id(import_data["username"])
        self._abort_if_unique_id_configured(updates=import_data)

        try:
            info = await validate_input(self.hass, import_data)
        except (SVPBVAuthError, SVPBVApiError):
            return self.async_abort(reason="invalid_auth")
        except Exception:  # noqa: BLE001
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(title=info["title"], data=import_data)
