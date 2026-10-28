# Changelog

## 1.0.3

- Renamed the user-facing integration to Deye TOU EMS.
- Added Normal and Verbose modes to the action-log card.
- Allowed the current selling hour to be planned until it ends.

## 1.0.0

- Replaced the live-control opt-in with a confirmed Dry run control that is enabled by default.
- Added a persisted, paged action-log dashboard card for preset, plan, selling, and inverter events.
- First stable HACS release of Deye TOU EMS.
- UI setup for the selected Lewa-Reka Deye inverter; no configuration YAML is required.
- Named TOU presets, weekday scheduling, and automatic dashboard-resource registration.
- Energy-selling planning with RCE PSE prices, per-period target SOC, safe STOP/RESTART controls, and recovery after restart.
- Measured hourly export/revenue ledger and paged selling-history card.
