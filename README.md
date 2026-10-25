# Deye TOU Manager

A Home Assistant custom integration and Lovelace card for named, six-slot Deye Time of Use presets. It uses the existing ESPHome entities from [Lewa-Reka/esphome-deye-inverter](https://github.com/Lewa-Reka/esphome-deye-inverter), with the `deye_inverter_esp32` prefix. No second Modbus connection or cloud account is needed.

This repository packages version 0.4.0 for HACS. It builds on the 0.3.0 YAML integration and keeps its integration domain, service names, entity ID, and Home Assistant storage key.

## What it does

- Create and edit any number of named presets in Home Assistant without writing to the inverter.
- Capture the current six-slot configuration, duplicate or delete presets, and update a preset from the inverter.
- Assign a preset to each weekday.
- Apply a preset manually, or enable the built-in schedule for 00:00:15 and Home Assistant startup.
- Wait up to three minutes for ESPHome on startup, and skip scheduled writes when the current configuration already matches.

Only **Apply** and the enabled schedule write inverter settings. `save_current` reads entities but does not write them. Automatic application defaults to **off** for new stores and retains its saved setting on upgrades.

## Requirements

- Home Assistant with the HTTP integration and HACS.
- ESPHome Deye entities named `deye_inverter_esp32_*`, including the work mode select, Solar Sell switch, the main TOU switch, seven TOU day switches, and six `start`, `soc`, `out_power`, `grid_charge`, and `gen` controls. The expected entity names are in [the source](custom_components/deye_tou_manager/__init__.py).
- A Deye inverter configured for SOC based TOU. The integration does not manage the slot voltage entities or the global Battery Grid Charging permission.

This is a YAML configured integration. HACS installs the files; it does not configure or enable the integration in Home Assistant.

## Install with HACS

1. In HACS, add this GitHub repository as a **Custom repository** of type **Integration**, then install **Deye TOU Manager**.
2. Add this top-level entry to `/config/configuration.yaml` if it is not already present:

   ```yaml
   deye_tou_manager:
   ```

3. Check the Home Assistant configuration and restart Home Assistant.
4. In **Settings → Dashboards → Resources**, add `/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.0` as a **JavaScript module**.
5. Add a manual dashboard card:

   ```yaml
   type: custom:deye-tou-manager-card
   ```

After setup, `sensor.deye_tou_preset_manager` supplies the card with presets, weekday assignments, the automation setting, and the latest automatic result. Change the resource query version on each frontend update to refresh browser caches.

## Upgrade from a manual 0.3.0 installation

1. Back up `/config/.storage/deye_tou_manager` before replacing the integration. Do not edit the live storage file.
2. Install this repository through HACS. It replaces the files under the same `/config/custom_components/deye_tou_manager` domain. Leave the existing `deye_tou_manager:` YAML entry in place.
3. Replace the old dashboard resource `/local/deye-tou-manager-card.js?v=3` with `/api/deye_tou_manager/deye-tou-manager-card.js?v=0.4.0`. Keep only one resource definition for the card.
4. Check the configuration, restart Home Assistant, and refresh the dashboard. Confirm that the saved presets, day assignments, and automation setting appear before using **Apply**.

The new version still loads `Store(hass, 1, "deye_tou_manager")` from the same `.storage` key; there is no preset migration. The old `/config/www/deye-tou-manager-card.js` can remain unused during verification. The older `packages/deye_tou_presets.yaml` is separate and is not removed. Do not run its TOU script or an older midnight automation alongside this integration.

## Applying a preset

An apply first checks all current ESPHome readings and TOU switches. It then turns main TOU off, writes Work Mode, Solar Sell, six slots and all seven day switches, waits for matching readback, and finally re-enables main TOU. A failed write or readback leaves TOU off where possible. Inspect the inverter readings and Home Assistant logs before manually re-enabling TOU. Readback depends on ESPHome reporting the updated values within 30 seconds; slow polling may cause an apply to report failure even if the inverter eventually accepts the settings.

**Selling First** can allow battery export when combined with TOU. Review the Work Mode and Solar Sell values in each preset before applying it or enabling the schedule.

The schedule uses Home Assistant local time, runs at 00:00:15 and on startup, and only applies a preset when one is assigned for that weekday. Manual and scheduled applications share a lock, so they cannot write at the same time.

## Before publishing this repository

The GitHub owner has not been provided yet. Replace `OWNER/deye-tou-manager` in `custom_components/deye_tou_manager/manifest.json` with the actual GitHub `OWNER/REPO`, and add the maintainer GitHub handle to `codeowners`. Set a GitHub description and topics, and enable Issues. Confirm the MIT license choice with the owner. After committing, push the repository:

```bash
git remote add origin https://github.com/OWNER/REPO.git
git push -u origin main
```

For a versioned HACS release, create a GitHub release for tag `v0.4.0` (or push that tag and create the release in GitHub). HACS can also install the default branch without a release. Run the HACS validation action after publishing and resolve any findings before installing on the production HA instance.

The HACS validator runs in GitHub Actions after publishing. The current version has not yet been tested against the user's Home Assistant container or a physical Deye inverter; perform a first live test by saving the current TOU configuration, then verify readback before trying Apply.
