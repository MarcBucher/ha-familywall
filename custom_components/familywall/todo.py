"""FamilyWall lists as Home Assistant to-do entities.

One entity per selected list, in app order. The categories are exposed as attributes
(``categories``, ``item_categories``) so the bundled ``familywall-list-card`` can show
them as headings; ``familywall.add_item`` / ``familywall.move_item`` accept a category.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FamilyWallError, FamilyWallItem, FamilyWallList
from .const import DOMAIN, MAX_COMPLETED_ITEMS
from .coordinator import FamilyWallConfigEntry, FamilyWallCoordinator

ATTR_CATEGORY_ID = "category_id"
ATTR_ITEM = "item"
ATTR_PREVIOUS_UID = "previous_uid"
ATTR_UID = "uid"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyWallConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one to-do entity per selected list."""
    coordinator = entry.runtime_data
    async_add_entities(FamilyWallTodoList(coordinator, list_id) for list_id in coordinator.data)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "add_item",
        {
            vol.Required(ATTR_ITEM): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional(ATTR_CATEGORY_ID): vol.Any(None, cv.string),
        },
        "async_add_item_with_category",
    )
    platform.async_register_entity_service(
        "move_item",
        {
            vol.Required(ATTR_UID): cv.string,
            vol.Optional(ATTR_PREVIOUS_UID): vol.Any(None, cv.string),
            vol.Optional(ATTR_CATEGORY_ID): vol.Any(None, cv.string),
        },
        "async_move_item_to_category",
    )


def _visible_items(fw: FamilyWallList) -> list[FamilyWallItem]:
    """Items in app order: open ones grouped by category, then recently completed.

    Items without (known) category come first, then the categories in their
    configured order; within a group the drag & drop position (higher sort index =
    higher up).
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
    """A FamilyWall list.

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
    # Only needed live by the card; keep them out of the recorder.
    _unrecorded_attributes = frozenset({"categories", "item_categories"})

    def __init__(self, coordinator: FamilyWallCoordinator, list_id: str) -> None:
        super().__init__(coordinator)
        self._list_id = list_id
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{list_id}"
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

    @property
    def available(self) -> bool:
        return super().available and self._list is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fw = self._list
        if fw is None:
            return {}
        known = {cat.id for cat in fw.categories}
        return {
            "categories": [
                {"id": cat.id, "name": cat.name, "emoji": cat.emoji} for cat in fw.categories
            ],
            "item_categories": {
                item.uid: self._item_category.get(item.uid)
                for item in self._attr_todo_items or []
                if self._item_category.get(item.uid) in known
            },
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_items()
        super()._handle_coordinator_update()

    def _update_items(self) -> None:
        fw = self._list
        if fw is None:
            return
        self._attr_name = fw.name
        items = _visible_items(fw)
        self._item_category = {item.id: item.category_id for item in items}
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

    def _check_category(self, category_id: str | None) -> str | None:
        """Validate a category id; None and "" (= no category) pass through."""
        fw = self._list
        if category_id and not (fw and any(cat.id == category_id for cat in fw.categories)):
            raise HomeAssistantError(f"Unbekannte Kategorie: {category_id}")
        return category_id

    async def _write(self, call) -> None:
        try:
            await call
        except FamilyWallError as err:
            raise HomeAssistantError(f"FamilyWall: {err}") from err
        finally:
            await self.coordinator.async_refresh()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        if not item.summary or not item.summary.strip():
            raise HomeAssistantError("Eintrag darf nicht leer sein")
        await self._write(self.coordinator.client.add_item(self._list_id, item.summary.strip()))

    async def async_add_item_with_category(
        self, item: str, category_id: str | None = None
    ) -> None:
        """Service familywall.add_item."""
        if not item.strip():
            raise HomeAssistantError("Eintrag darf nicht leer sein")
        category = self._check_category(category_id) or None
        await self._write(self.coordinator.client.add_item(self._list_id, item.strip(), category))

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._item(item.uid)
        if current is None:
            raise HomeAssistantError("Eintrag nicht gefunden")
        client = self.coordinator.client
        completed = item.status == TodoItemStatus.COMPLETED

        async def update() -> None:
            if item.summary and item.summary.strip() and item.summary != current.text:
                await client.rename_item(self._list_id, current.id, item.summary.strip())
            if item.status is not None and completed != current.completed:
                await client.set_completed(current.id, completed)

        await self._write(update())

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        """Standard move: an item joins the group it is dropped into.

        Dropped below another item it takes that item's category; dropped on top it
        lands in the first group, the items without category.
        """
        if self._item(uid) is None:
            raise HomeAssistantError("Eintrag nicht gefunden")
        previous = self._item(previous_uid)
        category_id = (previous.category_id or "") if previous else ""
        await self._write(
            self.coordinator.client.move_item(
                self._list_id, uid, previous.id if previous else None, category_id
            )
        )

    async def async_move_item_to_category(
        self, uid: str, previous_uid: str | None = None, category_id: str | None = None
    ) -> None:
        """Service familywall.move_item: place below ``previous_uid`` in ``category_id``.

        ``category_id`` omitted keeps the item's category, "" removes it.
        """
        if self._item(uid) is None:
            raise HomeAssistantError("Eintrag nicht gefunden")
        previous = self._item(previous_uid)
        category = self._check_category(category_id)
        await self._write(
            self.coordinator.client.move_item(
                self._list_id, uid, previous.id if previous else None, category
            )
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        async def delete() -> None:
            for uid in uids:
                await self.coordinator.client.delete_item(uid)

        await self._write(delete())
