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
- Select the Lewa-Reka ESPHome inverter during setup; entity IDs are derived from its Work Mode entity.
- Apply a preset manually, or enable the built-in schedule for 00:00:15 and Home Assistant startup.
- Wait up to three minutes for ESPHome after startup and skip scheduled writes when the active settings already match.

Only **Apply** and the enabled schedule write to the inverter. The schedule is off by default for a new installation.

## Requirements

- Home Assistant with its HTTP integration enabled.
- A Deye inverter with SOC-based TOU controls exposed through Lewa-Reka's ESPHome configuration.
- The following Home Assistant entities, where `{prefix}` is derived from the selected `select.{prefix}_system_work_mode` entity:

| Control | Entity ID |
| --- | --- |
| Work Mode | `select.{prefix}_system_work_mode` |
| Solar Sell | `switch.{prefix}_solar_sell` |
| Main TOU | `switch.{prefix}_time_of_use` |
| TOU weekdays | `switch.{prefix}_time_of_use_{monday…sunday}` |
| Slot start, 1–6 | `time.{prefix}_time_of_use_{1…6}_start` |
| Slot SOC, 1–6 | `number.{prefix}_time_of_use_{1…6}_soc` |
| Slot output power, 1–6 | `number.{prefix}_time_of_use_{1…6}_out_power` |
| Slot Grid Charge and Gen, 1–6 | `switch.{prefix}_time_of_use_{1…6}_{grid_charge,gen}` |

The slot voltage entities and the inverter's global Battery Grid Charging permission are outside this integration's scope.

## Installation

### HACS (recommended)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/maclewan/deye-tou-manager` with category **Integration**.
3. Find **Deye TOU Manager** in HACS and install it.
4. Restart Home Assistant, then open **Settings → Devices & services → Add integration**, search for **Deye TOU Preset Manager**, and choose the inverter's Work Mode entity.

HACS installs files under `custom_components/deye_tou_manager`. The setup flow activates the manager without editing `configuration.yaml`. In the default dashboard resource mode, the integration also installs and updates its card resource automatically. See [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/) for the current HACS interface.

### Manual installation

Copy the repository's `custom_components/deye_tou_manager` directory into `/config/custom_components/deye_tou_manager`, restart Home Assistant, then add the integration from **Settings → Devices & services**. The dashboard card is already inside the integration directory; do not copy it separately to `/config/www`.

## Configuration

The recommended setup is through **Settings → Devices & services → Add integration → Deye TOU Preset Manager**. Choose the Lewa-Reka ESPHome inverter's `select.…_system_work_mode` entity. The integration uses its prefix for all TOU controls; `deye_inverter_esp32` is no longer required. No YAML entry is needed, and setup does not change inverter settings. If more than one compatible Work Mode entity exists, choose the intended inverter carefully. You can change it later under the integration's **Configure** options; doing so reloads the manager. Changing the target disables the weekly schedule until you review and re-enable it.

Legacy YAML setup remains supported. If you already have the following at the top level of `/config/configuration.yaml`, you can keep it instead of adding the integration through the UI:

```yaml
deye_tou_manager:
```

For YAML setup, the only matching Work Mode entity is detected automatically. If several are present, specify the one to control:

```yaml
deye_tou_manager:
  work_mode_entity: select.my_deye_system_work_mode
```

The other entity IDs must retain the Lewa-Reka suffixes shown above. If they have been renamed individually, selecting Work Mode alone cannot map them.
For reliable YAML startup when ESPHome is offline, set `work_mode_entity` explicitly. Older YAML installs with no detected entity retain the previous `deye_inverter_esp32` target as a compatibility fallback.

After UI setup or a YAML configuration check and restart, `sensor.deye_tou_preset_manager` should appear with `presets`, `assignments`, and `auto_enabled` attributes. To move from YAML to UI setup, remove the YAML entry, restart, and add the integration through **Devices & services**; the saved presets use the same storage key.

With dashboard resources in storage mode (Home Assistant's default), the integration automatically keeps one JavaScript module resource for this card at:

```text
/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.3
```

If you use YAML-mode dashboard resources, update your Lovelace `resources:` entry manually to this URL with `type: module`; the integration cannot edit your YAML file. Remove the old `/local/deye-tou-manager-card.js?v=3` entry so there is only one resource for this card.

Add a manual card to your dashboard:

```yaml
type: custom:deye-tou-manager-card
```

After a card update, refresh the browser. Storage-mode resource URLs are updated by the integration when needed; YAML-mode resource URLs remain your responsibility.

## Usage

The compact section at the top shows the inverter's **live** Work Mode, Solar Sell, TOU, and six slot readings; it is read-only. Selecting a saved preset opens its full editor by default. Edit it offline, duplicate it, start a blank preset, or capture the inverter's current values as a new preset. Assign presets to weekdays and use **Wczytaj do Deye** to apply one manually. Turn on **Włącz harmonogram tygodniowy** only after checking the assignments. The card shows the latest automatic result.

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
2. Install this repository through HACS. You can keep the existing `deye_tou_manager:` entry in `configuration.yaml`, or remove it and use the UI setup flow after restarting.
3. In storage-mode dashboard resources, the integration replaces `/local/deye-tou-manager-card.js?v=3` with `/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.3` and removes duplicates automatically on startup. In YAML resource mode, replace the entry yourself and keep only one resource for this card.
4. Check the Home Assistant configuration, restart, and refresh the dashboard. Confirm your presets, weekday assignments, and automation setting before applying anything.

The integration domain and `Store(hass, 1, "deye_tou_manager")` storage key are unchanged, so saved presets need no migration. The old `/config/www/deye-tou-manager-card.js` may remain unused during verification. The older `packages/deye_tou_presets.yaml` is separate; do not run its TOU script or an older midnight automation alongside this integration.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Card says the manager sensor is missing | Confirm the integration was added through **Devices & services**, or that the legacy YAML entry is present; restart Home Assistant and check the logs. |
| Card does not load | Confirm that the integration is active and the single JavaScript module resource URL matches the URL above, then refresh the browser. YAML-mode resources must be edited manually. |
| No compatible Work Mode entity at UI setup | Finish the ESPHome setup and confirm its `select.…_system_work_mode` entity appears in Home Assistant, then try again. |
| Apply fails or TOU remains off | Check the selected Work Mode entity, ESPHome availability, the six slot readings, all seven day switches, and Home Assistant logs before manually enabling TOU. |
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
