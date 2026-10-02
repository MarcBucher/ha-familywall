"""Minimal async client for the (unofficial) FamilyWall web API.

Ported from https://github.com/ryanhunt/familywall-api (src/client.ts):
form-encoded POSTs to https://api.familywall.com/api/<endpoint>, session via
JSESSIONID cookie mirrored into the ``tokencsrf`` header, results in
``a00.r.r``, errors in ``a00.ex``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://www.familywall.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}


class FamilyWallError(Exception):
    """Generic FamilyWall API error."""


class FamilyWallAuthError(FamilyWallError):
    """Login failed."""


@dataclass
class FamilyWallItem:
    """A single list item."""

    id: str
    text: str
    completed: bool
    quantity: str | None = None
    # ISO timestamp of the last change (e.g. when it was checked off); sortable as string.
    modified: str = ""


@dataclass
class FamilyWallList:
    """A list with its items."""

    id: str
    name: str
    type: str | None = None
    items: list[FamilyWallItem] = field(default_factory=list)


def _get_str(value: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return str(candidate)
    return None


def _get_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "checked", "complete", "completed")
    return value == 1


def _list_type(raw: str | None) -> str | None:
    """Normalize FamilyWall list types (e.g. SHOPPING_LIST, TODOS)."""
    if not raw:
        return None
    upper = raw.upper()
    if upper.startswith("SHOPPING"):
        return "shopping"
    if upper.startswith("TODO"):
        return "todo"
    return raw.lower()


def _api_error(call: Any) -> str | None:
    """Return the error message of an ``aXX`` call result, if any."""
    if not isinstance(call, dict):
        return "malformed response"
    for key in ("ex", "un"):
        if key in call:
            err = call[key]
            while isinstance(err, dict) and isinstance(err.get(key), dict):
                err = err[key]
            if isinstance(err, dict):
                return str(err.get("message") or err)
            return str(err)
    if not isinstance(call.get("r"), dict):
        return "response without result"
    return None


def _parse_item(value: dict[str, Any]) -> FamilyWallItem | None:
    item_id = _get_str(value, ["metaId", "taskId", "id"])
    text = _get_str(value, ["text", "name", "title"])
    if not item_id or text is None:
        return None
    completion = next(
        (value[k] for k in ("complete", "completed", "checked", "isChecked") if k in value),
        None,
    )
    quantity = value.get("quantity")
    return FamilyWallItem(
        id=item_id,
        text=text,
        completed=_get_bool(completion),
        quantity=str(quantity) if isinstance(quantity, (str, int, float)) and quantity != "" else None,
        modified=_get_str(value, ["modifDate", "lastActionDate", "creationDate"]) or "",
    )



class FamilyWallClient:
    """FamilyWall API client."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        # The session needs its own cookie jar: besides JSESSIONID, FamilyWall's AWS
        # load balancer sets AWSALB stickiness cookies; without them later calls land
        # on a backend that does not know the session ("ruleset NOAUTHENT").
        self._session = session
        self._email = email
        self._password = password
        self._jsessionid: str | None = None
        self._login_lock = asyncio.Lock()

    async def _post(self, endpoint: str, body: dict[str, Any]) -> aiohttp.ClientResponse:
        headers = dict(_HEADERS)
        if self._jsessionid:
            headers["tokencsrf"] = self._jsessionid
        data = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in body.items()}
        return await self._session.post(
            f"{API_BASE_URL}/{endpoint}",
            data=data,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def login(self) -> None:
        """Log in and store the session id."""
        async with self._login_lock:
            self._jsessionid = None
            for _ in range(3):
                resp = await self._post(
                    "log2in",
                    {
                        "partnerScope": "Family",
                        "a01call": "log2get",
                        "transactional": True,
                        "a00generateAutologinToken": True,
                        "a00identifier": self._email,
                        "a00password": self._password,
                    },
                )
                async with resp:
                    cookie = resp.cookies.get("JSESSIONID")
                    try:
                        json = await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        json = None
                call = json.get("a00") if isinstance(json, dict) else None
                if isinstance(call, dict) and (error := _api_error(call)):
                    raise FamilyWallAuthError(f"FamilyWall login failed: {error}")
                token = call["r"]["r"].get("tokenCsrf") if isinstance(call, dict) and isinstance(call["r"].get("r"), dict) else None
                if token or (cookie is not None and cookie.value):
                    self._jsessionid = token or cookie.value
                    break
            if not self._jsessionid:
                raise FamilyWallAuthError("FamilyWall login returned no session")
            # The web client performs these two calls right after login.
            for endpoint, body in (
                ("webset", {"partnerScope": "Family", "var": "a", "value": "t"}),
                ("webget", {"partnerScope": "Family", "var": "a"}),
            ):
                async with await self._post(endpoint, body) as resp:
                    await resp.read()

    async def _call(self, endpoint: str, body: dict[str, Any], *, retry: bool = True) -> Any:
        """Call an endpoint and return ``a00.r.r``; re-login once on failure."""
        if not self._jsessionid:
            await self.login()
        try:
            async with await self._post(endpoint, body) as resp:
                status = resp.status
                try:
                    json = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    json = None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise FamilyWallError(f"{endpoint}: {err}") from err

        call = json.get("a00") if isinstance(json, dict) else None
        error = _api_error(call)
        if status >= 400 or error:
            if retry:
                _LOGGER.debug("FamilyWall %s failed (HTTP %s: %s), re-login and retry", endpoint, status, error)
                await self.login()
                return await self._call(endpoint, body, retry=False)
            raise FamilyWallError(f"{endpoint} failed (HTTP {status}): {error}")
        return call["r"].get("r")

    async def get_lists(self) -> list[FamilyWallList]:
        """Return all lists (without items)."""
        result = await self._call("taskgettasklists", {"partnerScope": "Family"})
        entries: Any = result
        if isinstance(result, dict):
            entries = next(
                (result[k] for k in ("lists", "taskLists", "tasklists", "results") if isinstance(result.get(k), list)),
                [],
            )
        lists = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            list_id = _get_str(entry, ["metaId", "taskListId", "listId", "id"])
            name = _get_str(entry, ["name", "title"])
            if list_id and name is not None:
                lists.append(
                    FamilyWallList(list_id, name, _list_type(_get_str(entry, ["type", "taskListType"])))
                )
        return lists

    async def get_items(self, list_id: str) -> list[FamilyWallItem]:
        """Return the items of a list."""
        result = await self._call("tasklist", {"partnerScope": "Family", "a00listId": list_id})
        values: Any = []
        if isinstance(result, list):
            values = result
        elif isinstance(result, dict):
            meta = result.get("list") or result.get("taskList") or result
            for key in ("items", "tasks", "listItems"):
                if isinstance(result.get(key), list):
                    values = result[key]
                    break
                if isinstance(meta, dict) and isinstance(meta.get(key), list):
                    values = meta[key]
                    break
        items = []
        for value in values:
            if isinstance(value, dict) and (item := _parse_item(value)) is not None:
                items.append(item)
        return items

    # Write calls follow the official web app (startupmodule.js): `taskcreate` has no
    # list parameter and always files into the default to-do list, so items are
    # created and edited via `taskcreate2` / `taskupdate2`, which take the task's
    # fields inline (a00taskListId, a00text, ...).

    async def add_item(self, list_id: str, text: str) -> None:
        """Add an item to a list."""
        await self._call(
            "taskcreate2",
            {"partnerScope": "Family", "a00taskListId": list_id, "a00text": text},
        )

    async def rename_item(self, list_id: str, item_id: str, text: str) -> None:
        """Change an item's text."""
        await self._call(
            "taskupdate2",
            {
                "partnerScope": "Family",
                "a00taskId": item_id,
                "a00metaId": item_id,
                "a00taskListId": list_id,
                "a00text": text,
            },
        )

    async def set_completed(self, item_id: str, completed: bool) -> None:
        """Mark an item as completed / not completed."""
        await self._call(
            "taskmark",
            {"partnerScope": "Family", "a00taskId": item_id, "a00complete": completed},
        )

    async def delete_item(self, item_id: str) -> None:
        """Delete an item."""
        await self._call("taskdelete", {"partnerScope": "Family", "a00taskId": item_id})
