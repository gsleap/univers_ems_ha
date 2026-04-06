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
    scan_interval = entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)

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
        """Read staged values from entities and send changed ones to the inverter."""
        # Find the coordinator and config entry — we support only one entry for now
        domain_data: dict[str, UniversEMSCoordinator] = hass.data.get(DOMAIN, {})
        if not domain_data:
            _LOGGER.error("send_forced_control: no active Univers EMS config entries")
            return

        # Use the first (and typically only) entry
        entry_id = next(iter(domain_data))
        coordinator: UniversEMSCoordinator = domain_data[entry_id]

        # Get the config entry to retrieve storage_asset_id
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            _LOGGER.error("send_forced_control: could not find config entry %s", entry_id)
            return

        storage_asset_id: str = entry.data[CONF_STORAGE_ASSET_ID]

        # Collect staged values from number and select entities
        # We look up entities by their unique_id pattern
        asset_id: str = entry.data[CONF_ASSET_ID]

        # Gather staged values from entities stored on the coordinator
        from .number import UniversEMSNumberEntity
        from .select import UniversEMSModeSelect

        number_entities: dict[str, UniversEMSNumberEntity] = coordinator.number_entities
        select_entities: dict[str, UniversEMSModeSelect] = coordinator.select_entities

        if not number_entities and not select_entities:
            _LOGGER.error(
                "send_forced_control: could not find Univers EMS control entities. "
                "Has the integration loaded fully?"
            )
            return

        # Build the set of current API values from coordinator data
        control_data = coordinator.data.get("control", {}) if coordinator.data else {}

        def _current_api_value(mp: str) -> int | None:
            raw = control_data.get(mp, {}).get("value")
            return int(raw) if raw is not None else None

        # Build changes dict — only include values that differ from the API
        changes: dict[str, int] = {}

        # Mode (select)
        mode_entity = select_entities.get(MP_CHARGE_OR_DISCHARGE)
        if mode_entity is not None:
            new_mode = mode_entity.get_staged_or_current_value()
            cur_mode = _current_api_value(MP_CHARGE_OR_DISCHARGE)
            if new_mode is not None and new_mode != cur_mode:
                changes[MP_CHARGE_OR_DISCHARGE] = new_mode

        # Number entities
        for mp_id in (MP_FORCED_CHARGE_PWR, MP_FORCED_DISCHARGE_PWR, MP_FORCED_PERIOD):
            num_entity = number_entities.get(mp_id)
            if num_entity is not None:
                new_val = num_entity.get_staged_or_current()
                cur_val = _current_api_value(mp_id)
                if new_val is not None and new_val != cur_val:
                    changes[mp_id] = new_val

        if not changes:
            _LOGGER.info("send_forced_control: no changes to send")
            return

        _LOGGER.info("send_forced_control: sending changes: %s", changes)

        try:
            command_id = await coordinator.client.async_send_control(
                storage_asset_id=storage_asset_id,
                changes=changes,
            )
            _LOGGER.info(
                "send_forced_control: accepted by inverter, commandId=%s", command_id
            )
        except UniversEMSError as err:
            _LOGGER.error("send_forced_control failed: %s", err)
            return

        # Clear staged values on success
        if mode_entity is not None and MP_CHARGE_OR_DISCHARGE in changes:
            mode_entity.clear_staged()
        for mp_id in (MP_FORCED_CHARGE_PWR, MP_FORCED_DISCHARGE_PWR, MP_FORCED_PERIOD):
            num_entity = number_entities.get(mp_id)
            if num_entity is not None and mp_id in changes:
                num_entity.clear_staged()

        # Trigger an immediate coordinator refresh to confirm new state
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_FORCED_CONTROL,
        handle_send_forced_control,
        schema=vol.Schema({}),
    )
