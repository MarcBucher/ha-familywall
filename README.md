# FamilyWall for Home Assistant

Unofficial custom integration that exposes [FamilyWall](https://www.familywall.com) lists
(shopping, to-do, other) as Home Assistant **to-do entities**.

- Add, check/uncheck, rename, delete and reorder (drag & drop) items from Home Assistant.
- Same order as the app: items without category first, then the categories in their
  configured order, within each group the drag & drop order (new items on top).
- Only the 20 most recently completed items per list are shown; older ones stay in FamilyWall.
- Changes made in the FamilyWall app show up within 60 seconds (cloud polling), or
  immediately with the **Jetzt aktualisieren** button.

> ⚠️ Uses FamilyWall's private web API (login/read protocol ported from
> [ryanhunt/familywall-api](https://github.com/ryanhunt/familywall-api); write calls
> `taskcreate2` / `taskupdate2` / `taskmark` / `taskdelete` as used by the official web app). It may break when
> FamilyWall changes their backend. Your FamilyWall email/password are stored in the Home
> Assistant config entry.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repository URL, type **Integration**.
2. Install **FamilyWall**, then restart Home Assistant.
3. Settings → Devices & services → **Add integration** → *FamilyWall*.
4. Log in and pick the lists to expose (shopping lists are preselected).

## Entities

- `todo.familywall_<list>`: the whole list.
- For lists with categories, additionally one entity per category, e.g.
  `todo.familywall_einkaufen_obst_gemuse`, plus `todo.familywall_<list>_ohne_kategorie`.
  The HA to-do card cannot group, so a dashboard can show one card per category. Items
  added in a category entity get that category.
- `button.familywall_jetzt_aktualisieren`: reload all lists now.

Item quantities appear in the item description. Categories added later in the app appear
after reloading the integration.
