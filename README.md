# Deye TOU Manager

<img src="brand/icon.png" alt="Deye TOU Manager icon" width="96">

[![Validate](https://github.com/maclewan/deye-tou-manager/actions/workflows/validate.yml/badge.svg)](https://github.com/maclewan/deye-tou-manager/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](#installation)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration and dashboard card for managing named, six-slot Deye Time of Use (TOU) presets. It uses the existing entities from [Lewa-Reka's ESPHome Deye integration](https://github.com/Lewa-Reka/esphome-deye-inverter); it does not open another Modbus connection or use Deye Cloud.

## Features

- Save the inverter's current TOU settings as a named preset.
- Create, edit, duplicate, and delete presets in Home Assistant without changing the inverter.
- Assign a different preset to each weekday.
- Apply a preset manually, or enable the built-in schedule for 00:00:15 and Home Assistant startup.
- Wait up to three minutes for ESPHome after startup and skip scheduled writes when the active settings already match.

Only **Apply** and the enabled schedule write to the inverter. The schedule is off by default for a new installation.

## Requirements

- Home Assistant with its HTTP integration enabled.
- A Deye inverter with SOC-based TOU controls exposed through ESPHome using the `deye_inverter_esp32` entity prefix.
- The following Home Assistant entities:

| Control | Entity ID |
| --- | --- |
| Work Mode | `select.deye_inverter_esp32_system_work_mode` |
| Solar Sell | `switch.deye_inverter_esp32_solar_sell` |
| Main TOU | `switch.deye_inverter_esp32_time_of_use` |
| TOU weekdays | `switch.deye_inverter_esp32_time_of_use_{monday…sunday}` |
| Slot start, 1–6 | `time.deye_inverter_esp32_time_of_use_{1…6}_start` |
| Slot SOC, 1–6 | `number.deye_inverter_esp32_time_of_use_{1…6}_soc` |
| Slot output power, 1–6 | `number.deye_inverter_esp32_time_of_use_{1…6}_out_power` |
| Slot Grid Charge and Gen, 1–6 | `switch.deye_inverter_esp32_time_of_use_{1…6}_{grid_charge,gen}` |

The slot voltage entities and the inverter's global Battery Grid Charging permission are outside this integration's scope.

## Installation

### HACS (recommended)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/maclewan/deye-tou-manager` with category **Integration**.
3. Find **Deye TOU Manager** in HACS and install it.
4. Continue with [Configuration](#configuration) and restart Home Assistant.

HACS installs files under `custom_components/deye_tou_manager`. It does not add the YAML configuration or the dashboard resource for you. See [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/) for the current HACS interface.

### Manual installation

Copy the repository's `custom_components/deye_tou_manager` directory into `/config/custom_components/deye_tou_manager`, then continue with [Configuration](#configuration). The dashboard card is already inside the integration directory; do not copy it separately to `/config/www`.

## Configuration

This integration uses YAML configuration. Add the following at the top level of `/config/configuration.yaml` if it is not already present:

```yaml
deye_tou_manager:
```

Check the Home Assistant configuration and restart. `sensor.deye_tou_preset_manager` should then appear with `presets`, `assignments`, and `auto_enabled` attributes.

In **Settings → Dashboards → Resources**, add this URL as a **JavaScript module**:

```text
/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.0
```

Add a manual card to your dashboard:

```yaml
type: custom:deye-tou-manager-card
```

When updating to a version with card changes, update the `?v=` query value and refresh the browser.

## Usage

Use the card to save the current six slots, work mode, and Solar Sell value; or create a blank preset and edit it offline. Assign presets to weekdays and use **Wczytaj do Deye** to apply one manually. Turn on **Włącz harmonogram tygodniowy** only after checking the assignments. The card shows the latest automatic result.

The integration also registers these Home Assistant actions:

| Action | Purpose | Writes to inverter? |
| --- | --- | --- |
| `deye_tou_manager.save_current` | Save the current ESPHome readings as a preset | No |
| `deye_tou_manager.save_definition` | Save an offline preset definition | No |
| `deye_tou_manager.delete` | Delete a preset and clear its day assignments | No |
| `deye_tou_manager.assign_day` | Assign or clear a weekday preset | No |
| `deye_tou_manager.set_auto` | Enable or disable the built-in schedule | No immediate write |
| `deye_tou_manager.apply` | Apply a preset to the inverter | Yes |

Presets and assignments are stored by Home Assistant in `/config/.storage/deye_tou_manager`. Do not edit the live storage file by hand.

### Apply behavior and safety

Before an apply, the integration checks the six slots and all TOU switch states. It turns main TOU off, writes Work Mode, Solar Sell, six slots, and all seven day switches, waits for matching ESPHome readings, then re-enables main TOU. If a write or readback fails, it tries to leave main TOU off. Check the inverter readings and Home Assistant logs before turning TOU on manually.

Readback waits for up to 30 seconds. Slow ESPHome updates can therefore report a failure even if the inverter later accepts the settings. **Selling First** with TOU can allow battery export; review Work Mode and Solar Sell before applying a preset or enabling the schedule.

The schedule uses Home Assistant local time. Manual and scheduled applies share a lock, so they cannot write concurrently.

## Upgrading from the manual 0.3.0 installation

1. Back up `/config/.storage/deye_tou_manager`.
2. Install this repository through HACS. Keep the existing `deye_tou_manager:` entry in `configuration.yaml`.
3. Replace the old dashboard resource `/local/deye-tou-manager-card.js?v=3` with `/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.0`. Keep only one resource for this card.
4. Check the Home Assistant configuration, restart, and refresh the dashboard. Confirm your presets, weekday assignments, and automation setting before applying anything.

The integration domain and `Store(hass, 1, "deye_tou_manager")` storage key are unchanged, so saved presets need no migration. The old `/config/www/deye-tou-manager-card.js` may remain unused during verification. The older `packages/deye_tou_presets.yaml` is separate; do not run its TOU script or an older midnight automation alongside this integration.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Card says the manager sensor is missing | Confirm the YAML entry, restart Home Assistant, and check the integration logs. |
| Card does not load | Confirm the JavaScript module resource URL and refresh the browser. |
| Apply fails or TOU remains off | Check ESPHome availability, the six slot readings, all seven day switches, and Home Assistant logs before manually enabling TOU. |
| Schedule does not apply a preset | Confirm it is enabled and that today's weekday has an assignment. |

## Development

The repository includes a HACS validation workflow and local tests:

```bash
python -m unittest discover -s tests -v
node tests/card-smoke.cjs
```

The Python tests use a simulated Home Assistant service and state layer. The integration has not yet been tested against a live Home Assistant instance or physical Deye inverter. Start live verification by saving the current TOU settings, then inspect the captured preset before trying **Apply**.

## License

[MIT](LICENSE)
