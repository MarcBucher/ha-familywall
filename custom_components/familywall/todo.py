"""FamilyWall lists as Home Assistant to-do entities.

Per selected list there is one entity for the whole list plus, because the HA to-do
card cannot group, one entity per category ("Ohne Kategorie" included) so a
dashboard can show one card per category like the FamilyWall app.
"""

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

from .api import FamilyWallError, FamilyWallItem, FamilyWallList
from .const import DOMAIN, MAX_COMPLETED_ITEMS
from .coordinator import FamilyWallConfigEntry, FamilyWallCoordinator

# Category key of the entity holding items without (known) category.
UNCATEGORIZED = ""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyWallConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the to-do entities for the selected lists."""
    coordinator = entry.runtime_data
    entities: list[FamilyWallTodoList] = []
    for list_id, fw in coordinator.data.items():
        entities.append(FamilyWallTodoList(coordinator, list_id, None))
        if fw.categories:
            entities.append(FamilyWallTodoList(coordinator, list_id, UNCATEGORIZED))
            entities.extend(
                FamilyWallTodoList(coordinator, list_id, cat.id) for cat in fw.categories
            )
    async_add_entities(entities)


def _visible_items(fw: FamilyWallList) -> list[FamilyWallItem]:
    """Items in app order: open ones grouped by category, then recently completed.

    Items without category come first, then the categories in their configured
    order; within a group the drag & drop position (higher sort index = higher up).
    """
    rank = {cat.id: pos for pos, cat in enumerate(fw.categories, start=1)}
    open_items = sorted(
        (item for item in fw.items if not item.completed),
        key=lambda item: (rank.get(item.category_id or "", 0), -item.sort_index),
    )
    completed = sorted(
        (item for item in fw.items if item.completed),
        key=lambda item: item.modified,
        reverse=True,
    )[:MAX_COMPLETED_ITEMS]
    return [*open_items, *completed]


class FamilyWallTodoList(CoordinatorEntity[FamilyWallCoordinator], TodoListEntity):
    """A FamilyWall list, or one category of it.

    Writes refresh immediately (not debounced) so that a follow-up call, e.g. an
    automation renaming and then removing an item, sees the new state.
    """

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
    )

    def __init__(
        self, coordinator: FamilyWallCoordinator, list_id: str, category: str | None
    ) -> None:
        """``category``: None = whole list, UNCATEGORIZED or a category id."""
        super().__init__(coordinator)
        self._list_id = list_id
        self._category = category
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = (
            f"{entry_id}_{list_id}"
            if category is None
            else f"{entry_id}_{list_id}_{category or 'none'}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="FamilyWall",
            manufacturer="FamilyWall",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._update_items()

    @property
    def _list(self) -> FamilyWallList | None:
        return self.coordinator.data.get(self._list_id)

    def _known_category(self, category_id: str | None) -> str:
        fw = self._list
        if fw and category_id and any(cat.id == category_id for cat in fw.categories):
            return category_id
        return UNCATEGORIZED

    @property
    def available(self) -> bool:
        fw = self._list
        if not super().available or fw is None:
            return False
        if self._category:
            return any(cat.id == self._category for cat in fw.categories)
        return True

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_items()
        super()._handle_coordinator_update()

    def _update_items(self) -> None:
        fw = self._list
        if fw is None:
            return
        if self._category is None:
            self._attr_name = fw.name
        elif self._category == UNCATEGORIZED:
            self._attr_name = f"{fw.name} Ohne Kategorie"
        else:
            cat = next((c for c in fw.categories if c.id == self._category), None)
            if cat is not None:
                self._attr_name = f"{fw.name} {cat.emoji} {cat.name}".replace("  ", " ")
        items = _visible_items(fw)
        if self._category is not None:
            items = [i for i in items if self._known_category(i.category_id) == self._category]
        self._attr_todo_items = [
            TodoItem(
                uid=item.id,
                summary=item.text,
                status=TodoItemStatus.COMPLETED if item.completed else TodoItemStatus.NEEDS_ACTION,
                description=f"Menge: {item.quantity}" if item.quantity else None,
            )
            for item in items
        ]

    def _item(self, uid: str | None) -> FamilyWallItem | None:
        fw = self._list
        return next((i for i in fw.items if i.id == uid), None) if fw and uid else None

    async def async_create_todo_item(self, item: TodoItem) -> None:
        if not item.summary or not item.summary.strip():
            raise HomeAssistantError("Eintrag darf nicht leer sein")
        try:
            await self.coordinator.client.add_item(
                self._list_id, item.summary.strip(), self._category or None
            )
        except FamilyWallError as err:
            raise HomeAssistantError(f"FamilyWall: {err}") from err
        await self.coordinator.async_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._item(item.uid)
        if current is None:
            raise HomeAssistantError("Eintrag nicht gefunden")
        client = self.coordinator.client
        completed = item.status == TodoItemStatus.COMPLETED
        try:
            if item.summary and item.summary.strip() and item.summary != current.text:
                await client.rename_item(self._list_id, current.id, item.summary.strip())
            if item.status is not None and completed != current.completed:
                await client.set_completed(current.id, completed)
        except FamilyWallError as err:
            raise HomeAssistantError(f"FamilyWall: {err}") from err
        await self.coordinator.async_refresh()

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        current = self._item(uid)
        if current is None:
            raise HomeAssistantError("Eintrag nicht gefunden")
        previous = self._item(previous_uid)
        if self._category is not None:
            # A category card keeps the item in its category.
            category_id = self._category or current.category_id
        else:
            # In the whole list, an item dropped below another one joins its category.
            category_id = (previous.category_id if previous else None) or current.category_id
        try:
            await self.coordinator.client.move_item(
                self._list_id, uid, previous.id if previous else None, category_id
            )
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
