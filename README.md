# Deye TOU EMS

<img src="brand/icon.png" alt="Deye TOU EMS icon" width="96">

[![Validate](https://github.com/maclewan/deye-tou-manager/actions/workflows/validate.yml/badge.svg)](https://github.com/maclewan/deye-tou-manager/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](#installation)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant integration and dashboard cards for Deye inverters exposed by [Lewa-Reka's ESPHome Deye integration](https://github.com/Lewa-Reka/esphome-deye-inverter). It uses those existing entities—no second Modbus connection or Deye Cloud account is needed.

## Three things it does

1. **Manage TOU presets** — save the inverter's six-slot TOU configuration, edit named presets safely, and assign one preset to each weekday. Apply a preset manually or use the optional weekly schedule.
2. **Plan battery selling** — use RCE PSE prices to find profitable one-hour selling periods, add manual periods, set a target SOC per period, and approve each period. Plans begin in **Dry run** mode, so they cannot change the inverter until you explicitly turn it off.
3. **Estimate daily revenue** — calculate measured hourly net export from cumulative grid meters, combine it with RCE prices, and browse daily kWh, revenue, and action history in separate cards.

The weekly schedule is off by default. Only **Apply**, the enabled schedule, or selling with Dry run turned off can write to the inverter.

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
3. Find this integration in HACS and install it.
4. Restart Home Assistant, then open **Settings → Devices & services → Add integration**, search for **Deye TOU Preset Manager**, and choose the inverter's Work Mode entity.

HACS installs the integration and registers the shared card resource automatically. No YAML is needed.

## Configuration

Add **Deye TOU Preset Manager** in **Settings → Devices & services** and choose your inverter's Work Mode entity. Optionally select grid export/import meters for revenue estimates. You can change these later in **Configure**.

After setup, `sensor.deye_tou_preset_manager` contains the integration data.

With dashboard resources in storage mode (Home Assistant's default), the integration automatically keeps one JavaScript module resource for both cards at:

```text
/api/deye_tou_manager/deye-tou-manager-card.js?v=1.1.0
```

Add a manual card to your dashboard:

```yaml
type: custom:deye-tou-manager-card
```

Add the separate energy-selling planner card wherever you want it:

```yaml
type: custom:deye-tou-selling-card
```

Add the separate hourly revenue-history card to browse one recorded day at a time:

```yaml
type: custom:deye-tou-selling-history-card
```

Add the separate action-log card to review saved planning and inverter events:

```yaml
type: custom:deye-tou-action-log-card
```

After a card update, refresh the browser.

## Quick use

- **TOU:** save the current inverter plan, edit or create a preset, assign it to weekdays, then apply it or enable the weekly schedule.
- **Selling:** configure RCE PSE prices and battery SOC, check a plan, approve the periods you want, and leave **Dry run** on until you are ready for live control.
- **Revenue:** configure cumulative export and import energy meters, then add the revenue-history card.

For detailed behavior, safety rules, selling planning, and revenue calculation, see [Advanced usage and safety](docs/advanced-usage.md).

The integration also registers these Home Assistant actions:

| Action | Purpose | Writes to inverter? |
| --- | --- | --- |
| `deye_tou_manager.save_current` | Save the current ESPHome readings as a preset | No |
| `deye_tou_manager.save_definition` | Save an offline preset definition | No |
| `deye_tou_manager.delete` | Delete a preset and clear its day assignments | No |
| `deye_tou_manager.assign_day` | Assign or clear a weekday preset | No |
| `deye_tou_manager.set_auto` | Enable or disable the built-in schedule | No immediate write |
| `deye_tou_manager.apply` | Apply a preset to the inverter | Yes |
| `deye_tou_manager.set_selling_settings` | Configure selling and Dry run | No immediate write |
| `deye_tou_manager.refresh_selling_plan` | Recalculate today's or tomorrow's plan | No |
| `deye_tou_manager.approve_selling_range` | Approve or unapprove one semi-automatic selling hour | May start selling when its period is active and Dry run is off |
| `deye_tou_manager.set_selling_range_soc` | Set one period's stop SOC | No |
| `deye_tou_manager.stop_selling` | Stop the active period and restore the prior settings | Yes |
| `deye_tou_manager.restart_selling` | Restart a completed period during its original hour | Yes |

Data is stored by Home Assistant. Do not edit the storage file manually; see [Advanced usage and safety](docs/advanced-usage.md#stored-data) for details.

## Energy selling

Use `custom:deye-tou-selling-card` to plan and approve hourly selling periods. It starts in Dry run mode. See [Advanced usage and safety](docs/advanced-usage.md#selling-planner) before turning on live control.

## Revenue

Use `custom:deye-tou-selling-history-card` to view daily net export and revenue. The totals are also available as:

| Entity | Meaning |
| --- | --- |
| `sensor.deye_tou_selling_revenue_total` | Total measured revenue in PLN |
| `sensor.deye_tou_selling_net_export_total` | Total measured net exported energy in kWh |

For meter requirements and calculation details, see [Advanced usage and safety](docs/advanced-usage.md#revenue-ledger).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Card says the manager sensor is missing | Confirm the integration was added through **Devices & services**, restart Home Assistant, and check the logs. |
| Card does not load | Confirm that the integration is active and the card resource URL matches the URL above, then refresh the browser. |
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
