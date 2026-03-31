"""Sensor platform for Univers EMS."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    MP_PV_POWER,
    MP_BATTERY_POWER,
    MP_BATTERY_SOC,
    MP_GRID_POWER,
    MP_LOAD_POWER,
    MP_GEN_POWER,
)
from .coordinator import UniversEMSCoordinator


def _mp_value(data: dict, point: str) -> float | None:
    """Safely extract a float value from measurementPoints."""
    raw = data.get("measurementPoints", {}).get(point, {}).get("value")
    return float(raw) if raw is not None else None


# ---------------------------------------------------------------------------
# Raw measurement-point sensors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversSensorDescription(SensorEntityDescription):
    """Sensor that reads directly from a measurement point."""

    measurement_point: str = ""
    negate: bool = False


SENSOR_DESCRIPTIONS: tuple[UniversSensorDescription, ...] = (
    UniversSensorDescription(
        key="pv_power",
        name="PV Power",
        measurement_point=MP_PV_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
    ),
    UniversSensorDescription(
        key="battery_power",
        name="Battery Power",
        measurement_point=MP_BATTERY_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        # Positive = charging, negative = discharging
    ),
    UniversSensorDescription(
        key="battery_soc",
        name="Battery State of Charge",
        measurement_point=MP_BATTERY_SOC,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    UniversSensorDescription(
        key="grid_power",
        name="Grid Power",
        measurement_point=MP_GRID_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower",
        # Positive = export, negative = import
    ),
    UniversSensorDescription(
        key="load_power",
        name="Load Power",
        measurement_point=MP_LOAD_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt",
    ),
    UniversSensorDescription(
        key="generation_power",
        name="Generation Power",
        measurement_point=MP_GEN_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-panel",
    ),
)


# ---------------------------------------------------------------------------
# Derived sensors (split signed values for Energy dashboard)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversDerivedSensorDescription(SensorEntityDescription):
    """Sensor whose value is computed from coordinator data via a callable."""

    # Receives the full asset data dict, returns float | None
    compute: Callable[[dict[str, Any]], float | None] = field(default=lambda _: None)


def _pos(val: float | None) -> float | None:
    """Return val if positive, else 0.0."""
    if val is None:
        return None
    return round(max(val, 0.0), 3)


def _neg_as_pos(val: float | None) -> float | None:
    """Return abs(val) if negative, else 0.0."""
    if val is None:
        return None
    return round(max(-val, 0.0), 3)


DERIVED_DESCRIPTIONS: tuple[UniversDerivedSensorDescription, ...] = (
    UniversDerivedSensorDescription(
        key="grid_import_power",
        name="Grid Import Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-import",
        compute=lambda d: _neg_as_pos(_mp_value(d, MP_GRID_POWER)),
    ),
    UniversDerivedSensorDescription(
        key="grid_export_power",
        name="Grid Export Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-export",
        compute=lambda d: _pos(_mp_value(d, MP_GRID_POWER)),
    ),
    UniversDerivedSensorDescription(
        key="battery_charge_power",
        name="Battery Charge Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-arrow-up",
        compute=lambda d: _pos(_mp_value(d, MP_BATTERY_POWER)),
    ),
    UniversDerivedSensorDescription(
        key="battery_discharge_power",
        name="Battery Discharge Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-arrow-down",
        compute=lambda d: _neg_as_pos(_mp_value(d, MP_BATTERY_POWER)),
    ),
)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Univers EMS sensors from a config entry."""
    coordinator: UniversEMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    asset_id: str = entry.data["asset_id"]

    entities: list[SensorEntity] = [UniversEMSSensor(coordinator, desc, asset_id) for desc in SENSOR_DESCRIPTIONS]
    entities += [UniversEMSDerivedSensor(coordinator, desc, asset_id) for desc in DERIVED_DESCRIPTIONS]
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------


class _UniversEMSBase(CoordinatorEntity[UniversEMSCoordinator], SensorEntity):
    """Shared base for all Univers EMS sensor entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UniversEMSCoordinator,
        description: SensorEntityDescription,
        asset_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._asset_id = asset_id
        self._attr_unique_id = f"{DOMAIN}_{asset_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset_id)},
            name="Univers EMS Solar Site",
            manufacturer=MANUFACTURER,
            model="EnOS Solar Site",
        )


class UniversEMSSensor(_UniversEMSBase):
    """Sensor that reads directly from a measurement point."""

    entity_description: UniversSensorDescription

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        val = _mp_value(self.coordinator.data, self.entity_description.measurement_point)
        if val is None:
            return None
        if self.entity_description.negate:
            val = -val
        return round(val, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        mp_data = self.coordinator.data.get("measurementPoints", {}).get(self.entity_description.measurement_point, {})
        return {
            "last_updated_local": mp_data.get("localtime"),
            "last_updated_ts": mp_data.get("timestamp"),
        }


class UniversEMSDerivedSensor(_UniversEMSBase):
    """Sensor whose value is computed from coordinator data."""

    entity_description: UniversDerivedSensorDescription

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.compute(self.coordinator.data)
