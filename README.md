# FamilyWall for Home Assistant

Unofficial custom integration that exposes [FamilyWall](https://www.familywall.com) lists
(shopping, to-do, other) as Home Assistant **to-do entities**.

- Add items and check/uncheck them from Home Assistant (both directions).
- Changes made in the FamilyWall app show up within 60 seconds (cloud polling).
- Deleting or renaming items is not supported by the API – do that in the FamilyWall app.

> ⚠️ Uses FamilyWall's private web API (protocol ported from
> [ryanhunt/familywall-api](https://github.com/ryanhunt/familywall-api)). It may break when
> FamilyWall changes their backend. Your FamilyWall email/password are stored in the Home
> Assistant config entry.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repository URL, type **Integration**.
2. Install **FamilyWall**, then restart Home Assistant.
3. Settings → Devices & services → **Add integration** → *FamilyWall*.
4. Log in and pick the lists to expose (shopping lists are preselected).

## Entities

One `todo.familywall_<list name>` entity per selected list. Item quantities appear in the
item description.
