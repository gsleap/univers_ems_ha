# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap
"""Config flow for Univers EMS."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UniversEMSClient, UniversEMSAuthError, UniversEMSError
from .const import DOMAIN, CONF_ASSET_ID, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ASSET_ID, default="a1b2c3d4"): str,
        vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=10, max=3600)),
    }
)


class UniversEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = UniversEMSClient(
                session=session,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                asset_id=user_input[CONF_ASSET_ID],
            )
            try:
                await client.async_login()
            except UniversEMSAuthError:
                errors["base"] = "invalid_auth"
            except UniversEMSError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"univers_ems_{user_input[CONF_ASSET_ID]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Univers EMS ({user_input[CONF_ASSET_ID]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
