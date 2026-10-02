"""The FamilyWall integration."""

from __future__ import annotations

from pathlib import Path

import aiohttp

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import FamilyWallAuthError, FamilyWallClient, FamilyWallError
from .const import DOMAIN
from .coordinator import FamilyWallConfigEntry, FamilyWallCoordinator

PLATFORMS = [Platform.BUTTON, Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = "/familywall/familywall-list-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "familywall-list-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled dashboard card and load it in every frontend."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    # Version in the query string so browsers pick up a new card after an update.
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True


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
