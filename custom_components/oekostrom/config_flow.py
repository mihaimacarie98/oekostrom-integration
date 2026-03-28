"""Config flow for oekostrom AG integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import OekostromApi, OekostromApiError, OekostromAuthError
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class OekostromConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for oekostrom AG."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_username: str | None = None

    async def _test_credentials(
        self, username: str, password: str
    ) -> dict[str, Any]:
        """Test credentials and return user data. Always closes its session."""
        api = OekostromApi(username, password)
        try:
            return await api.authenticate()
        finally:
            await api.close()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                result = await self._test_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except OekostromAuthError:
                errors["base"] = "invalid_auth"
            except (OekostromApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "unknown"
            else:
                unique_id = str(result["WeuId"])
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = result.get("UserEMail", user_input[CONF_USERNAME])
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth when credentials become invalid."""
        self._reauth_username = entry_data.get(CONF_USERNAME)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self._test_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except OekostromAuthError:
                errors["base"] = "invalid_auth"
            except (OekostromApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry, data=user_input
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=self._reauth_username or ""
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )
