"""FamilyWall lists as Home Assistant to-do entities."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FamilyWallError
from .const import DOMAIN, MAX_COMPLETED_ITEMS
from .coordinator import FamilyWallConfigEntry, FamilyWallCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyWallConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one to-do entity per selected list."""
    coordinator = entry.runtime_data
    async_add_entities(FamilyWallTodoList(coordinator, list_id) for list_id in coordinator.data)


class FamilyWallTodoList(CoordinatorEntity[FamilyWallCoordinator], TodoListEntity):
    """A FamilyWall list.

    Writes refresh immediately (not debounced) so that a follow-up call, e.g. an
    automation renaming and then removing an item, sees the new state.
    """

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: FamilyWallCoordinator, list_id: str) -> None:
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{list_id}"
        self._attr_name = coordinator.data[list_id].name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="FamilyWall",
            manufacturer="FamilyWall",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._update_items()

    @property
    def available(self) -> bool:
        return super().available and self._list_id in self.coordinator.data

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_items()
        super()._handle_coordinator_update()

    def _update_items(self) -> None:
        fw = self.coordinator.data.get(self._list_id)
        if fw is None:
            return
        self._attr_name = fw.name
        open_items = [item for item in fw.items if not item.completed]
        completed = sorted(
            (item for item in fw.items if item.completed),
            key=lambda item: item.modified,
            reverse=True,
        )[:MAX_COMPLETED_ITEMS]
        self._attr_todo_items = [
            TodoItem(
                uid=item.id,
                summary=item.text,
                status=TodoItemStatus.COMPLETED if item.completed else TodoItemStatus.NEEDS_ACTION,
                description=f"Menge: {item.quantity}" if item.quantity else None,
            )
            for item in (*open_items, *completed)
        ]

    def _find(self, uid: str | None) -> TodoItem | None:
        return next((i for i in self._attr_todo_items or [] if i.uid == uid), None)

    async def async_create_todo_item(self, item: TodoItem) -> None:
        if not item.summary or not item.summary.strip():
            raise HomeAssistantError("Eintrag darf nicht leer sein")
        try:
            await self.coordinator.client.add_item(self._list_id, item.summary.strip())
        except FamilyWallError as err:
            raise HomeAssistantError(f"FamilyWall: {err}") from err
        await self.coordinator.async_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._find(item.uid)
        if current is None:
            raise HomeAssistantError("Eintrag nicht gefunden")
        client = self.coordinator.client
        try:
            if item.summary and item.summary.strip() and item.summary != current.summary:
                await client.rename_item(self._list_id, current.uid, item.summary.strip())
            if item.status is not None and item.status != current.status:
                await client.set_completed(current.uid, item.status == TodoItemStatus.COMPLETED)
        except FamilyWallError as err:
            raise HomeAssistantError(f"FamilyWall: {err}") from err
        await self.coordinator.async_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        try:
            for uid in uids:
                await self.coordinator.client.delete_item(uid)
        except FamilyWallError as err:
            raise HomeAssistantError(f"FamilyWall: {err}") from err
        finally:
            await self.coordinator.async_refresh()
