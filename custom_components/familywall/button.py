"""Button to refresh FamilyWall immediately."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FamilyWallConfigEntry, FamilyWallCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyWallConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the refresh button."""
    async_add_entities([FamilyWallRefreshButton(entry.runtime_data)])


class FamilyWallRefreshButton(CoordinatorEntity[FamilyWallCoordinator], ButtonEntity):
    """Reload all lists from FamilyWall now instead of waiting for the next poll."""

    _attr_has_entity_name = True
    _attr_name = "Jetzt aktualisieren"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: FamilyWallCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="FamilyWall",
            manufacturer="FamilyWall",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        # Must stay pressable after a failed poll, that's when it's needed most.
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
