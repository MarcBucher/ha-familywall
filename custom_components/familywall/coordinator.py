"""Data update coordinator for FamilyWall."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FamilyWallClient, FamilyWallError, FamilyWallList
from .const import CONF_LISTS, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type FamilyWallConfigEntry = ConfigEntry[FamilyWallCoordinator]


class FamilyWallCoordinator(DataUpdateCoordinator[dict[str, FamilyWallList]]):
    """Polls the selected FamilyWall lists."""

    config_entry: FamilyWallConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: FamilyWallConfigEntry, client: FamilyWallClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, FamilyWallList]:
        selected = set(self.config_entry.data[CONF_LISTS])
        try:
            lists = {fw.id: fw for fw in await self.client.get_lists() if fw.id in selected}
            for fw in lists.values():
                fw.items = await self.client.get_items(fw.id)
                fw.categories = await self.client.get_categories(fw)
        except FamilyWallError as err:
            raise UpdateFailed(str(err)) from err
        return lists
