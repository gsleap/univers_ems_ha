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
from .const import (
    DOMAIN,
    CONF_ASSET_ID,
    CONF_INVERTER_ASSET_ID,
    CONF_STORAGE_ASSET_ID,
    DEFAULT_SCAN_INTERVAL,
)

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

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "UniversEMSOptionsFlow":
        """Return the options flow handler."""
        return UniversEMSOptionsFlow(config_entry)

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
                discovered = await client.async_discover_devices()
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

                entry_data = {
                    **user_input,
                    CONF_INVERTER_ASSET_ID: discovered["inverter_asset_id"],
                    CONF_STORAGE_ASSET_ID: discovered["storage_asset_id"],
                }

                _LOGGER.debug(
                    "Discovered inverter_asset_id=%s, storage_asset_id=%s",
                    discovered["inverter_asset_id"],
                    discovered["storage_asset_id"],
                )

                return self.async_create_entry(
                    title=f"Univers EMS ({user_input[CONF_ASSET_ID]})",
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )


class UniversEMSOptionsFlow(config_entries.OptionsFlow):
    """Options flow — allows changing scan_interval after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional("scan_interval", default=current_interval): vol.All(int, vol.Range(min=10, max=3600)),
                }
            ),
        )
