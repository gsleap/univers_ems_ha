# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap

"""API client for Univers EMS / EnOS platform."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from .const import (
    LOGIN_URL,
    SESSION_URL,
    ASSET_LIST_URL,
    DETAIL_URL,
    CONTROL_URL,
    REFERER_BASE,
    LOGIN_KEY_ID,
    APP_ID,
    PUBLIC_KEY_PEM,
    DETAIL_ATTRIBUTES,
    DETAIL_POINTS,
    CONTROL_MEASUREMENT_POINTS,
    ASSET_LIST_MDM_TYPES,
)

_LOGGER = logging.getLogger(__name__)


def _encrypt_password(plain: str) -> str:
    """RSA-encrypt the password with PKCS#1 v1.5, return base64 string."""
    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
    if not isinstance(public_key, RSAPublicKey):
        raise TypeError("Expected an RSA public key")
    encrypted = public_key.encrypt(plain.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


class UniversEMSAuthError(Exception):
    """Raised when login fails."""


class UniversEMSError(Exception):
    """Raised on general API errors."""


class UniversEMSClient:
    """Async API client for the Univers EMS portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        asset_id: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._asset_id = asset_id
        self._token: str | None = None
        self._org_id: str | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def async_login(self) -> None:
        """Log in, then call session/set to obtain the upgraded token."""
        # Step 1: initial login
        timestamp = int(time.time() * 1000)
        url = f"{LOGIN_URL}?channel=Web&_sid_={timestamp}"
        payload = {
            "account": self._username,
            "keyId": LOGIN_KEY_ID,
            "password": _encrypt_password(self._password),
        }

        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    raise UniversEMSAuthError(f"Login HTTP error {resp.status}")
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise UniversEMSError(f"Login request failed: {err}") from err

        if data.get("code") not in (0, 200):
            raise UniversEMSAuthError(f"Login rejected: {data.get('message', 'unknown error')}")

        initial_token = data.get("data", {}).get("accessToken")
        if not initial_token:
            raise UniversEMSAuthError("Login succeeded but no accessToken returned")

        org_id = data.get("data", {}).get("organizations", [{}])[0].get("id")
        if not org_id:
            raise UniversEMSAuthError("Login succeeded but no organizationId returned")

        self._org_id = org_id

        # Step 2: session/set — upgrades the token with app permissions
        ts2 = int(time.time() * 1000)
        session_url = f"{SESSION_URL}?channel=Web&_sid_={ts2}"
        session_headers = {
            "Authorization": f"Bearer {initial_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "locale": "en-US",
        }

        try:
            async with self._session.post(
                session_url,
                json={"organizationId": org_id},
                headers=session_headers,
            ) as resp:
                sdata = await resp.json()
        except aiohttp.ClientError as err:
            raise UniversEMSError(f"Session set request failed: {err}") from err

        if sdata.get("code") not in (0, 200):
            raise UniversEMSAuthError(f"Session set rejected: {sdata.get('message', 'unknown error')}")

        upgraded_token = sdata.get("data", {}).get("accessToken", initial_token)
        self._token = upgraded_token
        _LOGGER.debug("Univers EMS login + session/set successful, upgraded token acquired")

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    async def async_discover_devices(self) -> dict[str, str]:
        """Call /asset/list and return discovered mdmIds by type.

        Returns a dict with keys 'inverter_asset_id' and 'storage_asset_id'.
        Raises UniversEMSError if either device type is not found.
        """
        if not self._token:
            await self.async_login()

        headers = self._make_headers()
        body = {
            "mdmIds": self._asset_id,
            "mdmTypes": ASSET_LIST_MDM_TYPES,
            "view": "DeviceMgtList",
            "pageNo": 1,
            "pageSize": 500,
        }

        try:
            async with self._session.post(ASSET_LIST_URL, json=body, headers=headers) as resp:
                if resp.status != 200:
                    raise UniversEMSError(f"Asset list HTTP error {resp.status}")
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise UniversEMSError(f"Asset list request failed: {err}") from err

        if data.get("code") not in (0, 200):
            raise UniversEMSError(f"Asset list API error: {data.get('message', 'unknown')}")

        inverter_asset_id: str | None = None
        storage_asset_id: str | None = None

        for device in data.get("data", []):
            mdm_type = device.get("mdmType")
            mdm_id = device.get("mdmId")
            if mdm_type == "Res_Inverter":
                inverter_asset_id = mdm_id
            elif mdm_type == "Res_Storage":
                storage_asset_id = mdm_id

        if not inverter_asset_id:
            raise UniversEMSError("No Res_Inverter device found under site asset")
        if not storage_asset_id:
            raise UniversEMSError("No Res_Storage device found under site asset")

        _LOGGER.debug(
            "Discovered inverter_asset_id=%s, storage_asset_id=%s",
            inverter_asset_id,
            storage_asset_id,
        )
        return {
            "inverter_asset_id": inverter_asset_id,
            "storage_asset_id": storage_asset_id,
        }

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch latest measurement points; re-login on 401."""
        if not self._token:
            await self.async_login()

        result = await self._fetch_detail()

        # Retry once on auth failure
        if result is None:
            _LOGGER.debug("Token expired, re-authenticating")
            await self.async_login()
            result = await self._fetch_detail()

        if result is None:
            raise UniversEMSError("Failed to fetch data after re-login")

        return result

    async def async_get_control_data(self, inverter_asset_id: str) -> dict[str, Any]:
        """Fetch current forced control measurement points from the inverter device."""
        if not self._token:
            await self.async_login()

        result = await self._fetch_control_detail(inverter_asset_id)

        if result is None:
            _LOGGER.debug("Token expired during control fetch, re-authenticating")
            await self.async_login()
            result = await self._fetch_control_detail(inverter_asset_id)

        if result is None:
            raise UniversEMSError("Failed to fetch control data after re-login")

        return result

    async def _fetch_detail(self) -> dict[str, Any] | None:
        """POST to asset detail endpoint. Returns parsed data or None on auth error."""
        referer = (
            f"{REFERER_BASE}?appId={APP_ID}&menuCode=SiteView&locale=en-US"
            f"&accessToken={self._token}&state=siteId%3D{self._asset_id}"
            f"%26view%3Dsite%26appId%3D{APP_ID}&__f__=__aim__"
        )
        headers = self._make_headers(referer=referer)
        body = {
            "mdmIds": self._asset_id,
            "attributes": DETAIL_ATTRIBUTES,
            "measurementPoints": DETAIL_POINTS,
        }

        try:
            async with self._session.post(DETAIL_URL, json=body, headers=headers) as resp:
                if resp.status == 401:
                    self._token = None
                    return None
                if resp.status != 200:
                    raise UniversEMSError(f"Data fetch HTTP error {resp.status}")
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise UniversEMSError(f"Data fetch request failed: {err}") from err

        if data.get("code") not in (0, 200):
            if data.get("code") == 88202:
                self._token = None
                return None
            raise UniversEMSError(f"API error: {data.get('message', 'unknown')}")

        asset_data = data.get("data", {}).get(self._asset_id)
        if not asset_data:
            raise UniversEMSError(f"Asset ID '{self._asset_id}' not found in response")

        return asset_data

    async def _fetch_control_detail(self, inverter_asset_id: str) -> dict[str, Any] | None:
        """Fetch control measurement points from the inverter mdmId."""
        headers = self._make_headers()
        body = {
            "mdmIds": inverter_asset_id,
            "measurementPoints": CONTROL_MEASUREMENT_POINTS,
        }

        try:
            async with self._session.post(DETAIL_URL, json=body, headers=headers) as resp:
                if resp.status == 401:
                    self._token = None
                    return None
                if resp.status != 200:
                    raise UniversEMSError(f"Control fetch HTTP error {resp.status}")
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise UniversEMSError(f"Control fetch request failed: {err}") from err

        if data.get("code") not in (0, 200):
            if data.get("code") == 88202:
                self._token = None
                return None
            raise UniversEMSError(f"Control fetch API error: {data.get('message', 'unknown')}")

        asset_data = data.get("data", {}).get(inverter_asset_id)
        if not asset_data:
            raise UniversEMSError(f"Inverter asset ID '{inverter_asset_id}' not found in control response")

        return asset_data

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    async def async_send_control(
        self,
        storage_asset_id: str,
        changes: dict[str, int],
    ) -> str:
        """POST changed control parameters to /device/control.

        Args:
            storage_asset_id: The Res_Storage mdmId (write target).
            changes: Dict of {controlPointId: new_value} — only changed values.

        Returns:
            The commandId string from the API response.

        Raises:
            UniversEMSError on API failure.
        """
        if not changes:
            raise UniversEMSError("async_send_control called with no changes")

        if not self._token:
            await self.async_login()

        payload = [
            {"assetId": storage_asset_id, "controlPointId": cp_id, "value": value}
            for cp_id, value in changes.items()
        ]

        headers = self._make_headers()

        try:
            async with self._session.post(CONTROL_URL, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    self._token = None
                    raise UniversEMSAuthError("Control command rejected: token expired, please retry")
                if resp.status != 200:
                    raise UniversEMSError(f"Control command HTTP error {resp.status}")
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise UniversEMSError(f"Control command request failed: {err}") from err

        if data.get("code") not in (0, 200):
            raise UniversEMSError(
                f"Control command rejected by API: {data.get('message', 'unknown')} "
                f"(code {data.get('code')})"
            )

        command_id: str = data.get("data", {}).get("commandId", "unknown")
        _LOGGER.debug("Control command accepted, commandId=%s", command_id)
        return command_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_headers(self, referer: str | None = None) -> dict[str, str]:
        """Build standard API request headers."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app-portal-eu2.envisioniot.com",
            "Referer": referer or REFERER_BASE,
            "locale": "en-US",
            "Cookie": "locale=en-US",
        }
