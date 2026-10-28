# Advanced usage and safety

This page contains the detailed behavior and safety notes for Deye TOU EMS. For installation and the three main workflows, start with the [README](../README.md).

## Setup details

During setup, choose the Lewa-Reka ESPHome inverter's `select.…_system_work_mode` entity. You can also select cumulative grid-export and grid-import energy meters. The picker lists live `energy` / `total_increasing` sensors with Wh, kWh, or MWh units.

The integration derives all other TOU controls from the Work Mode entity prefix and does not change inverter settings during setup. If there is more than one compatible inverter, choose the intended one carefully. You can change it later through the integration's **Configure** options; changing the target disables the weekly schedule until it has been reviewed and enabled again.

## Stored data

Presets, weekday assignments, selling plans, revenue records, and action-log entries are stored by Home Assistant in `/config/.storage/deye_tou_manager`. Presets use stable SHA-256 IDs while their names remain editable. Do not edit the live storage file by hand. To rename a preset through `save_definition`, pass its ID from the manager sensor's `preset_ids` attribute as `preset_id` together with the new `name`.

## TOU presets and applying safely

The main card's compact section is read-only and shows the inverter's live Work Mode, Solar Sell, TOU state, and six slots. Each slot displays its start and calculated end time. The editor also shows the end time as you change a start time. A slot ends when the next one starts; slot six ends at slot one's start on the following day.

Presets can be edited offline, duplicated, created blank, or captured from the inverter. Renaming retains weekday assignments. The schedule runs at 00:00:15 and after Home Assistant startup when enabled.

Before an apply, the integration checks all six slots and TOU switch states. It turns main TOU off, writes Work Mode, Solar Sell, the six slots, and weekday switches, waits for matching ESPHome readings, then re-enables main TOU. If a write or readback fails, it attempts to leave main TOU off. Readback can take up to 30 seconds.

**Selling First** with TOU may export battery energy. Check Work Mode, Solar Sell, and the inverter readings before applying a preset or enabling the schedule. Manual and scheduled applies share a lock and cannot write concurrently.

## Selling planner

The selling card uses the Lewa-Reka [RCE PSE integration](https://github.com/Lewa-Reka/ha-rce-pse). In the integration's **Configure** options, choose its **Price** and **Price Tomorrow** entities. The planner reads a complete day of 15-minute prices, converts PLN/MWh or PLN/kWh to PLN/kWh, calculates hourly mean prices, and selects the highest configured number of one-hour blocks above the minimum price.

You can limit candidates to morning, afternoon, evening (16:00–24:00), or any time. A plan for today excludes completed hours but can include the current hour until it ends. **Check today** and **Check tomorrow** save the visible settings before recalculating. Incomplete, inconsistent, or daylight-saving duplicate price data is rejected.

Choose Off, semi-automatic, or automatic mode. The manager plans tomorrow at 18:00 and recalculates today at 00:00:15. Every selected one-hour period has an individual approval and target SOC. Automatic mode approves valid periods during the midnight check; semi-automatic mode requires individual approval. Changed prices, settings, or missing price data revoke calculated approvals. Manual selling hours bypass the price threshold but still need their own approval in semi-automatic mode.

## Dry run and live selling

Selling begins in **Dry run** mode. While it is enabled, plans and approvals never change the inverter. Turning Dry run off requires confirmation and enables physical inverter control for approved active periods.

Configure the Battery BMS SOC sensor in integration options; normally it is `sensor.{prefix}_battery_bms_soc`. At the start of an approved live period, the manager saves the current plan, changes only Work Mode to `Selling First`, and changes the active TOU slot's SOC to the period target. It checks SOC every 15 seconds. On the target SOC or period end, it restores the saved Work Mode and slot SOC, marks the period completed, and does not automatically restart it if SOC rebounds.

During a live period, approval and target-SOC controls are disabled. **STOP** restores the snapshot and completes the period. **RESTART** is a confirmed action available only during the remainder of that period's original hour. The snapshot is persisted before any write and is recovered after a Home Assistant restart. A failed read/write or missing SOC triggers a restore attempt rather than a new selling attempt.

## Action log

The integration retains its latest 500 preset, schedule, planning, selling, and inverter-control events in Home Assistant storage. Add `custom:deye-tou-action-log-card` to browse the timestamp, action, and detail. **Normal** mode hides selling-settings, findings-clear, target-SOC, weekday-assignment, and successful plan-calculation changes; **Verbose** mode shows every event. The same entries are exposed as the manager sensor's `action_log` attribute.

## Revenue ledger

Configure cumulative export and import meters in the integration's **Configure** options. Five seconds after each hour, the manager reads Recorder history at both hour boundaries, calculates `max(0, exported − imported)`, and multiplies it by the RCE hourly price. Zero or negative net export, counter resets, incomplete meter readings, and missing price history are skipped rather than estimated.

The revenue-history card shows one day at a time, with hour, RCE price, sold net kWh, revenue, day total, and all-time revenue. The total entities are `sensor.deye_tou_selling_revenue_total` and `sensor.deye_tou_selling_net_export_total`.

After meters are configured, startup and each hourly run backfill one 31-day Recorder-history batch, working back to January 2024 when retained data exists. Stored hours are not recalculated.

## Planned work

- Verify physical selling behavior on a live inverter before relying on it unattended. The optional TOU discharge-power override is not currently used.
- Add configurable Home Assistant notifications for proposed and approved plans.
