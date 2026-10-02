"""The FamilyWall integration."""

from __future__ import annotations

import aiohttp

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import FamilyWallAuthError, FamilyWallClient, FamilyWallError
from .coordinator import FamilyWallConfigEntry, FamilyWallCoordinator

PLATFORMS = [Platform.TODO]


async def async_setup_entry(hass: HomeAssistant, entry: FamilyWallConfigEntry) -> bool:
    """Set up FamilyWall from a config entry."""
    # Own session (own cookie jar) per entry, see FamilyWallClient.__init__.
    session = async_create_clientsession(hass)
    client = FamilyWallClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await client.login()
    except (FamilyWallAuthError, FamilyWallError, aiohttp.ClientError) as err:
        raise ConfigEntryNotReady(f"FamilyWall login failed: {err}") from err

    coordinator = FamilyWallCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FamilyWallConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
