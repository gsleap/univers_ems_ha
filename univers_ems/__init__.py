"""Univers EMS Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UniversEMSClient
from .const import DOMAIN, CONF_ASSET_ID, DEFAULT_SCAN_INTERVAL
from .coordinator import UniversEMSCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Univers EMS from a config entry."""
    session = async_get_clientsession(hass)

    client = UniversEMSClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        asset_id=entry.data[CONF_ASSET_ID],
    )

    scan_interval = entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)

    coordinator = UniversEMSCoordinator(hass, client, scan_interval)

    # Perform initial login + fetch so HA knows immediately if it works
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
