# Univers EMS — Home Assistant Integration

A custom Home Assistant integration for the **Univers EMS** solar monitoring app by [iStore Australia](https://istoreaustralia.com.au/). Polls live data from the Envision EnOS cloud platform and exposes solar, battery, and grid sensors directly in Home Assistant.

**⚠️ Important**
This is my own work, making use of public API's and is not associated with, or supported by Univers or iStore. Use at your own risk- it's new and not very well tested!

---

## Sensors

| Entity | Description | Unit | Sign convention |
| --- | --- | --- | --- |
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

## Forced Charge/Discharge Control (v0.0.5+)

In addition to monitoring, the integration can control the battery's forced charge/discharge behaviour — the same settings available in the Univers EMS app under **Parameter Setting → Forced Charge/Discharge**.

### Control entities

| Entity | Type | Description | Range |
| --- | --- | --- | --- |
| `select.univers_ems_solar_site_forced_mode` | Select | Operating mode | Idle / Charge / Discharge |
| `number.univers_ems_solar_site_forced_charge_power` | Number | Forced charge rate | 0–20 kW |
| `number.univers_ems_solar_site_forced_discharge_power` | Number | Forced discharge rate | 0–20 kW |
| `number.univers_ems_solar_site_forced_charge_discharge_period` | Number | Duration | 1–1440 min |

### How it works

The control entities use a **stage-then-commit** pattern, mirroring how the Univers EMS web app works:

1. Set the select and/or number entities to the desired values in HA
2. Call the `univers_ems.send_forced_control` service to send the changes to the inverter

The service always sends the **full set of parameters** required for the selected mode — it does not diff against current state. This ensures the inverter always receives a complete, consistent command regardless of polling timing.

The parameters sent depend on the selected mode:

| Mode | Parameters sent |
| --- | --- |
| **Idle** | `ChargeOrDischarge = 0` |
| **Charge** | `ChargeOrDischarge = 1`, `SettingMode = 0` (Duration), `ForcedChargePwr`, `ForcedChargeDischagrePeriod` |
| **Discharge** | `ChargeOrDischarge = 2`, `SettingMode = 0` (Duration), `ForcedDischargePwr`, `ForcedChargeDischagrePeriod` |

If no mode is staged or polled, the service defaults to **Idle**. If no power or period value is set, it defaults to **0**.

After a successful send, the integration triggers an immediate coordinator refresh to confirm the new state from the API.

### Calling the service

In **Developer Tools → Services**, call:

```yaml
service: univers_ems.send_forced_control
```

No parameters are required — the service reads staged values from the control entities automatically.

### Automation example — daily grid export

This example sets the battery to discharge at 7 kW for a calculated duration every weekday at 5:59 PM, targeting 50% SOC by 8 PM (assuming a 30 kWh battery):

```yaml
alias: "Battery discharge at peak tariff"
description: >
  At 5:59 PM, calculate how long to discharge at 7 kW to reach 50% SOC
  by 8 PM, then send the control command.
trigger:
  - platform: time
    at: "17:59:00"
variables:
  soc: >
    {{ states('sensor.univers_ems_solar_site_battery_state_of_charge') | float(0) }}
  available_kwh: >
    {{ ((soc - 50) / 100) * 30 }}
  duration_minutes: >
    {{ [((available_kwh / 7) * 60) | round(0) | int, 120] | min }}
condition:
  - condition: template
    value_template: "{{ soc > 50 and duration_minutes >= 10 }}"
action:
  - service: select.select_option
    target:
      entity_id: select.univers_ems_solar_site_forced_mode
    data:
      option: Discharge
  - service: number.set_value
    target:
      entity_id: number.univers_ems_solar_site_forced_discharge_power
    data:
      value: 7
  - service: number.set_value
    target:
      entity_id: number.univers_ems_solar_site_forced_charge_discharge_period
    data:
      value: "{{ duration_minutes }}"
  - service: univers_ems.send_forced_control
  - service: notify.persistent_notification
    data:
      title: "Battery discharge started"
      message: >
        SOC: {{ soc }}% — discharging at 7 kW for {{ duration_minutes }} minutes
        ({{ available_kwh | round(1) }} kWh available above 50%)
```

### Automation example — daily AC charge

This example charges the battery from AC at 10 kW every day from 11 AM to 2 PM:

```yaml
alias: "Battery charge from AC 11am to 2pm"
description: "Every day at 11am, charge battery from AC until 2pm"
trigger:
  - platform: time
    at: "11:00:00"
action:
  - service: select.select_option
    target:
      entity_id: select.univers_ems_solar_site_forced_mode
    data:
      option: Charge
  - service: number.set_value
    target:
      entity_id: number.univers_ems_solar_site_forced_charge_power
    data:
      value: 10
  - service: number.set_value
    target:
      entity_id: number.univers_ems_solar_site_forced_charge_discharge_period
    data:
      value: 180
  - service: univers_ems.send_forced_control
  - service: notify.persistent_notification
    data:
      title: "Battery charging started"
      message: "Charging at 10 kW for 180 minutes (until 2pm)"
```

### Staging and pending state

Each control entity exposes three extra state attributes useful for dashboards and debugging:

| Attribute | Description |
| --- | --- |
| `polled_value` | Last value confirmed by the API |
| `staged_value` | Value set locally but not yet sent |
| `pending_send` | `true` if a staged value is waiting to be committed |

Staged values are cleared automatically on the next coordinator poll.

---

## Requirements

* Home Assistant 2023.6 or later
* A valid Univers EMS account (the same credentials used to log into the Univers EMS app or portal)
* Your **Asset ID** — an 8-character code identifying your site (e.g. `a1b2c3d4`). See [Finding your Asset ID](#finding-your-asset-id) below.

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
           ├── number.py
           ├── select.py
           ├── sensor.py
           ├── services.yaml
           └── strings.json
   ```
3. Restart Home Assistant

> **Note for users upgrading from v0.0.4:** The integration now auto-discovers your inverter and battery device IDs during setup. You will need to **remove and re-add the integration** after upgrading to v0.0.5 — existing config entries will not have the required device IDs stored.

---

## Configuration

1. In Home Assistant, go to **Settings → Devices & Services → Add Integration**
2. Search for **Univers EMS**
3. Fill in the form:
   * **Username** — your Univers EMS portal email address
   * **Password** — your Univers EMS portal password
   * **Asset ID** — your 8-character site identifier (see below)
   * **Poll interval** — how often to fetch live data in seconds (default: 60)
4. Click **Submit** — the integration will verify your credentials and auto-discover your inverter and battery device IDs before saving

### Changing the poll interval after setup

Go to **Settings → Devices & Services → Univers EMS → Configure** to change the poll interval without removing and re-adding the integration.

---

## Finding your Asset ID

The Asset ID is visible in the URL when you open the Univers EMS web portal:

1. Log into <https://app-portal-eu2.envisioniot.com>
2. Navigate to your site dashboard
3. Look at the browser URL — it will contain `siteId=XXXXXXXX` where `XXXXXXXX` is your Asset ID

---

## Energy Dashboard Setup

The integration provides instantaneous power sensors (kW). To use them in the Home Assistant **Energy Dashboard**, you need to create **Riemann Sum helper** sensors to accumulate energy (kWh) over time, and set the correct device class via `customize`.

### Step 1 — Add to configuration.yaml

```yaml
homeassistant:
  customize:
    sensor.univers_grid_import_energy:
      state_class: total_increasing
      device_class: energy
    sensor.univers_grid_export_energy:
      state_class: total_increasing
      device_class: energy
    sensor.univers_pv_energy:
      state_class: total_increasing
      device_class: energy
    sensor.univers_load_energy:
      state_class: total_increasing
      device_class: energy
    sensor.univers_battery_charge_energy:
      state_class: total_increasing
      device_class: energy
    sensor.univers_battery_discharge_energy:
      state_class: total_increasing
      device_class: energy

sensor:
  - platform: integration
    source: sensor.univers_ems_solar_site_pv_power
    name: Univers PV Energy
    unique_id: univers_pv_energy
    method: trapezoidal
    unit_prefix: k
    round: 3

  - platform: integration
    source: sensor.univers_ems_solar_site_grid_import_power
    name: Univers Grid Import Energy
    unique_id: univers_grid_import_energy
    method: trapezoidal
    unit_prefix: k
    round: 3

  - platform: integration
    source: sensor.univers_ems_solar_site_grid_export_power
    name: Univers Grid Export Energy
    unique_id: univers_grid_export_energy
    method: trapezoidal
    unit_prefix: k
    round: 3

  - platform: integration
    source: sensor.univers_ems_solar_site_load_power
    name: Univers Load Energy
    unique_id: univers_load_energy
    method: trapezoidal
    unit_prefix: k
    round: 3

  - platform: integration
    source: sensor.univers_ems_solar_site_battery_charge_power
    name: Univers Battery Charge Energy
    unique_id: univers_battery_charge_energy
    method: trapezoidal
    unit_prefix: k
    round: 3

  - platform: integration
    source: sensor.univers_ems_solar_site_battery_discharge_power
    name: Univers Battery Discharge Energy
    unique_id: univers_battery_discharge_energy
    method: trapezoidal
    unit_prefix: k
    round: 3

utility_meter:
  univers_pv_energy_daily:
    source: sensor.univers_pv_energy
    name: Univers PV Energy Daily
    cycle: daily
    unique_id: univers_pv_energy_daily

  univers_grid_import_energy_daily:
    source: sensor.univers_grid_import_energy
    name: Univers Grid Import Energy Daily
    cycle: daily
    unique_id: univers_grid_import_energy_daily

  univers_grid_export_energy_daily:
    source: sensor.univers_grid_export_energy
    name: Univers Grid Export Energy Daily
    cycle: daily
    unique_id: univers_grid_export_energy_daily

  univers_load_energy_daily:
    source: sensor.univers_load_energy
    name: Univers Load Energy Daily
    cycle: daily
    unique_id: univers_load_energy_daily

  univers_battery_charge_energy_daily:
    source: sensor.univers_battery_charge_energy
    name: Univers Battery Charge Energy Daily
    cycle: daily
    unique_id: univers_battery_charge_energy_daily

  univers_battery_discharge_energy_daily:
    source: sensor.univers_battery_discharge_energy
    name: Univers Battery Discharge Energy Daily
    cycle: daily
    unique_id: univers_battery_discharge_energy_daily
```

### Step 2 — Configure the Energy Dashboard

Go to **Settings → Energy** and assign:

| Energy Dashboard field | Sensor to use |
| --- | --- |
| ⚡ Solar production | `sensor.univers_pv_energy` |
| 🔌 Grid consumption | `sensor.univers_grid_import_energy` |
| 🔄 Return to grid | `sensor.univers_grid_export_energy` |
| 🔋 Battery charged from | `sensor.univers_battery_charge_energy` |
| 🔋 Battery discharged to | `sensor.univers_battery_discharge_energy` |

> **Note:** Riemann Sum helpers accumulate from the moment they are created. Historical data prior to setup will not be available.

---

## Test Scripts

Three standalone test scripts are included to verify connectivity outside of Home Assistant.

### Prerequisites

```
pip install aiohttp cryptography
```

### Environment variable

All scripts require your Asset ID to be set as an environment variable:

```
export UNIVERS_EMS_ASSET_ID=your_asset_id_here
```

### `test_univers_ems.py` — Basic API sanity test

Tests the raw API directly: login, session upgrade, and live data fetch.

```
UNIVERS_EMS_ASSET_ID=your_asset_id python test_univers_ems.py
```

### `test_ha_univers_ems.py` — Component integration test

Imports and runs the actual `api.py` component code exactly as Home Assistant would. If this passes, the HA integration will work.

```
UNIVERS_EMS_ASSET_ID=your_asset_id python test_ha_univers_ems.py
```

### `test_univers_ems_control.py` — Forced control test

Interactively tests the forced charge/discharge control API: discovers device IDs, reads current settings, prompts for new values (defaulting to current), and sends changes to the inverter.

```
UNIVERS_EMS_ASSET_ID=your_asset_id python test_univers_ems_control.py
```

---

## Troubleshooting

**`Auth exception` on data fetch**
The session upgrade step after login is required. Ensure you are using the latest version of this integration — earlier versions did not include the two-step login flow.

**`Login failed: Fail to decrypt`**
The password is RSA-encrypted before sending. This error means the encryption key mismatch. Ensure you have not modified `const.py`.

**Sensors show `unavailable`**
Check the HA logs for errors from `univers_ems`. Common causes:

* Incorrect credentials
* The Univers EMS portal is unreachable (cloud dependency)
* Token expired and re-login failed

**`send_forced_control` service has no effect**
Check the HA logs for `univers_ems`. Common causes:

* The integration has not fully loaded — wait for first coordinator refresh
* The inverter rejected a parameter combination — check logs for the API error message

**`Failed to load services.yaml` error in logs**
Upgrade to v0.0.7 or later, which includes the missing `services.yaml` file.

**Wrong sign on battery or grid sensors**
The sign conventions follow the raw API values. If your system reports them inverted, please open an issue with details of your hardware configuration.

---

## Technical Notes

The integration authenticates against Envision's EnOS platform hosted at `app-portal-eu2.envisioniot.com`. Authentication requires a two-step flow:

1. `POST /app-portal/web/v1/login` — initial login with RSA-encrypted password
2. `POST /app-portal/web/v1/session/set` — session upgrade that returns a token with full API permissions

During setup, the integration calls `POST /hossain-bff/monitor/v1.0/asset/list` to automatically discover the inverter (`Res_Inverter`) and battery (`Res_Storage`) device IDs under the site asset. These are stored in the config entry and used for all subsequent control operations.

Data is fetched from:

```
POST /hossain-bff/monitor/v1.0/asset/detail
```

Control commands are sent to:

```
POST /hossain-bff/connect/v1.0/device/control
```

Poll interval defaults to 60 seconds, configurable at setup time or via **Settings → Devices & Services → Univers EMS → Configure**.

The `send_forced_control` service always sends the full parameter set for the selected mode (Idle, Charge, or Discharge), including `SettingMode = 0` (Duration) for Charge and Discharge. Energy-based control (`SettingMode = 1`) is not yet supported.

---

## Changelog

### v0.0.8
- `send_forced_control` now always sends the full parameter set for the selected mode rather than diffing against last-polled state. This eliminates any risk of stale coordinator data causing missed updates.
- `SettingMode` (`PUB_INV_Hossain.SettingMode`) is now always sent as `0` (Duration) with Charge and Discharge commands. Energy mode (`SettingMode = 1`) is recognised in constants but not yet supported.
- `SettingMode` added to `CONTROL_MEASUREMENT_POINTS` so it is included in regular polls.

### v0.0.7
- Fixed: changing the poll interval via **Configure** had no effect — the options flow was reading from `entry.data` only, ignoring previously saved options values.
- Fixed: `Failed to load services.yaml` error logged on startup — added missing `services.yaml` file.

### v0.0.6
- Poll interval is now configurable at setup time and via **Settings → Devices & Services → Univers EMS → Configure**.

### v0.0.5
- Added forced charge/discharge control via `select`, `number`, and `send_forced_control` service.
- Auto-discovery of inverter and storage device IDs during setup.

### v0.0.4
- Initial release with sensor monitoring.