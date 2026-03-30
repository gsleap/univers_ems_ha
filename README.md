# Univers EMS — Home Assistant Integration

A custom Home Assistant integration for the **Univers EMS** solar monitoring app by [iStore Australia](https://istoreaustralia.com.au/). Polls live data from the Envision EnOS cloud platform and exposes solar, battery, and grid sensors directly in Home Assistant.

**⚠️ Important**
This is my own work, making use of public API's and is not associated with, or supported by Univers or iStore. Use at your own risk- it's new and not very well tested!

---

## Sensors

| Entity | Description | Unit | Sign convention |
|---|---|---|---|
| `sensor.univers_ems_solar_site_pv_power` | Solar panel output | kW | Always ≥ 0 |
| `sensor.univers_ems_solar_site_battery_power` | Battery charge/discharge | kW | + = charging, − = discharging |
| `sensor.univers_ems_solar_site_battery_state_of_charge` | Battery level | % | 0–100 |
| `sensor.univers_ems_solar_site_grid_power` | Grid import/export | kW | + = import, − = export |
| `sensor.univers_ems_solar_site_load_power` | House consumption | kW | Always ≥ 0 |
| `sensor.univers_ems_solar_site_generation_power` | Total generation (PV + battery) | kW | Always ≥ 0 |
| `sensor.univers_ems_solar_site_grid_import_power` | Grid import only (derived) | kW | Always ≥ 0 |
| `sensor.univers_ems_solar_site_grid_export_power` | Grid export only (derived) | kW | Always ≥ 0 |
| `sensor.univers_ems_solar_site_battery_charge_power` | Battery charging only (derived) | kW | Always ≥ 0 |
| `sensor.univers_ems_solar_site_battery_discharge_power` | Battery discharging only (derived) | kW | Always ≥ 0 |

The four **derived** sensors split the signed raw values into non-negative halves, which is required for the Home Assistant Energy Dashboard.

---

## Requirements

- Home Assistant 2023.6 or later
- A valid Univers EMS account (the same credentials used to log into the Univers EMS app or portal)
- Your **Asset ID** — an 8-character code identifying your site (e.g. `a1b2c3d4`). See [Finding your Asset ID](#finding-your-asset-id) below.

---

## Installation

### Option A — HACS (recommended)

1. In Home Assistant, go to **HACS → Integrations → Custom Repositories**
2. Add this repository URL and select **Integration** as the category
3. Search for **Univers EMS** and install it
4. Restart Home Assistant

### Option B — Manual

1. Download or clone this repository
2. Copy the `univers_ems/` folder into your HA config directory:
   ```
   config/
   └── custom_components/
       └── univers_ems/
           ├── __init__.py
           ├── api.py
           ├── config_flow.py
           ├── const.py
           ├── coordinator.py
           ├── manifest.json
           ├── sensor.py
           └── strings.json
   ```
3. Restart Home Assistant

---

## Configuration

1. In Home Assistant, go to **Settings → Devices & Services → Add Integration**
2. Search for **Univers EMS**
3. Fill in the form:
   - **Username** — your Univers EMS portal email address
   - **Password** — your Univers EMS portal password
   - **Asset ID** — your 8-character site identifier (see below)
   - **Poll interval** — how often to fetch live data in seconds (default: 60)
4. Click **Submit** — the integration will verify your credentials before saving

---

## Finding your Asset ID

The Asset ID is visible in the URL when you open the Univers EMS web portal:

1. Log into [https://app-portal-eu2.envisioniot.com](https://app-portal-eu2.envisioniot.com)
2. Navigate to your site dashboard
3. Look at the browser URL — it will contain `siteId=XXXXXXXX` where `XXXXXXXX` is your Asset ID

---

## Energy Dashboard Setup

The integration provides instantaneous power sensors (kW). To use them in the Home Assistant **Energy Dashboard**, you need to create **Riemann Sum helper** sensors to accumulate energy (kWh) over time.

### Step 1 — Create Riemann Sum helpers

Go to **Settings → Devices & Services → Helpers → Add Helper → Integrate sensor** and create one helper for each of the following:

| Helper name | Source sensor | Method | Precision |
|---|---|---|---|
| Univers PV Energy | `…pv_power` | Trapezoidal | 3 |
| Univers Grid Import Energy | `…grid_import_power` | Trapezoidal | 3 |
| Univers Grid Export Energy | `…grid_export_power` | Trapezoidal | 3 |
| Univers Load Energy | `…load_power` | Trapezoidal | 3 |
| Univers Battery Charge Energy | `…battery_charge_power` | Trapezoidal | 3 |
| Univers Battery Discharge Energy | `…battery_discharge_power` | Trapezoidal | 3 |

### Step 2 — Configure the Energy Dashboard

Go to **Settings → Energy** and assign:

| Energy Dashboard field | Helper to use |
|---|---|
| ⚡ Solar production | Univers PV Energy |
| 🔌 Grid consumption | Univers Grid Import Energy |
| 🔄 Return to grid | Univers Grid Export Energy |
| 🔋 Battery charged from | Univers Battery Charge Energy |
| 🔋 Battery discharged to | Univers Battery Discharge Energy |

> **Note:** Riemann Sum helpers accumulate from the moment they are created. Historical data prior to setup will not be available.

---

## Test Scripts

Two standalone test scripts are included to verify connectivity and credentials outside of Home Assistant.

### Prerequisites

```bash
pip install aiohttp cryptography
```

### Environment variable

Both scripts require your Asset ID to be set as an environment variable:

```bash
export UNIVERS_EMS_ASSET_ID=your_asset_id_here
```

Or inline per run (see examples below). The Asset ID is kept out of the scripts to avoid accidentally committing it to source control.

### `test_univers_ems.py` — Basic API sanity test

Tests the raw API directly: login, session upgrade, and live data fetch. Useful for quickly verifying credentials and connectivity without any component code involved.

```bash
UNIVERS_EMS_ASSET_ID=your_asset_id python test_univers_ems.py
```

Expected output:
```
✅  Login OK (initial token)
✅  Session set OK (upgraded token)
✅  Asset data received

── Step 4: Raw measurement points ──────────────────────
    PV Power                     0.0 kW   [2026-03-30 22:31:34]
    Battery Power               -0.403 kW [2026-03-30 22:31:34]
    Battery SOC                 62.0 %    [2026-03-30 22:30:46]
    Grid Power                   0.006 kW [2026-03-30 22:31:34]
    Load Power                   0.397 kW [2026-03-30 22:31:34]
    Generation Power             0.403 kW [2026-03-30 22:31:34]

── Step 5: Derived sensors ─────────────────────────────
    Grid Import Power            0.006 kW
    Grid Export Power            0.0 kW
    Battery Charge Power         0.0 kW
    Battery Discharge Power      0.403 kW
```

### `test_univers_ems_integration.py` — Component integration test

Imports and runs the **actual `api.py` component code** exactly as Home Assistant would. This is the definitive pre-install check — if this passes, the HA integration will work.

```bash
UNIVERS_EMS_ASSET_ID=your_asset_id python test_univers_ems_integration.py
```

This test:
1. Instantiates `UniversEMSClient` exactly as `__init__.py` does
2. Calls `async_login()` exactly as the coordinator's first refresh does
3. Calls `async_get_data()` exactly as each 60-second coordinator tick does
4. Performs a second poll to verify token reuse works correctly

---

## Troubleshooting

**`Auth exception` on data fetch**
The session upgrade step after login is required. Ensure you are using the latest version of this integration — earlier versions did not include the two-step login flow.

**`Login failed: Fail to decrypt`**
The password is RSA-encrypted before sending. This error means the encryption key mismatch. Ensure you have not modified `const.py`.

**Sensors show `unavailable`**
Check the HA logs for errors from `univers_ems`. Common causes:
- Incorrect credentials
- The Univers EMS portal is unreachable (cloud dependency)
- Token expired and re-login failed

**Wrong sign on battery or grid sensors**
The sign conventions follow the raw API values. If your system reports them inverted, please open an issue with details of your hardware configuration.

---

## Technical Notes

The integration authenticates against Envision's EnOS platform hosted at `app-portal-eu2.envisioniot.com`. Authentication requires a two-step flow:

1. `POST /app-portal/web/v1/login` — initial login with RSA-encrypted password
2. `POST /app-portal/web/v1/session/set` — session upgrade that returns the token with full API permissions

The token is then used as a `Bearer` token for all subsequent data requests. On token expiry (HTTP 401 or API code 88202), the integration automatically re-authenticates.

Data is fetched from:
```
POST /hossain-bff/monitor/v1.0/asset/detail
```

Poll interval defaults to 60 seconds, configurable at setup time.
