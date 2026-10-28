"""Choose the ESPHome inverter controlled by Deye TOU EMS."""

from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol

from . import (
    CONF_TODAY_PRICE_ENTITY,
    CONF_TOMORROW_PRICE_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EXPORT_ENERGY_ENTITY,
    CONF_IMPORT_ENERGY_ENTITY,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
    default_battery_soc_entity,
    energy_meter_candidates,
    rce_price_entities,
    work_mode_candidates,
)


class DeyeTouManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single local manager instance for a selected inverter."""

    async def async_step_user(self, user_input=None):
        candidates = work_mode_candidates(self.hass)
        energy_meters = [""] + energy_meter_candidates(self.hass)
        if not candidates:
            return self.async_abort(reason="no_compatible_entities")
        if user_input is not None:
            if (user_input[CONF_WORK_MODE_ENTITY] in candidates
                    and user_input.get(CONF_EXPORT_ENERGY_ENTITY, "") in energy_meters
                    and user_input.get(CONF_IMPORT_ENERGY_ENTITY, "") in energy_meters):
                return self.async_create_entry(
                    title="Deye TOU EMS",
                    data={
                        CONF_WORK_MODE_ENTITY: user_input[CONF_WORK_MODE_ENTITY],
                        CONF_EXPORT_ENERGY_ENTITY: user_input.get(CONF_EXPORT_ENERGY_ENTITY, ""),
                        CONF_IMPORT_ENERGY_ENTITY: user_input.get(CONF_IMPORT_ENERGY_ENTITY, ""),
                    },
                )
            errors = {"base": "invalid_entity"}
        else:
            errors = {}
        key = (
            vol.Required(CONF_WORK_MODE_ENTITY, default=candidates[0])
            if len(candidates) == 1 else vol.Required(CONF_WORK_MODE_ENTITY)
        )
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({
                key: vol.In(candidates),
                vol.Required(CONF_EXPORT_ENERGY_ENTITY, default=""): vol.In(energy_meters),
                vol.Required(CONF_IMPORT_ENERGY_ENTITY, default=""): vol.In(energy_meters),
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Allow choosing a different inverter after installation."""
        return DeyeTouManagerOptionsFlow()


class DeyeTouManagerOptionsFlow(config_entries.OptionsFlow):
    """Change the selected Work Mode entity."""

    async def async_step_init(self, user_input=None):
        current = self.config_entry.options.get(
            CONF_WORK_MODE_ENTITY,
            self.config_entry.data.get(CONF_WORK_MODE_ENTITY),
        )
        candidates = work_mode_candidates(self.hass)
        if current and current not in candidates:
            candidates.append(current)
            candidates.sort()
        if not candidates:
            return self.async_abort(reason="no_compatible_entities")
        price_entities = rce_price_entities(self.hass)
        energy_meters = [""] + energy_meter_candidates(self.hass)
        today_prices = ["", price_entities.get("today", "")]
        tomorrow_prices = ["", price_entities.get("tomorrow", "")]
        battery_default = self.config_entry.options.get(
            CONF_BATTERY_SOC_ENTITY, default_battery_soc_entity(current or candidates[0])
        )
        for values, current_key in (
            (today_prices, CONF_TODAY_PRICE_ENTITY),
            (tomorrow_prices, CONF_TOMORROW_PRICE_ENTITY),
        ):
            configured = self.config_entry.options.get(current_key, "")
            if configured and configured not in values:
                values.append(configured)
        energy_values = {}
        for key in (CONF_EXPORT_ENERGY_ENTITY, CONF_IMPORT_ENERGY_ENTITY):
            configured = self.config_entry.options.get(
                key, self.config_entry.data.get(key, "")
            )
            values = energy_meters.copy()
            if configured and configured not in values:
                values.append(configured)
            energy_values[key] = values
        if user_input is not None:
            battery_soc = user_input.get(CONF_BATTERY_SOC_ENTITY, "")
            if (user_input[CONF_WORK_MODE_ENTITY] in candidates
                    and user_input[CONF_TODAY_PRICE_ENTITY] in today_prices
                    and user_input[CONF_TOMORROW_PRICE_ENTITY] in tomorrow_prices
                    and user_input[CONF_EXPORT_ENERGY_ENTITY] in energy_values[CONF_EXPORT_ENERGY_ENTITY]
                    and user_input[CONF_IMPORT_ENERGY_ENTITY] in energy_values[CONF_IMPORT_ENERGY_ENTITY]
                    and isinstance(battery_soc, str) and battery_soc.startswith("sensor.")):
                return self.async_create_entry(title="", data={
                    **user_input, CONF_BATTERY_SOC_ENTITY: battery_soc,
                })
            errors = {"base": "invalid_entity"}
        else:
            errors = {}
        key = vol.Required(CONF_WORK_MODE_ENTITY, default=current or candidates[0])
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema({
                key: vol.In(candidates),
                vol.Required(CONF_TODAY_PRICE_ENTITY, default=self.config_entry.options.get(
                    CONF_TODAY_PRICE_ENTITY, price_entities.get("today", "")
                )): vol.In(today_prices),
                vol.Required(CONF_TOMORROW_PRICE_ENTITY, default=self.config_entry.options.get(
                    CONF_TOMORROW_PRICE_ENTITY, price_entities.get("tomorrow", "")
                )): vol.In(tomorrow_prices),
                vol.Required(CONF_BATTERY_SOC_ENTITY, default=battery_default): str,
                vol.Required(CONF_EXPORT_ENERGY_ENTITY, default=self.config_entry.options.get(
                    CONF_EXPORT_ENERGY_ENTITY, self.config_entry.data.get(CONF_EXPORT_ENERGY_ENTITY, "")
                )): vol.In(energy_values[CONF_EXPORT_ENERGY_ENTITY]),
                vol.Required(CONF_IMPORT_ENERGY_ENTITY, default=self.config_entry.options.get(
                    CONF_IMPORT_ENERGY_ENTITY, self.config_entry.data.get(CONF_IMPORT_ENERGY_ENTITY, "")
                )): vol.In(energy_values[CONF_IMPORT_ENERGY_ENTITY]),
            }),
            errors=errors,
        )
