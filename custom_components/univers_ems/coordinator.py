# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap

"""DataUpdateCoordinator for Univers EMS."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniversEMSClient, UniversEMSError
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class UniversEMSCoordinator(DataUpdateCoordinator):
    """Polls the Univers EMS API on a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: UniversEMSClient,
        inverter_asset_id: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.inverter_asset_id = inverter_asset_id
        # Populated by number.py and select.py during async_setup_entry
        # so __init__.py service handler can find entities without HA registry lookups
        self.number_entities: dict[str, Any] = {}
        self.select_entities: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch site data and control data, merge into a single dict."""
        try:
            site_data = await self.client.async_get_data()
            control_data = await self.client.async_get_control_data(self.inverter_asset_id)
        except UniversEMSError as err:
            raise UpdateFailed(f"Univers EMS update failed: {err}") from err

        # Merge control measurement points into the top-level data dict
        # under a "control" key so sensor/number/select entities can access them
        # without colliding with site-level measurement point keys.
        return {
            **site_data,
            "control": control_data.get("measurementPoints", {}),
        }
