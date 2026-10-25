"""Choose the ESPHome inverter controlled by the Deye TOU Preset Manager."""

from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol

from . import CONF_WORK_MODE_ENTITY, DOMAIN, work_mode_candidates


class DeyeTouManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single local manager instance for a selected inverter."""

    async def async_step_user(self, user_input=None):
        candidates = work_mode_candidates(self.hass)
        if not candidates:
            return self.async_abort(reason="no_compatible_entities")
        if user_input is not None:
            if user_input[CONF_WORK_MODE_ENTITY] in candidates:
                return self.async_create_entry(
                    title="Deye TOU Preset Manager",
                    data={CONF_WORK_MODE_ENTITY: user_input[CONF_WORK_MODE_ENTITY]},
                )
            errors = {"base": "invalid_entity"}
        else:
            errors = {}
        key = (
            vol.Required(CONF_WORK_MODE_ENTITY, default=candidates[0])
            if len(candidates) == 1 else vol.Required(CONF_WORK_MODE_ENTITY)
        )
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({key: vol.In(candidates)}),
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
        if user_input is not None:
            if user_input[CONF_WORK_MODE_ENTITY] in candidates:
                return self.async_create_entry(title="", data=user_input)
            errors = {"base": "invalid_entity"}
        else:
            errors = {}
        key = vol.Required(CONF_WORK_MODE_ENTITY, default=current or candidates[0])
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema({key: vol.In(candidates)}),
            errors=errors,
        )
