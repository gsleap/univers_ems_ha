# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap

"""Univers EMS Home Assistant Integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .api import UniversEMSClient, UniversEMSError
from .const import (
    DOMAIN,
    CONF_ASSET_ID,
    CONF_INVERTER_ASSET_ID,
    CONF_STORAGE_ASSET_ID,
    DEFAULT_SCAN_INTERVAL,
    MP_CHARGE_OR_DISCHARGE,
    MP_FORCED_CHARGE_PWR,
    MP_FORCED_DISCHARGE_PWR,
    MP_FORCED_PERIOD,
    MP_SETTING_MODE,
    CHARGE_OR_DISCHARGE_IDLE,
    CHARGE_OR_DISCHARGE_CHARGE,
    CHARGE_OR_DISCHARGE_DISCHARGE,
    SETTING_MODE_DURATION,
)
from .coordinator import UniversEMSCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT]

SERVICE_SEND_FORCED_CONTROL = "send_forced_control"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Univers EMS from a config entry."""
    session = async_get_clientsession(hass)
    client = UniversEMSClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        asset_id=entry.data[CONF_ASSET_ID],
    )

    inverter_asset_id: str = entry.data[CONF_INVERTER_ASSET_ID]
    scan_interval = entry.options.get("scan_interval", entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))

    coordinator = UniversEMSCoordinator(hass, client, inverter_asset_id, scan_interval)

    # Perform initial login + fetch so HA knows immediately if it works
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the send_forced_control service (once, not per entry)
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_FORCED_CONTROL):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove service if no entries remain
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_FORCED_CONTROL)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register integration-level services."""

    async def handle_send_forced_control(call: ServiceCall) -> None:
        """Send forced charge/discharge parameters to the inverter.

        Always sends the full set of parameters required for the selected mode,
        regardless of whether values have changed since the last poll. This avoids
        any risk of stale coordinator data causing missed updates.

        - Idle:     sends ChargeOrDischarge = 0
        - Charge:   sends ChargeOrDischarge = 1, SettingMode = 0 (Duration),
                    ForcedChargePwr, ForcedChargeDischagrePeriod
        - Discharge: sends ChargeOrDischarge = 2, SettingMode = 0 (Duration),
                    ForcedDischargePwr, ForcedChargeDischagrePeriod
        """
        domain_data: dict[str, UniversEMSCoordinator] = hass.data.get(DOMAIN, {})
        if not domain_data:
            _LOGGER.error("send_forced_control: no active Univers EMS config entries")
            return

        entry_id = next(iter(domain_data))
        coordinator: UniversEMSCoordinator = domain_data[entry_id]

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            _LOGGER.error("send_forced_control: could not find config entry %s", entry_id)
            return

        storage_asset_id: str = entry.data[CONF_STORAGE_ASSET_ID]

        from .number import UniversEMSNumberEntity
        from .select import UniversEMSModeSelect

        number_entities: dict[str, UniversEMSNumberEntity] = coordinator.number_entities
        select_entities: dict[str, UniversEMSModeSelect] = coordinator.select_entities

        if not number_entities and not select_entities:
            _LOGGER.error(
                "send_forced_control: could not find Univers EMS control entities. Has the integration loaded fully?"
            )
            return

        # Determine the mode to send — default to Idle if unset
        mode_entity = select_entities.get(MP_CHARGE_OR_DISCHARGE)
        mode_label: str = (mode_entity.current_option if mode_entity else None) or "Idle"

        def _num_value(mp: str) -> int:
            """Return staged-or-current value for a number entity, defaulting to 0."""
            entity = number_entities.get(mp)
            if entity is None:
                return 0
            val = entity.get_staged_or_current()
            return val if val is not None else 0

        # Build the full parameter set for the selected mode
        if mode_label == "Charge":
            changes = {
                MP_CHARGE_OR_DISCHARGE: CHARGE_OR_DISCHARGE_CHARGE,
                MP_SETTING_MODE: SETTING_MODE_DURATION,
                MP_FORCED_CHARGE_PWR: _num_value(MP_FORCED_CHARGE_PWR),
                MP_FORCED_PERIOD: _num_value(MP_FORCED_PERIOD),
            }
        elif mode_label == "Discharge":
            changes = {
                MP_CHARGE_OR_DISCHARGE: CHARGE_OR_DISCHARGE_DISCHARGE,
                MP_SETTING_MODE: SETTING_MODE_DURATION,
                MP_FORCED_DISCHARGE_PWR: _num_value(MP_FORCED_DISCHARGE_PWR),
                MP_FORCED_PERIOD: _num_value(MP_FORCED_PERIOD),
            }
        else:
            # Idle (default)
            changes = {
                MP_CHARGE_OR_DISCHARGE: CHARGE_OR_DISCHARGE_IDLE,
            }

        _LOGGER.info("send_forced_control: sending mode=%s params=%s", mode_label, changes)

        try:
            command_id = await coordinator.client.async_send_control(
                storage_asset_id=storage_asset_id,
                changes=changes,
            )
            _LOGGER.info("send_forced_control: accepted by inverter, commandId=%s", command_id)
        except UniversEMSError as err:
            _LOGGER.error("send_forced_control failed: %s", err)
            return

        # Trigger an immediate coordinator refresh to confirm new state
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_FORCED_CONTROL,
        handle_send_forced_control,
        schema=vol.Schema({}),
    )
