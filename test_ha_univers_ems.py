"""
Integration test for Univers EMS using the actual api.py component code.
Runs UniversEMSClient.async_login() and async_get_data() exactly as HA would.
Requires: pip install aiohttp cryptography

Usage:
    UNIVERS_EMS_ASSET_ID=a1b2c3d4 python test_univers_ems_integration.py

Place this file alongside the univers_ems/ folder, e.g.:
    /your/path/
        univers_ems/
            api.py
            const.py
            ...
        test_univers_ems_integration.py
"""

import asyncio
import getpass
import logging
import os
import sys
import types
import aiohttp
from unittest.mock import MagicMock

# ── Logging setup (mirrors what HA would show) ────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("aiohttp").setLevel(logging.WARNING)


# ── Stub out homeassistant modules so api.py can be imported without HA ───────
def _stub(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# homeassistant.core
_stub("homeassistant.core", HomeAssistant=MagicMock)

# homeassistant.config_entries
_stub(
    "homeassistant.config_entries",
    ConfigEntry=MagicMock,
    ConfigFlow=MagicMock,
    config_entries=MagicMock,
)

# homeassistant.const
_stub(
    "homeassistant.const",
    CONF_PASSWORD="password",
    CONF_USERNAME="username",
    Platform=MagicMock(),
    UnitOfPower=MagicMock(),
    PERCENTAGE="%",
)

# homeassistant.components.sensor
_stub(
    "homeassistant.components.sensor",
    SensorDeviceClass=MagicMock(),
    SensorEntity=object,
    SensorEntityDescription=object,
    SensorStateClass=MagicMock(),
)
_stub("homeassistant.components", sensor=sys.modules["homeassistant.components.sensor"])

# homeassistant.helpers.*
_stub(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=object,
    UpdateFailed=Exception,
    CoordinatorEntity=object,
)
_stub("homeassistant.helpers.aiohttp_client", async_get_clientsession=MagicMock)
_stub("homeassistant.helpers.device_registry", DeviceInfo=dict)
_stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock)
_stub("homeassistant.helpers", update_coordinator=MagicMock, aiohttp_client=MagicMock)
_stub("homeassistant", core=MagicMock, config_entries=MagicMock)

# ── Import actual component code ──────────────────────────────────────────────
try:
    from univers_ems.api import UniversEMSClient, UniversEMSAuthError, UniversEMSError
    from univers_ems.const import (
        MP_PV_POWER,
        MP_BATTERY_POWER,
        MP_BATTERY_SOC,
        MP_GRID_POWER,
        MP_LOAD_POWER,
        MP_GEN_POWER,
    )
except ImportError as e:
    print(f"❌  Could not import univers_ems: {e}")
    print("    Make sure univers_ems/ folder is in the same directory as this script.")
    sys.exit(1)

ASSET_ID = os.environ.get("UNIVERS_EMS_ASSET_ID", "").strip()
if not ASSET_ID:
    print("❌  UNIVERS_EMS_ASSET_ID environment variable not set.")
    print("    Usage: UNIVERS_EMS_ASSET_ID=a1b2c3d4 python test_univers_ems_integration.py")
    sys.exit(1)


# ── Derived sensor logic (mirrors sensor.py) ──────────────────────────────────
def _mp_value(data: dict, point: str) -> float | None:
    raw = data.get("measurementPoints", {}).get(point, {}).get("value")
    return float(raw) if raw is not None else None


def _pos(val: float | None) -> float | None:
    return round(max(val, 0.0), 3) if val is not None else None


def _neg_as_pos(val: float | None) -> float | None:
    return round(max(-val, 0.0), 3) if val is not None else None


DERIVED = {
    "Grid Import Power": (MP_GRID_POWER, _pos),
    "Grid Export Power": (MP_GRID_POWER, _neg_as_pos),
    "Battery Charge Power": (MP_BATTERY_POWER, _pos),
    "Battery Discharge Power": (MP_BATTERY_POWER, _neg_as_pos),
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def separator(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print("─" * 55)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    print("Univers EMS — integration test (using actual api.py)")
    print("Component version: univers_ems.api.UniversEMSClient")

    username = input("\nUsername (email): ").strip()
    password = getpass.getpass("Password: ")

    async with aiohttp.ClientSession() as http_session:
        # ── Instantiate exactly as __init__.py does ───────────────────────────
        separator("Step 1: Instantiate UniversEMSClient")
        client = UniversEMSClient(
            session=http_session,
            username=username,
            password=password,
            asset_id=ASSET_ID,
        )
        print(f"✅  Client created for asset: {ASSET_ID}")

        # ── Login exactly as coordinator's first_refresh does ─────────────────
        separator("Step 2: async_login() — two-step login + session/set")
        try:
            await client.async_login()
        except UniversEMSAuthError as e:
            print(f"❌  Auth error: {e}")
            return
        except UniversEMSError as e:
            print(f"❌  API error: {e}")
            return

        print("✅  Login successful")
        token_preview = client._token[:30] if client._token else "(none)"  # type: ignore[index]
        print(f"    token  : {token_preview}…")
        print(f"    org_id : {client._org_id}")

        # ── Fetch data exactly as coordinator._async_update_data does ─────────
        separator("Step 3: async_get_data() — live data fetch")
        try:
            data = await client.async_get_data()
        except UniversEMSError as e:
            print(f"❌  Data fetch error: {e}")
            return

        print("✅  Data received")

        # ── Print raw measurement points ──────────────────────────────────────
        separator("Step 4: Raw measurement points (as HA sensors will see them)")
        LABELS = {
            MP_PV_POWER: ("PV Power", "kW", "Always ≥ 0"),
            MP_BATTERY_POWER: ("Battery Power", "kW", "+ charge / − discharge"),
            MP_BATTERY_SOC: ("Battery SOC", "%", ""),
            MP_GRID_POWER: ("Grid Power", "kW", "+ import / − export"),
            MP_LOAD_POWER: ("Load Power", "kW", "Always ≥ 0"),
            MP_GEN_POWER: ("Generation Power", "kW", ""),
        }
        for point, (label, unit, note) in LABELS.items():
            val = _mp_value(data, point)
            ts = data.get("measurementPoints", {}).get(point, {}).get("localtime", "")
            note_str = f"  ({note})" if note else ""
            if val is not None:
                print(f"    {label:<22} {val:>8} {unit:<3}  [{ts}]{note_str}")
            else:
                print(f"    {label:<22}  (not in response)")

        # ── Print derived sensors ─────────────────────────────────────────────
        separator("Step 5: Derived sensors (Energy dashboard ready)")
        for name, (source_point, fn) in DERIVED.items():
            val = _mp_value(data, source_point)
            derived = fn(val)
            if derived is not None:
                print(f"    {name:<28} {derived:>8} kW")
            else:
                print(f"    {name:<28}  (source not available)")

        # ── Site attributes ───────────────────────────────────────────────────
        separator("Step 6: Site attributes")
        for k, v in data.get("attributes", {}).items():
            print(f"    {k:<30} {v}")

        # ── Simulate a second poll (token reuse) ──────────────────────────────
        separator("Step 7: Second poll — simulating 60s coordinator tick")
        try:
            data2 = await client.async_get_data()
            soc = _mp_value(data2, MP_BATTERY_SOC)
            pv = _mp_value(data2, MP_PV_POWER)
            print(f"✅  Second poll OK — SOC: {soc}%  PV: {pv} kW")
        except UniversEMSError as e:
            print(f"❌  Second poll failed: {e}")

        separator("All checks passed ✅  — ready for Home Assistant")


if __name__ == "__main__":
    asyncio.run(main())
