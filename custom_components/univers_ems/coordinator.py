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
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the API."""
        try:
            return await self.client.async_get_data()
        except UniversEMSError as err:
            raise UpdateFailed(f"Univers EMS HA update failed: {err}") from err
