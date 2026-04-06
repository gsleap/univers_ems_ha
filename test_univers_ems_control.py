"""
Standalone test for Univers EMS forced charge/discharge control API.

Discovers device IDs automatically from the site asset ID, reads current
forced control settings, prompts for new values, and sends a control command.

Requires: pip install aiohttp cryptography

Usage:
    UNIVERS_EMS_ASSET_ID=7g3Co6Bp python test_univers_ems_control.py
"""

import asyncio
import base64
import getpass
import os
import sys
import time

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://app-portal-eu2.envisioniot.com"
APP_ID = "6508dd96-c72f-4c75-85d3-11c6e1380f75"
LOGIN_URL = f"{BASE_URL}/app-portal/web/v1/login"
SESSION_URL_BASE = f"{BASE_URL}/app-portal/web/v1/session/set"
ASSET_LIST_URL = f"{BASE_URL}/hossain-bff/monitor/v1.0/asset/list"
ASSET_DETAIL_URL = f"{BASE_URL}/hossain-bff/monitor/v1.0/asset/detail"
CONTROL_URL = f"{BASE_URL}/hossain-bff/connect/v1.0/device/control"

LOGIN_KEY_ID = "FIXED_KEY_ID"

SITE_ASSET_ID = os.environ.get("UNIVERS_EMS_ASSET_ID", "").strip()
if not SITE_ASSET_ID:
    print("❌ UNIVERS_EMS_ASSET_ID environment variable not set.")
    print("   Usage: UNIVERS_EMS_ASSET_ID=7g3Co6Bp python test_univers_ems_control.py")
    sys.exit(1)

PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAkB87CRMTufaNoG/EaHaX\n"
    "vb5/rBan6g5sta1Yg6UFZ0t1O4HMdYVR40oTYjuJzNoCvjaco+LWNbcOCioTKpto\n"
    "b4PCb/cXCZmXs6WsZSIt0iLVwm3aufkVuEpeqGf5H8CeTcytGAzI3qKQ8PyyWM8F\n"
    "wdCDBTLWP1Tqt4e8EncC5z8ja8hrkqdwVovLCNrr3z3KSMc8rnLfOWidqmR4hIhA\n"
    "Fe4YscD8GddEkI32i02TAG2L1g5+DxvLmncFAUYyUFWbybe5gvOD5ClCAxlIm+/p\n"
    "fq9ILeruu/FJ74ycp3/jNhBjiOxRrqo4NkJPbeaBIIE0sRNw4gpcHmtfXh9elO98\n"
    "mwIDAQAB\n"
    "-----END PUBLIC KEY-----"
)

# Measurement point IDs for forced control (on Res_Inverter device)
MP_CHARGE_OR_DISCHARGE = "PUB_INV_Hossain.ChargeOrDischarge"
MP_FORCED_CHARGE_PWR = "PUB_INV_Hossain.ForcedChargePwr"
MP_FORCED_DISCHARGE_PWR = "PUB_INV_Hossain.ForcedDischargePwr"
MP_FORCED_PERIOD = "PUB_INV_Hossain.ForcedChargeDischagrePeriod"

CONTROL_MEASUREMENT_POINTS = ",".join(
    [
        MP_CHARGE_OR_DISCHARGE,
        MP_FORCED_CHARGE_PWR,
        MP_FORCED_DISCHARGE_PWR,
        MP_FORCED_PERIOD,
    ]
)

CHARGE_OR_DISCHARGE_OPTIONS = {
    0: "Idle",
    1: "Charge",
    2: "Discharge",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def separator(title: str) -> None:
    print(f"\n{'─' * 55}")
    print(f" {title}")
    print("─" * 55)


def encrypt_password(plain: str) -> str:
    """RSA-encrypt the password with PKCS#1 v1.5, return base64 string."""
    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
    if not isinstance(public_key, RSAPublicKey):
        raise TypeError("Expected an RSA public key")
    encrypted = public_key.encrypt(plain.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def make_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE_URL,
        "Referer": (
            f"{BASE_URL}/hossain-fe/index.html"
            f"?appId={APP_ID}&menuCode=DeviceView&categoryId=112&locale=en-US"
            f"&accessToken={token}"
        ),
        "locale": "en-US",
        "Cookie": "locale=en-US",
    }


def get_mp_value(data: dict, mdm_id: str, point: str):
    """Extract a measurement point value from an /asset/detail response."""
    return data.get("data", {}).get(mdm_id, {}).get("measurementPoints", {}).get(point, {}).get("value")


def prompt_int(label: str, default: int, min_val: int, max_val: int) -> int:
    while True:
        raw = input(f"  {label} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"    ⚠️  Must be between {min_val} and {max_val}")
        except ValueError:
            print("    ⚠️  Please enter a whole number")


def prompt_mode(default: int) -> int:
    options_str = ", ".join(f"{k}={v}" for k, v in CHARGE_OR_DISCHARGE_OPTIONS.items())
    while True:
        raw = input(f"  Mode ({options_str}) [{default}={CHARGE_OR_DISCHARGE_OPTIONS[default]}]: ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if val in CHARGE_OR_DISCHARGE_OPTIONS:
                return val
            print(f"    ⚠️  Must be one of: {list(CHARGE_OR_DISCHARGE_OPTIONS.keys())}")
        except ValueError:
            print("    ⚠️  Please enter a number")


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("Univers EMS — forced charge/discharge control test")

    username = input("Username (email): ").strip()
    password = getpass.getpass("Password: ")

    async with aiohttp.ClientSession() as session:
        # ── Step 1: Login ─────────────────────────────────────────────────────
        separator("Step 1: Login")
        ts = int(time.time() * 1000)
        url = f"{LOGIN_URL}?channel=Web&_sid_={ts}&appId={APP_ID}"
        payload = {
            "account": username,
            "keyId": LOGIN_KEY_ID,
            "password": encrypt_password(password),
        }
        async with session.post(url, json=payload) as resp:
            data = await resp.json(content_type=None)

        if data.get("code") not in (0, 200):
            print(f"❌ Login failed: {data.get('message')!r}")
            return

        token = data["data"]["accessToken"]
        org_id = data["data"].get("organizations", [{}])[0].get("id", "N/A")
        print("✅ Login OK (initial token)")
        print(f"   token  : {token[:30]}…")
        print(f"   org_id : {org_id}")

        # ── Step 1b: Session set ──────────────────────────────────────────────
        separator("Step 1b: Session set (upgrade token)")
        ts2 = int(time.time() * 1000)
        session_url = f"{SESSION_URL_BASE}?channel=Web&_sid_={ts2}"
        async with session.post(
            session_url,
            json={"organizationId": org_id},
            headers=make_headers(token),
        ) as resp:
            sdata = await resp.json(content_type=None)

        if sdata.get("code") not in (0, 200):
            print(f"❌ Session set failed: {sdata.get('message')!r}")
            return

        upgraded = sdata.get("data", {}).get("accessToken")
        if upgraded:
            token = upgraded
        print("✅ Session set OK (upgraded token)")
        print(f"   token  : {token[:30]}…")

        # ── Step 2: Discover device IDs from asset list ───────────────────────
        separator("Step 2: Discover device IDs via /asset/list")
        async with session.post(
            ASSET_LIST_URL,
            json={
                "mdmIds": SITE_ASSET_ID,
                "mdmTypes": "Dongle,Smart_Logger,Res_Inverter,Res_Storage,Res_Meter,"
                "Res_WaterHeater,Res_EV_Charger,Res_EV_Connector,Res_WeatherStation",
                "view": "DeviceMgtList",
                "pageNo": 1,
                "pageSize": 500,
            },
            headers=make_headers(token),
        ) as resp:
            list_data = await resp.json(content_type=None)

        if list_data.get("code") not in (0, 200):
            print(f"❌ Asset list failed: {list_data.get('message')!r}")
            return

        inverter_mdm_id = None
        storage_asset_id = None

        for device in list_data.get("data", []):
            mdm_type = device.get("mdmType")
            mdm_id = device.get("mdmId")
            name = device.get("attributes", {}).get("name", "?")
            print(f"   Found: {mdm_type:<20} mdmId={mdm_id}  name={name}")
            if mdm_type == "Res_Inverter":
                inverter_mdm_id = mdm_id
            elif mdm_type == "Res_Storage":
                storage_asset_id = mdm_id

        if not inverter_mdm_id:
            print("❌ Could not find Res_Inverter device in asset list")
            return
        if not storage_asset_id:
            print("❌ Could not find Res_Storage device in asset list")
            return

        print(f"\n✅ Inverter mdmId (for reads) : {inverter_mdm_id}")
        print(f"✅ Storage assetId (for writes): {storage_asset_id}")

        # ── Step 3: Read current forced control state ─────────────────────────
        separator("Step 3: Read current forced control settings")
        async with session.post(
            ASSET_DETAIL_URL,
            json={
                "mdmIds": inverter_mdm_id,
                "measurementPoints": CONTROL_MEASUREMENT_POINTS,
            },
            headers=make_headers(token),
        ) as resp:
            detail_data = await resp.json(content_type=None)

        if detail_data.get("code") not in (0, 200):
            print(f"❌ Asset detail failed: {detail_data.get('message')!r}")
            return

        def read_mp(point):
            return get_mp_value(detail_data, inverter_mdm_id, point)

        cur_mode = read_mp(MP_CHARGE_OR_DISCHARGE)
        cur_charge_pwr = read_mp(MP_FORCED_CHARGE_PWR)
        cur_discharge_pwr = read_mp(MP_FORCED_DISCHARGE_PWR)
        cur_period = read_mp(MP_FORCED_PERIOD)

        if any(v is None for v in [cur_mode, cur_charge_pwr, cur_discharge_pwr, cur_period]):
            print("❌ One or more control measurement points missing from response")
            print(f"   Raw response: {detail_data}")
            return

        cur_mode = int(cur_mode)
        cur_charge_pwr = int(cur_charge_pwr)
        cur_discharge_pwr = int(cur_discharge_pwr)
        cur_period = int(cur_period)

        print("✅ Current values:")
        print(f"   Mode              : {cur_mode} ({CHARGE_OR_DISCHARGE_OPTIONS.get(cur_mode, '?')})")
        print(f"   Forced charge pwr : {cur_charge_pwr} kW")
        print(f"   Forced disch. pwr : {cur_discharge_pwr} kW")
        print(f"   Period            : {cur_period} min")

        # ── Step 4: Prompt for new values ─────────────────────────────────────
        separator("Step 4: Enter new values (press Enter to keep current)")
        new_mode = prompt_mode(cur_mode)
        new_charge_pwr = prompt_int("Forced charge power (kW)", cur_charge_pwr, 0, 100)
        new_discharge_pwr = prompt_int("Forced discharge power (kW)", cur_discharge_pwr, 0, 100)
        new_period = prompt_int("Period (minutes)", cur_period, 1, 1440)

        # Build diff — only include parameters that actually changed.
        # The API rejects "correlation" errors when unrelated power parameters
        # are sent alongside a mismatched mode (e.g. ForcedChargePwr with Discharge).
        # Mirroring the web app behaviour: only send what changed.
        changes = {
            MP_CHARGE_OR_DISCHARGE: (cur_mode, new_mode),
            MP_FORCED_CHARGE_PWR: (cur_charge_pwr, new_charge_pwr),
            MP_FORCED_DISCHARGE_PWR: (cur_discharge_pwr, new_discharge_pwr),
            MP_FORCED_PERIOD: (cur_period, new_period),
        }
        changed_params = {k: v for k, (old, v) in changes.items() if old != v}

        print(f"\n  Parameters that will be sent ({len(changed_params)} changed):")
        if not changed_params:
            print("  No values changed — nothing to send.")
            return
        for cp_id, val in changed_params.items():
            print(f"    {cp_id} = {val}")

        confirm = input("\n  Send these values? [y/N]: ").strip().lower()
        if confirm != "y":
            print("  Aborted — no changes sent.")
            return

        # ── Step 5: Send control command ──────────────────────────────────────
        separator("Step 5: POST to /device/control")
        control_payload = [
            {"assetId": storage_asset_id, "controlPointId": cp_id, "value": val}
            for cp_id, val in changed_params.items()
        ]
        print(f"  Payload: {control_payload}")

        async with session.post(
            CONTROL_URL,
            json=control_payload,
            headers=make_headers(token),
        ) as resp:
            ctrl_data = await resp.json(content_type=None)

        if ctrl_data.get("code") not in (0, 200):
            print(f"❌ Control command failed: {ctrl_data.get('message')!r} (full: {ctrl_data})")
            return

        command_id = ctrl_data.get("data", {}).get("commandId", "?")
        print("✅ Control command accepted")
        print(f"   commandId: {command_id}")

        # ── Step 6: Re-read to confirm ────────────────────────────────────────
        separator("Step 6: Re-read to confirm (allow a few seconds to apply)")
        await asyncio.sleep(3)

        async with session.post(
            ASSET_DETAIL_URL,
            json={
                "mdmIds": inverter_mdm_id,
                "measurementPoints": CONTROL_MEASUREMENT_POINTS,
            },
            headers=make_headers(token),
        ) as resp:
            verify_data = await resp.json(content_type=None)

        def read_verify(point):
            return get_mp_value(verify_data, inverter_mdm_id, point)

        v_mode = read_verify(MP_CHARGE_OR_DISCHARGE)
        v_charge_pwr = read_verify(MP_FORCED_CHARGE_PWR)
        v_discharge_pwr = read_verify(MP_FORCED_DISCHARGE_PWR)
        v_period = read_verify(MP_FORCED_PERIOD)

        print("  Verified values:")
        print(
            f"   Mode              : {v_mode} ({CHARGE_OR_DISCHARGE_OPTIONS.get(int(v_mode) if v_mode is not None else -1, '?')})"
        )
        print(f"   Forced charge pwr : {v_charge_pwr} kW")
        print(f"   Forced disch. pwr : {v_discharge_pwr} kW")
        print(f"   Period            : {v_period} min")

        # Only verify the parameters we actually sent
        verify_map = {
            MP_CHARGE_OR_DISCHARGE: v_mode,
            MP_FORCED_CHARGE_PWR: v_charge_pwr,
            MP_FORCED_DISCHARGE_PWR: v_discharge_pwr,
            MP_FORCED_PERIOD: v_period,
        }
        all_match = all(
            verify_map[cp_id] is not None and int(verify_map[cp_id]) == val for cp_id, val in changed_params.items()
        )

        if all_match:
            separator("All checks passed ✅ — control command confirmed")
        else:
            separator("⚠️  Values may not have applied yet — check the app to confirm")
            print("  (Some inverters apply settings asynchronously — try re-running the read in a few seconds)")


if __name__ == "__main__":
    asyncio.run(main())
