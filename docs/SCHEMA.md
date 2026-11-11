# Schema (version 1)

The machine-checked version is `tools/cgdata/schema.py`; `tools/validate.py` applies it to every record. All keys
listed here are always present (a missing value is `null` or `[]`) unless marked *optional*. Unknown keys are an
error, so additions go through a schema version bump.

## Files

| Path | Content |
|---|---|
| `data/meta.json` | schema version, sources (wiki revision range, pages used, DB2 build and tables per client, map build), counts |
| `data/<client>/<kind>/<bucket>.json` | `{"flavor", "kind", "bucket", "count", "records": [...]}`, one record per line, sorted |
| `data/<client>/maps.json` | `{"flavor", "source", "fields", "maps": [[id, name, instance, topX, leftY, width, height, parent, type], ...]}` |
| `data/<client>/questv2.json` | `{"flavor", "table", "build", "count", "excluded": [{"id", "page", "revid", "reason"}], "ids": [...]}` |

Clients (`flavor`): `era` Classic Era 1.15.x, `tbc` Burning Crusade Anniversary 2.5.x, `mop` Mists of Pandaria
Classic 5.5.x, `retail` 12.x, `forever` WoW Forever 1.60.x. Each client's records use that client's own map ids and
coordinates.

Buckets: quests, achievements and missions by `id` in ranges of 1,000 (`000000-000999`); npcs and objects by their
first game id in ranges of 10,000 (`0000000-0009999`), records without an id in `no-id`.

## Coordinates

A point is `{"map": <uiMapID>, "x": <0-100>, "y": <0-100>}`: percent of the map's width and height from the top
left, the unit of `/way`, the in-game map and `C_Map`. One decimal. `map` is always listed in that client's
`maps.json`, which also carries each map's world rectangle (`topX`, `leftY`, `width`, `height`, world yards) so a
tool can convert: `worldX = topX - y/100 * height`, `worldY = leftY - x/100 * width`.

A list of points on an endpoint or objective holds up to four spawn points, all on one map. Next to it:

* `coord_source` - where the points came from, one of
  * `{"type": "wiki", "page": <title>, "revid": <id>, "via": <how>}` with `via`:
    `questbox` (a `{{co}}` in the quest page's start/end field), `objective` (a `{{co}}` on the objective bullet),
    `entity-page` (the linked NPC / object / place page), `item-source` (the page of a mob or object the item
    drops from; `item_page` names the item).
  * `{"type": "db2", "table": "QuestPOIBlob", "build": <build>, "blob": <id>, "via": <how>}` (retail only) with
    `via`: `turn-in-pin` (the client's turn-in marker, ObjectiveIndex -1), `objective-area` (the objective's map
    area, matched through QuestObjective), `objective-area-by-index` (matched by the objective's position in the
    quest log; weaker). The point is the mean of the blob's polygon points.
  * `{"type": "correction", "correction": <id>}` - set by `corrections/`.
* `exact_version` - `true` when the point was written for this client's game version: always on retail and for DB2
  points; on Classic clients only when it comes from a Classic page, a `(Classic)` zone or an `{{Npclocations}}`
  row badged with an expansion the client has. `false` means the wiki gave a position for another version (usually
  current retail) and it was carried over through world coordinates; it is right for anything that never moved and
  wrong for what did. `null` when there are no points.

How a wiki point becomes a client point (the addon's `tools/wiki/wikimaps.py`): the zone name resolves to a uiMapID
(the client's map names, the addon's zone aliases, "The " retry, zone maps before others), the point goes to world
coordinates on the map the wiki meant (`(Classic)` / `(Forever)` / `(Burning Crusade)` / `(alternate universe)`
pick the map set) and comes back on the client's map that contains it, preferring the same zone, then its parent
zones. A few zones whose wiki numbers are known to be Classic-map numbers (Badlands, Arathi Highlands, Swamp of
Sorrows, Felwood, Teldrassil) keep their numbers on Classic clients.

## Quest (`data/<client>/quests/`)

| Key | Type | Meaning |
|---|---|---|
| `id` | int | quest id (the client's QuestV2 id) |
| `name` | string | in-game name (wiki `name`, else the page title without its `(...)` suffix) |
| `flavors` | [string] | every client this quest id belongs to under the membership rules below |
| `faction` | string | `Alliance`, `Horde`, `Both`, or another wiki value (a covenant, `Scryers`, ...) |
| `level`, `min_level` | int / null | wiki `level` (null when not a plain positive number, e.g. scaling) and `levelreq` |
| `type` | string / null | wiki `type`: `Daily`, `Weekly`, `Dungeon`, `World Quest`, `Bonus Objective`, ... |
| `category` | string / null | the wiki quest-log category (a zone, class, profession, holiday, campaign...) |
| `zone_map`, `zone_map_source` | int / null, string / null | home map: `category` when the category is a map, else `coords` (the zone of the first located endpoint) |
| `classes`, `races` | [string] | class / race limits from the wiki (empty = none) |
| `profession` | string / null | wiki `profession` |
| `is_breadcrumb` | `"yes"` / `"optional"` / null | the quest page's lead sentence calls the quest a (optional) breadcrumb |
| `auto_accept` | bool | the wiki says the quest is accepted automatically |
| `start`, `end` | [endpoint] | quest givers and enders, in wiki order |
| `end_same_as_start` | bool | the wiki gives no ender (the template default: the giver), so `end` repeats `start` |
| `start_item` | object / null | `{"ids", "name", "page"}` of the item that starts the quest |
| `objectives_text` | string / null | the prose line of the wiki `==Objectives==` section |
| `objectives_source` | `"wiki"` / `"db2"` / null | where `objectives` came from (`db2`: retail QuestObjective / POI when the wiki has no bullets) |
| `objectives` | [objective] | one per objective bullet |
| `prerequisites` | object | see below |
| `next` | [int] | wiki `next` quests that exist on this client |
| `source` | object | `{"wiki": {"page", "revid"}, "db2": {"table": "QuestV2", "build"}}` |
| `corrections` | [string] | *optional*: ids of the corrections applied to this record |

**Endpoint:** `kind` (`npc`, `object`, `item`, `place`, `quest`, `auto`, `unknown`), `ids` (game ids from the wiki's
external links; several when a page covers several spawns or versions), `name`, `page` (the linked wiki page),
`faction` (`Alliance`/`Horde` when the wiki marks the entry with a faction icon), `coords`, `coord_source`,
`exact_version`. On retail an `end` endpoint without wiki points takes the client's turn-in pin.

**Objective:** `index` (1-based bullet number), `kind` (`kill`, `item`, `talk`, `use`, `progress`, `object`,
`other`, `provided` = an item the quest gives you), `text`, `count`, `optional`, `target` (`{"kind", "ids", "name",
"page"}` or null), `coords`, `coord_source`, `exact_version`; DB2 objectives also have `db2_objective`
(QuestObjective id) and `db2_type`.

**Membership** (`flavors`, and which records a client folder holds) uses the addon's rules
(`gen_wiki_guides.membership`, `docs/WIKI_DATA_SPEC.md` 6 in the addon): the id is in the client's QuestV2; the page
is not RemovedFromBeta/Alpha/PTR, Season of Discovery, or Forever-only (except on `forever`); it was not removed at
or before the client's version (`{{Classic only|patch=}}`, `{{Removed|patch=}}`, `==Patch changes==`); and its
added patch fits the client. When an id has several pages (`(Classic)`, `(BC Classic)` twins) each client takes the
page written for it, so the same id can carry different data in different client folders. World quests, callings
and emissary quests are included here (the addon's guides leave them out). `questv2.json` lists the client's ids
that have a wiki page but fail these rules, with the reason; ids with no wiki page at all are the rest.

### Prerequisites

```json
"prerequisites": {
  "required": [[6135], [6136]],
  "breadcrumb": [],
  "optional": [],
  "in_progress": [],
  "inferred_from_next": [],
  "basis": "explicit",
  "faction": {"456": "Alliance"},
  "wiki_text": "Duskwing, Oh How I Hate Thee... (Classic) & The Corpulent One (Classic)",
  "unresolved_links": 1
}
```

* `required`: groups that must all be done; the ids inside one group are alternatives (any one of them).
* `breadcrumb`: quests that lead to this one but are not needed for it.
* `optional`: quests the wiki marks `(optional)` (or `(both optional)`, `(all optional)`).
* `in_progress`: quests that only have to be in the quest log (`(in-progress)`).
* `inferred_from_next`: quests whose own `next` names this quest, when this quest names no prerequisite itself on
  this client. Usually the previous step of a chain; treat it as required if you need a single rule.
* `faction` (*optional*): ids the wiki marks with a faction icon. Filter by the player's faction first, then drop
  empty groups: `{{Alliance}} [[A]] & [[B]]<br>{{Horde}} [[C]]` becomes `[[A], [B, C]]` with A and B Alliance, C
  Horde, which is A and B for Alliance and C for Horde.
* `basis`: how sure the split is. `none` (no previous quest), `single` (one link), `explicit` (several links joined
  by words: `,` / `and` / `&` = all of them, `or` / `/` / `one of` / an Alliance-Horde pair = any one of them),
  `list` (several links separated only by line breaks: read as all of them; the wiki is ambiguous here).
* `wiki_text` (*optional*): the plain text of the wiki `previous` field, when it has more than one link or links that
  did not resolve. `unresolved_links` (*optional*): links that are not a quest of this client (a quest from another
  version, a reputation, a non-quest page).

How the split is made (`tools/cgdata/prereqs.py`, tested in `tests/test_prereqs.py`): the questbox `previous` field
is read from the raw wikitext; a parenthesis right after a link qualifies that link; a prerequisite whose own page
says in its first sentence that it "is a breadcrumb" moves from `required` to `breadcrumb`; every id is kept only
when the quest exists on the same client. The game's real rules are server-side and not in client data, so these
are the wiki's statements, not Blizzard's.

## NPC and object (`data/<client>/npcs/`, `data/<client>/objects/`)

The NPCs and objects that this client's quests, objectives and achievement criteria point at.

| Key | Type | Meaning |
|---|---|---|
| `key` | string | the wiki page title (unique) |
| `kind` | `npc` / `object` | |
| `ids` | [int] | creature or game object ids from the page's external links (may be several, may be empty) |
| `name` | string | page title without its `(...)` suffix |
| `coords` | [point] | every coordinate on the page that lands on this client's maps, each with `exact_version` and `via` (`location` = infobox, `npclocations` = a Locations row, `lead`, `body`) |
| `source` | object | `{"wiki": {"page", "revid"}}` |
| `corrections` | [string] | *optional* |

## Achievement (`data/mop/achievements/`, `data/retail/achievements/`)

| Key | Type | Meaning |
|---|---|---|
| `id`, `name`, `description`, `reward` | | from the client's Achievement table |
| `category` | object | `{"id", "path": ["Quests", "Eastern Kingdoms"]}` |
| `points`, `faction`, `flags` | | `faction`: `Both` / `Horde` / `Alliance` |
| `statistic`, `guild`, `account_wide` | bool | flag bits 0x1, 0x4000, 0x20000 |
| `criteria` | [criterion] | the leaves of the achievement's criteria tree, in tree order |
| `wiki` | object / null | `{"page", "revid", "category", "criteria": [{"text", "link", "quest", "location"}]}` |
| `source` | object | `{"db2": {"table": "Achievement", "build"}, "wiki": {...}}` (wiki *optional*) |

**Criterion:** `tree` (CriteriaTree id), `criteria` (Criteria id), `type` and `type_name` (`complete_quest` 27,
`kill_creature` 0, `earn_achievement` 8, `obtain_item` 36, `explore_area` 43, `use_object` 68; other types keep only
the number), `asset` (quest / creature / item / achievement / object id by type), `amount`, `text`, `location`.

**Location** (criteria and wiki criteria): `{"map", "x", "y", "via"}` plus `quest` (via `quest-start` /
`quest-end`: that quest's first located endpoint on this client) or `page`, `revid`, `exact_version` (via
`npc-page` / `object-page` / `place-page`). `null` when unknown. An achievement counts as located when any of its
criteria has a location.

## Mission (`data/retail/missions/`)

From GarrMission: `id`, `name`, `location`, `description`, `garrison_type` + `garrison_type_name` (2 Garrison
(Warlords of Draenor), 3 Class Hall (Legion), 9 War Campaign (Battle for Azeroth), 111 Covenant (Shadowlands)),
`mission_type`, `follower_type`, `max_followers`, `target_level`, `target_item_level`, `duration_s`, `travel_s`,
`cost`, `cost_currency`, `area_id`, `map_pos` (the mission table's UI position, not a world point), `source`.

## SQLite (`build/completionist.sqlite`)

`tools/build_db.py build` writes one table per record type plus flattened tables for queries: `quests`,
`quest_flavors`, `quest_endpoints` (first point of each start/end), `quest_points` (every point), `quest_objectives`,
`quest_prereqs` (`class` = required / breadcrumb / optional / in_progress / inferred_from_next, `grp` = the required
group), `quest_next`, `npcs` (npcs and objects, `kind`), `npc_ids`, `npc_points`, `achievements`,
`achievement_criteria` (`origin` db2 / wiki), `missions`, `maps`, `questv2` (`status` wiki / excluded /
no_wiki_page), `corrections_applied`, `meta`. Each main table keeps the full corrected record in a `json` column.
