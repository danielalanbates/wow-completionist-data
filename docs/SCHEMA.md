# Schema (version 2)

The machine-checked version is `tools/cgdata/schema.py`; `tools/validate.py` applies it to every record. All keys
listed here are always present (a missing value is `null` or `[]`) unless marked *optional*. Unknown keys are an
error, so additions go through a schema version bump.

Version 2 (2026-11-10) added `confidence` to every located point, `read_as` / `read_by` / `check` to wiki
coordinate sources, `replaces` to DB2 turn-in pins, `variants` and `id_conflict` to quests, fixed spellings for
`faction`, `classes` and `races`, and per-point correction marks on NPCs and objects.

## Files

| Path | Content |
|---|---|
| `data/meta.json` | schema version, sources (wiki revision range, pages used, DB2 build and tables per client, map build), how coordinates were read (`coordinate_reading`), counts |
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
  * `{"type": "wiki", "page": <title>, "revid": <id>, "via": <how>, "read_as", "read_by", "check"}` with `via`:
    `questbox` (a `{{co}}` in the quest page's start/end field), `objective` (a `{{co}}` on the objective bullet),
    `entity-page` (the linked NPC / object / place page), `item-source` (the page of a mob or object the item
    drops from; `item_page` names the item).
  * `{"type": "db2", "table": "QuestPOIBlob", "build": <build>, "blob": <id>, "via": <how>}` (retail only) with
    `via`: `turn-in-pin` (the client's turn-in marker, ObjectiveIndex -1), `objective-area` (the objective's map
    area, matched through QuestObjective), `objective-area-by-index` (matched by the objective's position in the
    quest log; weaker). The point is the mean of the blob's points; most turn-in blobs are a single point.
  * `{"type": "correction", "correction": <id>}` - set by `corrections/`.
* `exact_version` - `true` when the point was written for this client's game version and no Blizzard position
  for the same NPC contradicts it: DB2 points and corrections; on retail a row read on the retail map; on MoP an
  `{{Npclocations}}` row badged with an expansion MoP has (the addon's strict rule); on Classic clients a Classic
  page, a `(Classic)` zone, a badged row, or a row whose Classic-map reading matched a Blizzard position. `false`
  means the point was carried over from another version through world coordinates (right only if the NPC stands
  in the same place in both versions, which nothing shippable confirms for most NPCs), or a Blizzard position more
  than 50 yd away contradicts it. `null` when there are no points.
* `confidence` - how far to trust the point, `null` when there are no points:
  * `high`: Blizzard data for this client (DB2 pins and objective areas), a correction, or a wiki point within
    50 yd of a Blizzard position that holds for this client: the client's own flight points (TaxiNodes) for a
    flight master; on retail and MoP a retail turn-in pin of the same NPC; on Classic clients a retail turn-in pin
    only when the row was read as Classic-map numbers (then the NPC has not moved since).
  * `medium`: no Blizzard position to compare, and either written for this version (`exact_version` true) or, on
    a Classic client, retail numbers that a turn-in pin confirmed (the numbers are right; the NPC may still have
    moved in Cataclysm or later).
  * `low`: more than 50 yd from such a Blizzard position (`coord_source.check.yards` says how far); carried over
    from another version with no check; an untagged row with no check whose retail-map and Classic-map readings
    are more than 50 yd apart (either could be right); or unchecked in a zone where more than a quarter of the
    checked rows disagree with Blizzard (a zone-wide stale offset, e.g. The Ringing Deeps).

Wiki coordinate sources also say how the numbers were read and checked:

* `read_as` - the map set the numbers were read on: `retail`, `classic` (the pre-Cataclysm map), `tbc`, `forever`.
* `read_by` - why: `tag` (the zone or page says the version: `(Classic)`, `(Burning Crusade)`, `(Forever)`, a
  Classic page), `check` (a Blizzard position for the same NPC agreed with this reading, see below),
  `zone-default` (no position for this row; its zone's checked rows decided), `default` (nothing to go on: retail,
  the wiki's convention).
* `check` (*optional*) - `{"against": "QuestPOIBlob" | "TaxiNodes", "build", "id" (blob or node id), "yards",
  "quest" (for pins)}`: the nearest Blizzard position for this NPC inside the point's map that holds for this
  client, and its distance from the shipped point.

A DB2 turn-in pin that replaced a wiki end point carries `replaces`: `{"page", "revid", "via", "map", "x", "y",
"yards"}`, the wiki point it replaced and how far it was from the pin.

### How a wiki point becomes a client point

The zone name resolves to a uiMapID (the addon's `tools/wiki/wikimaps.py`: the client's map names, the addon's zone
aliases, "The " retry, zone maps before others), the point goes to world coordinates on the map the numbers were
written on and comes back on the client's map that contains it, preferring the same zone, then its parent zones.
Map geometry is UiMap + UiMapAssignment of the same build as the client's DB2 tables (`maps.json`).

Which map the numbers were written on: a tagged row says so. An untagged row is ambiguous, because the Warcraft
Wiki is retail-first but many pages still carry numbers read off the pre-Cataclysm map of a zone, and that varies
page by page inside one zone. So the export (`tools/cgdata/evidence.py`) reads every untagged row both ways and
compares each reading with Blizzard's own position of the same NPC: the retail turn-in pin (QuestPOIBlob with
ObjectiveIndex -1 and a single point) of every retail quest whose wiki ender is that page, or, for a `{{co}}` in a
quest page's own start/end field, that quest's pin (the start only when the giver is also the ender); and the
Classic Era and retail flight points (TaxiNodes) for flight-master pages. A reading within 50 yd of a position in
the row's own zone decides (`read_by: check`); both readings within 50 yd means the maps agree there; neither means
the row disagrees with Blizzard (`confidence` low). A row with no position takes its zone's default: Classic
numbers when at least three checked rows of that zone are Classic numbers and they outnumber the retail ones,
else retail. NPC page rows and quest-page rows are counted apart. `data/meta.json` `coordinate_reading` lists the
verdict counts and the zones read as Classic numbers (2026-11-10 export: Arathi Highlands and Dun Morogh for NPC
pages). These defaults replace the addon's hand-made per-zone list (docs/SOURCES.md).

On retail, a wiki end point more than 50 yd (world distance) from the quest's single-point turn-in pin is replaced
by the pin, and the wiki point is kept under `coord_source.replaces`.

## Quest (`data/<client>/quests/`)

| Key | Type | Meaning |
|---|---|---|
| `id` | int | quest id (the client's QuestV2 id) |
| `name` | string | in-game name (wiki `name`, else the page title without its `(...)` suffix) |
| `flavors` | [string] | every client this quest id belongs to under the membership rules below |
| `faction` | string | `Alliance`, `Horde`, `Both` (also for the wiki's "neutral"), or one of `Aldor`, `Scryers`, `Kyrian`, `Necrolord`, `Night Fae`, `Venthyr` |
| `level`, `min_level` | int / null | wiki `level` (null when not a plain positive number, e.g. scaling) and `levelreq` |
| `type` | string / null | wiki `type`: `Daily`, `Weekly`, `Dungeon`, `World Quest`, `Bonus Objective`, ... |
| `category` | string / null | the wiki quest-log category (a zone, class, profession, holiday, campaign...) |
| `zone_map`, `zone_map_source` | int / null, string / null | home map: `category` when the category is a map, else `coords` (the zone of the first located endpoint) |
| `classes`, `races` | [string] | class / race limits from the wiki (empty = none), in the in-game spelling (`Death Knight`, `Blood Elf`, `Mag'har Orc`); the allowed values are in `tools/cgdata/names.py` |
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
| `variants` | [variant] | *optional*: the other faction's version when the wiki gives this id to an Alliance page and a Horde page (faction twins); see below |
| `id_conflict` | [object] | *optional*: `{"page", "revid", "name", "faction"}` of other wiki pages that give this id to a differently named quest on this client; which one is right is not decidable from wiki + DB2 |
| `corrections` | [string] | *optional*: ids of the corrections applied to this record |

**Endpoint:** `kind` (`npc`, `object`, `item`, `place`, `quest`, `auto`, `unknown`), `ids` (game ids from the wiki's
external links; several when a page covers several spawns or versions), `name`, `page` (the linked wiki page),
`faction` (`Alliance`/`Horde` when the wiki marks the entry with a faction icon), `coords`, `coord_source`,
`exact_version`, `confidence`. On retail an `end` endpoint without wiki points takes the client's turn-in pin, and
one more than 50 yd from it is replaced by the pin.

**Objective:** `index` (1-based bullet number), `kind` (`kill`, `item`, `talk`, `use`, `progress`, `object`,
`other`, `provided` = an item the quest gives you), `text`, `count`, `optional`, `target` (`{"kind", "ids", "name",
"page"}` or null), `coords`, `coord_source`, `exact_version`, `confidence`; DB2 objectives also have
`db2_objective` (QuestObjective id) and `db2_type`.

**Variant** (faction twins): every quest field except `id`, `flavors`, `variants`, `id_conflict`, with `source`
`{"wiki": {"page", "revid"}}`. The record itself is the best-ranked page (version preference, then newest revision);
its `faction` and each variant's `faction` say which side each version is for. Pick the one whose `faction`
matches the player. Either both versions really share the id in the game, or the wiki has one of the two ids
wrong; wiki + DB2 cannot tell which.

**Membership** (`flavors`, and which records a client folder holds) uses the addon's rules
(`gen_wiki_guides.membership`, `docs/WIKI_DATA_SPEC.md` 6 in the addon): the id is in the client's QuestV2; the page
is not RemovedFromBeta/Alpha/PTR, Season of Discovery, or Forever-only (except on `forever`); it was not removed at
or before the client's version (`{{Classic only|patch=}}`, `{{Removed|patch=}}`, `==Patch changes==`); and its
added patch fits the client. When an id has several pages (`(Classic)`, `(BC Classic)` twins) each client takes the
page written for it, so the same id can carry different data in different client folders. World quests, callings
and emissary quests are included here (the addon's guides leave them out). `questv2.json` lists the client's ids
that have a wiki page but fail these rules, with the reason; ids with no wiki page at all are the rest.

Several pages for one id: pages whose names match (the same name, or near-equal such as "Ursangous' Paw" and
"Ursangous's Paw") are versions of one quest and the rule above picks one. An id that three or more differently
named pages claim (counted over every page, on any client) is a placeholder or copied id on the wiki (788 is on
seventeen unrelated pages) and is left out, with the reason `ambiguous id: ...` in `questv2.json`. Otherwise the
best-ranked page is the record; an Alliance page and a Horde page become the record and its `variants`; any other
differently named page is listed in `id_conflict` and `tools/validate.py` warns.

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
* `faction` (*optional*): ids that apply to one faction only: the ones the wiki marks with a faction icon, and, on a
  quest both factions take, linked quests that are themselves Alliance-only or Horde-only (their own page's
  faction, or an `(Alliance)` / `(Horde)` title). Filter by the player's faction first, then drop empty groups:
  `{{Alliance}} [[A]] & [[B]]<br>{{Horde}} [[C]]` becomes `[[A], [B, C]]` with A and B Alliance, C Horde, which is
  A and B for Alliance and C for Horde. When a quest both factions take lists exactly one Alliance-only and one
  Horde-only group (`[[Brutal Politics]] <br> [[Magram Alliance]]`), the two become one group: each faction needs
  its own, not both.
* `basis`: how sure the split is. `none` (no previous quest), `single` (one link), `explicit` (several links joined
  by words: `,` / `and` / `&` = all of them, `or` / `/` / `one of` / an Alliance-Horde pair = any one of them),
  `list` (several links separated only by line breaks: read as all of them; the wiki is ambiguous here).
* `wiki_text` (*optional*): the plain text of the wiki `previous` field, when it has more than one link or links that
  did not resolve. `unresolved_links` (*optional*): links that are not a quest of this client (a quest from another
  version, a reputation, a non-quest page).

How the split is made (`tools/cgdata/prereqs.py`, tested in `tests/test_prereqs.py`): the questbox `previous` field
is read from the raw wikitext; a parenthesis right after a link qualifies that link; a prerequisite whose own page
says in its first sentence that it "is a breadcrumb" moves from `required` to `breadcrumb`; every id is kept only
when the quest exists on the same client. When several pages claim the linked id, the link counts only if the
shipped record (or its variant, or the same quest's page for another version) is the linked page, or the shipped
quest is open to every faction the linking quest is; a one-faction quest that links the other faction's quest is
pointed at the same-named quest of its own faction (`X` -> `X (Horde)`) or, with none, the link stays unresolved.
`tools/validate.py` fails on any requirement no player can meet after the faction filter. The game's real rules
are server-side and not in client data, so these are the wiki's statements, not Blizzard's.

## NPC and object (`data/<client>/npcs/`, `data/<client>/objects/`)

The NPCs and objects that this client's quests, objectives and achievement criteria point at.

| Key | Type | Meaning |
|---|---|---|
| `key` | string | the wiki page title (unique) |
| `kind` | `npc` / `object` | |
| `ids` | [int] | creature or game object ids from the page's external links (may be several, may be empty) |
| `name` | string | page title without its `(...)` suffix |
| `coords` | [point] | every coordinate on the page that lands on this client's maps, each with `exact_version`, `confidence`, `via` (`location` = infobox, `npclocations` = a Locations row, `lead`, `body`, `correction`), `read_as`, `read_by`, `check` (*optional*) as for endpoints; a point set by a correction has `correction` (its id) |
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

**Location** (criteria and wiki criteria): `{"map", "x", "y", "via", "confidence"}` plus `quest` (via `quest-start`
/ `quest-end`: that quest's first located endpoint on this client) or `page`, `revid`, `exact_version` (via
`npc-page` / `object-page` / `place-page`). `null` when unknown. An achievement counts as located when any of its
criteria has a location.

## Mission (`data/retail/missions/`)

From GarrMission: `id`, `name`, `location`, `description`, `garrison_type` + `garrison_type_name` (2 Garrison
(Warlords of Draenor), 3 Class Hall (Legion), 9 War Campaign (Battle for Azeroth), 111 Covenant (Shadowlands)),
`mission_type`, `follower_type`, `max_followers`, `target_level`, `target_item_level`, `duration_s`, `travel_s`,
`cost`, `cost_currency`, `area_id`, `map_pos` (the mission table's UI position, not a world point), `source`.

## SQLite (`build/completionist.sqlite`)

`tools/build_db.py build` writes one table per record type plus flattened tables for queries: `quests` (with
`variants` = how many faction variants, `id_conflict` = the other pages' titles), `quest_variants`, `quest_flavors`,
`quest_endpoints` (first point of each start/end, with `read_as`, `read_by`, `check_against`, `check_yards`,
`exact_version`, `confidence`), `quest_points` (every point), `quest_objectives`, `quest_prereqs` (`class` = required
/ breadcrumb / optional / in_progress / inferred_from_next, `grp` = the required group), `quest_next`, `npcs` (npcs
and objects, `kind`), `npc_ids`, `npc_points`, `achievements`, `achievement_criteria` (`origin` db2 / wiki),
`missions`, `maps`, `questv2` (`status` wiki / excluded / no_wiki_page), `corrections_applied` (with the record
`key`), `meta`. The per-quest tables have a `variant` column: 0 is the record, 1.. its `variants`. Each main table
keeps the full corrected record in a `json` column. The build checks every corrected record against the schema and
refuses points off their map (`--lenient` logs instead); the cross-record checks are `tools/validate.py`.
