# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap

"""Select platform for Univers EMS — forced charge/discharge mode."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    CONF_STORAGE_ASSET_ID,
    MP_CHARGE_OR_DISCHARGE,
    CHARGE_OR_DISCHARGE_OPTIONS,
)
from .coordinator import UniversEMSCoordinator

_LOGGER = logging.getLogger(__name__)

# Map option label → int value and back
_LABEL_TO_VALUE: dict[str, int] = {v: k for k, v in CHARGE_OR_DISCHARGE_OPTIONS.items()}
_VALUE_TO_LABEL: dict[int, str] = CHARGE_OR_DISCHARGE_OPTIONS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Univers EMS select entity from a config entry."""
    coordinator: UniversEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    asset_id: str = entry.data["asset_id"]
    storage_asset_id: str = entry.data[CONF_STORAGE_ASSET_ID]

    entity = UniversEMSModeSelect(coordinator, asset_id, storage_asset_id)
    # Register with coordinator so the service handler can find it
    coordinator.select_entities[MP_CHARGE_OR_DISCHARGE] = entity
    async_add_entities([entity])


class UniversEMSModeSelect(CoordinatorEntity[UniversEMSCoordinator], SelectEntity):
    """Select entity for the forced charge/discharge mode.

    Staging behaviour mirrors the number entities — selecting a new option
    stages the value locally. Use the send_forced_control service to commit.
    """

    _attr_has_entity_name = True
    _attr_name = "Forced Mode"
    _attr_icon = "mdi:battery-sync"
    _attr_options = list(_LABEL_TO_VALUE.keys())  # ["Idle", "Charge", "Discharge"]

    def __init__(
        self,
        coordinator: UniversEMSCoordinator,
        asset_id: str,
        storage_asset_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._storage_asset_id = storage_asset_id
        self._attr_unique_id = f"{DOMAIN}_{asset_id}_forced_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset_id)},
            name="Univers EMS Solar Site",
            manufacturer=MANUFACTURER,
            model="EnOS Solar Site",
        )
        self._staged_label: str | None = None

    @property
    def current_option(self) -> str | None:
        """Return staged label if set, otherwise the last polled value."""
        if self._staged_label is not None:
            return self._staged_label
        return self._polled_label()

    def _polled_label(self) -> str | None:
        """Extract current mode label from coordinator data."""
        if self.coordinator.data is None:
            return None
        raw = (
            self.coordinator.data
            .get("control", {})
            .get(MP_CHARGE_OR_DISCHARGE, {})
            .get("value")
        )
        if raw is None:
            return None
        return _VALUE_TO_LABEL.get(int(raw))

    async def async_select_option(self, option: str) -> None:
        """Stage the new mode locally. Does not write to the inverter."""
        if option not in _LABEL_TO_VALUE:
            raise ValueError(f"Invalid mode option: {option!r}")
        self._staged_label = option
        self.async_write_ha_state()
        _LOGGER.debug(
            "Staged forced mode = %r (not yet sent — call send_forced_control service)",
            option,
        )

    def get_staged_or_current_value(self) -> int | None:
        """Return the integer value of staged or current option."""
        label = self._staged_label if self._staged_label is not None else self._polled_label()
        if label is None:
            return None
        return _LABEL_TO_VALUE.get(label)

    def clear_staged(self) -> None:
        """Clear staged value after a successful control send."""
        self._staged_label = None

    def _handle_coordinator_update(self) -> None:
        """On poll, clear staged value so we reflect the confirmed API state."""
        self._staged_label = None
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        polled = self._polled_label()
        return {
            "polled_value": polled,
            "staged_value": self._staged_label,
            "pending_send": self._staged_label is not None,
        }
