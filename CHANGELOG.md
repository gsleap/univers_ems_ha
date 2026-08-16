# Changelog

All notable changes to Univers EMS for Home Assistant are documented here.

## v0.0.9
- Fixed: login started failing with "The user name or password is wrong" after HA Core 2026.8.2, even with correct credentials. The `account` field in the login request now needs to be base64-encoded — the API tightened validation on this field, and requests sending it as plain text are rejected.
- Docs/tests: the `Username (email)` prompt in the test scripts was misleading — the field is the plain username, not an email address. Updated to `Username`.
- Docs: split the changelog out of `README.md` into a standalone `CHANGELOG.md`.
- Housekeeping: removed a real Asset ID that had leaked into the test scripts' usage comments, replaced with a placeholder.

## v0.0.8
- `send_forced_control` now always sends the full parameter set for the selected mode rather than diffing against last-polled state. This eliminates any risk of stale coordinator data causing missed updates.
- `SettingMode` (`PUB_INV_Hossain.SettingMode`) is now always sent as `0` (Duration) with Charge and Discharge commands. Energy mode (`SettingMode = 1`) is recognised in constants but not yet supported.
- `SettingMode` added to `CONTROL_MEASUREMENT_POINTS` so it is included in regular polls.

## v0.0.7
- Fixed: changing the poll interval via **Configure** had no effect — the options flow was reading from `entry.data` only, ignoring previously saved options values.
- Fixed: `Failed to load services.yaml` error logged on startup — added missing `services.yaml` file.

## v0.0.6
- Poll interval is now configurable at setup time and via **Settings → Devices & Services → Univers EMS → Configure**.

## v0.0.5
- Added forced charge/discharge control via `select`, `number`, and `send_forced_control` service.
- Auto-discovery of inverter and storage device IDs during setup.

## v0.0.4
- Initial release with sensor monitoring.
