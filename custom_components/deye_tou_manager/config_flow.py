"""UI setup for the Deye TOU Preset Manager."""

from homeassistant import config_entries
import voluptuous as vol

from . import DOMAIN


class DeyeTouManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create the single local manager instance."""

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Deye TOU Preset Manager", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
