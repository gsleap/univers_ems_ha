# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Greg Sleap

"""Constants for the Univers EMS integration."""

DOMAIN = "univers_ems"
MANUFACTURER = "iStore / Envision EnOS"

# API endpoints
BASE_URL = "https://app-portal-eu2.envisioniot.com"
LOGIN_URL = f"{BASE_URL}/app-portal/web/v1/login"
SESSION_URL = f"{BASE_URL}/app-portal/web/v1/session/set"
ASSET_LIST_URL = f"{BASE_URL}/hossain-bff/monitor/v1.0/asset/list"
DETAIL_URL = f"{BASE_URL}/hossain-bff/monitor/v1.0/asset/detail"
CONTROL_URL = f"{BASE_URL}/hossain-bff/connect/v1.0/device/control"
REFERER_BASE = f"{BASE_URL}/hossain-fe/index.html"

# App ID (from portal URL)
APP_ID = "6508dd96-c72f-4c75-85d3-11c6e1380f75"

# Fixed login key (as captured from portal)
LOGIN_KEY_ID = "FIXED_KEY_ID"

# RSA public key for password encryption (PKCS#1 v1.5)
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

# Config entry keys
CONF_ASSET_ID = "asset_id"
CONF_INVERTER_ASSET_ID = "inverter_asset_id"
CONF_STORAGE_ASSET_ID = "storage_asset_id"

# Defaults
DEFAULT_SCAN_INTERVAL = 60  # seconds

# Measurement point IDs — site-level (existing)
MP_PV_POWER = "PUB_SITE.PVOutputPower"
MP_BATTERY_POWER = "PUB_SITE.BSActivePW"
MP_BATTERY_SOC = "PUB_SITE.Soc"
MP_GRID_POWER = "PUB_SITE.METERActivePW"
MP_LOAD_POWER = "ConsPower"
MP_GEN_POWER = "SITE.GenActivePW"

# Measurement point IDs — inverter-level control (new)
MP_CHARGE_OR_DISCHARGE = "PUB_INV_Hossain.ChargeOrDischarge"
MP_FORCED_CHARGE_PWR = "PUB_INV_Hossain.ForcedChargePwr"
MP_FORCED_DISCHARGE_PWR = "PUB_INV_Hossain.ForcedDischargePwr"
MP_FORCED_PERIOD = "PUB_INV_Hossain.ForcedChargeDischagrePeriod"

CONTROL_MEASUREMENT_POINTS = ",".join([
    MP_CHARGE_OR_DISCHARGE,
    MP_FORCED_CHARGE_PWR,
    MP_FORCED_DISCHARGE_PWR,
    MP_FORCED_PERIOD,
])

# ChargeOrDischarge mode values
CHARGE_OR_DISCHARGE_IDLE = 0
CHARGE_OR_DISCHARGE_CHARGE = 1
CHARGE_OR_DISCHARGE_DISCHARGE = 2

CHARGE_OR_DISCHARGE_OPTIONS: dict[int, str] = {
    CHARGE_OR_DISCHARGE_IDLE: "Idle",
    CHARGE_OR_DISCHARGE_CHARGE: "Charge",
    CHARGE_OR_DISCHARGE_DISCHARGE: "Discharge",
}

# Forced power limits (kW)
FORCED_POWER_MIN = 0
FORCED_POWER_MAX = 20

# Forced period limits (minutes)
FORCED_PERIOD_MIN = 1
FORCED_PERIOD_MAX = 1440

# mdmTypes to request when discovering child devices
ASSET_LIST_MDM_TYPES = (
    "Dongle,Smart_Logger,Res_Inverter,Res_Storage,Res_Meter,"
    "Res_WaterHeater,Res_EV_Charger,Res_EV_Connector,Res_WeatherStation"
)

# Attributes to request alongside measurement points
DETAIL_ATTRIBUTES = "gmtAmount,batteryStorageAmount,strInvAmount,powerDirection"

DETAIL_POINTS = ",".join(
    [
        MP_PV_POWER,
        MP_GRID_POWER,
        MP_BATTERY_POWER,
        MP_LOAD_POWER,
        MP_GEN_POWER,
        MP_BATTERY_SOC,
        "PUB_SITE.EVChargingPW",
    ]
)
