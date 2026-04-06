# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap

"""Number platform for Univers EMS — forced charge/discharge controls."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    CONF_STORAGE_ASSET_ID,
    MP_FORCED_CHARGE_PWR,
    MP_FORCED_DISCHARGE_PWR,
    MP_FORCED_PERIOD,
    FORCED_POWER_MIN,
    FORCED_POWER_MAX,
    FORCED_PERIOD_MIN,
    FORCED_PERIOD_MAX,
)
from .coordinator import UniversEMSCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class UniversNumberDescription(NumberEntityDescription):
    """Describes a Univers EMS number entity."""

    measurement_point: str = ""


NUMBER_DESCRIPTIONS: tuple[UniversNumberDescription, ...] = (
    UniversNumberDescription(
        key="forced_charge_power",
        name="Forced Charge Power",
        measurement_point=MP_FORCED_CHARGE_PWR,
        native_min_value=FORCED_POWER_MIN,
        native_max_value=FORCED_POWER_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=NumberDeviceClass.POWER,
        mode=NumberMode.BOX,
        icon="mdi:battery-arrow-up",
    ),
    UniversNumberDescription(
        key="forced_discharge_power",
        name="Forced Discharge Power",
        measurement_point=MP_FORCED_DISCHARGE_PWR,
        native_min_value=FORCED_POWER_MIN,
        native_max_value=FORCED_POWER_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=NumberDeviceClass.POWER,
        mode=NumberMode.BOX,
        icon="mdi:battery-arrow-down",
    ),
    UniversNumberDescription(
        key="forced_period",
        name="Forced Charge/Discharge Period",
        measurement_point=MP_FORCED_PERIOD,
        native_min_value=FORCED_PERIOD_MIN,
        native_max_value=FORCED_PERIOD_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        icon="mdi:timer-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Univers EMS number entities from a config entry."""
    coordinator: UniversEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    asset_id: str = entry.data["asset_id"]
    storage_asset_id: str = entry.data[CONF_STORAGE_ASSET_ID]

    entities = [
        UniversEMSNumberEntity(coordinator, desc, asset_id, storage_asset_id)
        for desc in NUMBER_DESCRIPTIONS
    ]
    # Register with coordinator so the service handler can find them
    for entity in entities:
        coordinator.number_entities[entity.entity_description.measurement_point] = entity

    async_add_entities(entities)


class UniversEMSNumberEntity(CoordinatorEntity[UniversEMSCoordinator], NumberEntity):
    """A number entity representing a forced control parameter.

    The entity reflects the current value read from the API.
    Changing the value stages it locally but does NOT send it to the inverter
    immediately — use the send_forced_control service to commit all changes.
    """

    _attr_has_entity_name = True
    entity_description: UniversNumberDescription

    def __init__(
        self,
        coordinator: UniversEMSCoordinator,
        description: UniversNumberDescription,
        asset_id: str,
        storage_asset_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._asset_id = asset_id
        self._storage_asset_id = storage_asset_id
        self._attr_unique_id = f"{DOMAIN}_{asset_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset_id)},
            name="Univers EMS Solar Site",
            manufacturer=MANUFACTURER,
            model="EnOS Solar Site",
        )
        # Staged value — set when user changes the entity, cleared on next poll
        self._staged_value: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return staged value if set, otherwise the last polled value."""
        if self._staged_value is not None:
            return self._staged_value
        return self._polled_value()

    def _polled_value(self) -> float | None:
        """Extract the current value from coordinator data."""
        if self.coordinator.data is None:
            return None
        raw = (
            self.coordinator.data
            .get("control", {})
            .get(self.entity_description.measurement_point, {})
            .get("value")
        )
        return float(raw) if raw is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Stage the new value locally. Does not write to the inverter."""
        self._staged_value = value
        self.async_write_ha_state()
        _LOGGER.debug(
            "Staged %s = %s (not yet sent — call send_forced_control service)",
            self.entity_description.measurement_point,
            value,
        )

    def get_staged_or_current(self) -> int | None:
        """Return staged value if set, else polled value, as int."""
        val = self._staged_value if self._staged_value is not None else self._polled_value()
        return int(val) if val is not None else None

    def clear_staged(self) -> None:
        """Clear staged value after a successful control send."""
        self._staged_value = None

    def _handle_coordinator_update(self) -> None:
        """On poll, clear staged value so we reflect the confirmed API state."""
        self._staged_value = None
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        polled = self._polled_value()
        return {
            "polled_value": polled,
            "staged_value": self._staged_value,
            "pending_send": self._staged_value is not None,
        }
