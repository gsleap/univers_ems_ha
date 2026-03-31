"""
Standalone sanity test for Univers EMS API.
Requires: pip install aiohttp cryptography

Usage:
    UNIVERS_EMS_ASSET_ID=7g3Co6Bp python test_univers_ems.py
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
LOGIN_URL = f"{BASE_URL}/app-portal/web/v1/login"
DETAIL_URL = f"{BASE_URL}/hossain-bff/monitor/v1.0/asset/detail"
LOGIN_KEY_ID = "FIXED_KEY_ID"

ASSET_ID = os.environ.get("UNIVERS_EMS_ASSET_ID", "").strip()
if not ASSET_ID:
    print("❌  UNIVERS_EMS_ASSET_ID environment variable not set.")
    print("    Usage: UNIVERS_EMS_ASSET_ID=7g3Co6Bp python test_univers_ems.py")
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


def encrypt_password(plain: str) -> str:
    """RSA-encrypt the password with PKCS#1 v1.5, return base64 string."""
    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
    if not isinstance(public_key, RSAPublicKey):
        raise TypeError("Expected an RSA public key")
    encrypted = public_key.encrypt(plain.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


DETAIL_ATTRIBUTES = "gmtAmount,batteryStorageAmount,strInvAmount,powerDirection"
DETAIL_POINTS = (
    "PUB_SITE.PVOutputPower,PUB_SITE.METERActivePW,PUB_SITE.BSActivePW,ConsPower,SITE.GenActivePW,PUB_SITE.Soc"
)

# Derived sensor logic (mirrors sensor.py)
# Grid: positive = export, negative = import
DERIVED = {
    "Grid Import Power": ("PUB_SITE.METERActivePW", lambda v: max(-v, 0)),
    "Grid Export Power": ("PUB_SITE.METERActivePW", lambda v: max(v, 0)),
    "Battery Charge Power": ("PUB_SITE.BSActivePW", lambda v: max(v, 0)),
    "Battery Discharge Power": ("PUB_SITE.BSActivePW", lambda v: max(-v, 0)),
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def separator(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print("─" * 50)


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("Univers EMS — standalone sanity test")

    username = input("Username (email): ").strip()
    password = getpass.getpass("Password: ")

    async with aiohttp.ClientSession() as session:
        # ── Step 1: Login ─────────────────────────────────────────────────────
        separator("Step 1: Login")
        APP_ID = "6508dd96-c72f-4c75-85d3-11c6e1380f75"
        ts = int(time.time() * 1000)
        url = f"{LOGIN_URL}?channel=Web&_sid_={ts}&appId={APP_ID}"
        payload = {"account": username, "keyId": LOGIN_KEY_ID, "password": encrypt_password(password)}

        async with session.post(url, json=payload) as resp:
            data = await resp.json(content_type=None)

        if data.get("code") not in (0, 200):
            print(f"❌  Login failed: {data.get('message')!r}  (full: {data})")
            return

        token = data["data"]["accessToken"]
        org_id = data["data"].get("organizations", [{}])[0].get("id", "N/A")
        user_id = data["data"].get("user", {}).get("id", "N/A")

        print("✅  Login OK (initial token)")
        print(f"    token   : {token[:30]}…")
        print(f"    orgId   : {org_id}")
        print(f"    userId  : {user_id}")

        # ── Step 1b: Session set (upgrades token) ─────────────────────────────
        separator("Step 1b: Session set")
        ts2 = int(time.time() * 1000)
        session_url = f"{BASE_URL}/app-portal/web/v1/session/set?channel=Web&_sid_={ts2}"
        session_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "locale": "en-US",
        }
        session_payload = {"organizationId": org_id}

        async with session.post(session_url, json=session_payload, headers=session_headers) as resp:
            sdata = await resp.json(content_type=None)

        if sdata.get("code") not in (0, 200):
            print(f"❌  Session set failed: {sdata.get('message')!r}")
            return

        upgraded_token = sdata.get("data", {}).get("accessToken")
        if not upgraded_token:
            print("⚠️   No new token in session/set response, keeping original")
        else:
            token = upgraded_token
            print("✅  Session set OK (upgraded token)")
            print(f"    token   : {token[:30]}…")

        # ── Step 2: Fetch asset detail ────────────────────────────────────────
        separator("Step 2: Fetch asset detail")
        referer = (
            f"https://app-portal-eu2.envisioniot.com/hossain-fe/index.html"
            f"?appId={APP_ID}&menuCode=SiteView&categoryId=112&locale=en-US"
            f"&accessToken={token}&state=siteId%3D{ASSET_ID}%26view%3Dsite"
            f"%26appId%3D{APP_ID}&__f__=__aim__"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app-portal-eu2.envisioniot.com",
            "Referer": referer,
            "locale": "en-US",
            "Cookie": "locale=en-US",
        }
        body = {
            "mdmIds": ASSET_ID,
            "attributes": DETAIL_ATTRIBUTES,
            "measurementPoints": DETAIL_POINTS,
        }

        async with session.post(DETAIL_URL, json=body, headers=headers) as resp:
            print(f"    Request URL : {resp.url}")
            raw = await resp.text()
            print(f"    HTTP status : {resp.status}")
            print(f"    Raw response: {raw[:500]}")
            detail = await resp.json(content_type=None)

        if detail.get("code") not in (0, 200):
            print(f"❌  Detail fetch failed: {detail.get('message')!r}  (full code: {detail.get('code')})")
            return

        asset = detail["data"].get(ASSET_ID)
        if not asset:
            print(f"❌  Asset '{ASSET_ID}' not found in response")
            return

        print("✅  Asset data received")

        # ── Step 3: Print attributes ──────────────────────────────────────────
        separator("Step 3: Site attributes")
        for k, v in asset.get("attributes", {}).items():
            print(f"    {k:<30} {v}")

        # ── Step 4: Print raw measurement points ──────────────────────────────
        separator("Step 4: Raw measurement points")
        mp = asset.get("measurementPoints", {})
        label_map = {
            "PUB_SITE.PVOutputPower": "PV Power",
            "PUB_SITE.BSActivePW": "Battery Power  (+ charge / - discharge)",
            "PUB_SITE.Soc": "Battery SOC",
            "PUB_SITE.METERActivePW": "Grid Power     (+ import / - export)",
            "ConsPower": "Load Power",
            "SITE.GenActivePW": "Generation Power",
        }
        for point_id, label in label_map.items():
            entry = mp.get(point_id)
            if entry:
                val = entry.get("value")
                ts_local = entry.get("localtime", "")
                unit = "%" if point_id == "PUB_SITE.Soc" else "kW"
                print(f"    {label:<42} {val:>8} {unit}   [{ts_local}]")
            else:
                print(f"    {label:<42} (not in response)")

        # ── Step 5: Derived sensors ───────────────────────────────────────────
        separator("Step 5: Derived sensors (Energy dashboard)")
        for name, (source_point, fn) in DERIVED.items():
            raw = mp.get(source_point, {}).get("value")
            if raw is not None:
                derived_val = round(fn(float(raw)), 3)
                print(f"    {name:<42} {derived_val:>8} kW")
            else:
                print(f"    {name:<42} (source not available)")

        separator("Done — all checks passed ✅")


if __name__ == "__main__":
    asyncio.run(main())
