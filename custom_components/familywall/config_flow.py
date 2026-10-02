"""Config flow for FamilyWall."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FamilyWallAuthError, FamilyWallClient, FamilyWallError, FamilyWallList
from .const import CONF_LISTS, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class FamilyWallConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FamilyWall."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._lists: list[FamilyWallList] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the FamilyWall login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].strip().lower())
            self._abort_if_unique_id_configured()
            session = async_create_clientsession(self.hass)
            client = FamilyWallClient(session, user_input[CONF_EMAIL].strip(), user_input[CONF_PASSWORD])
            try:
                await client.login()
                self._lists = await client.get_lists()
            except FamilyWallAuthError:
                errors["base"] = "invalid_auth"
            except (FamilyWallError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during FamilyWall login")
                errors["base"] = "unknown"
            finally:
                await session.close()
            if not errors:
                if not self._lists:
                    return self.async_abort(reason="no_lists")
                self._credentials = {
                    CONF_EMAIL: user_input[CONF_EMAIL].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return await self.async_step_lists()

        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    async def async_step_lists(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user pick which lists to expose."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_LISTS]:
                return self.async_create_entry(
                    title=self._credentials[CONF_EMAIL],
                    data={**self._credentials, CONF_LISTS: user_input[CONF_LISTS]},
                )
            errors["base"] = "no_selection"

        default = [fw.id for fw in self._lists if fw.type == "shopping"]
        schema = vol.Schema(
            {
                vol.Required(CONF_LISTS, default=default): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=fw.id, label=f"{fw.name} ({fw.type or '?'})")
                            for fw in self._lists
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="lists", data_schema=schema, errors=errors)
