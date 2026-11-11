# wow-completionist-data

An open database of World of Warcraft quests, quest givers and enders, NPCs, achievements and missions for five
game clients, built for quest routing. It is the data side of
[Completionist's Guide](https://github.com/danielalanbates/wow-completionist-guide), a free guide addon, and it is
meant to be used by any addon or tool.

| Client | Folder | Quests | QuestV2 ids in the client |
|---|---|---:|---:|
| Classic Era (1.15.x) | `data/era` | 3,299 | 4,807 |
| Burning Crusade Anniversary (2.5.x) | `data/tbc` | 5,021 | 6,160 |
| Mists of Pandaria Classic (5.5.x) | `data/mop` | 10,562 | 17,140 |
| Retail (12.x) | `data/retail` | 29,498 | 66,552 |
| WoW Forever (1.60.x) | `data/forever` | 3,486 | 6,616 |

How much of it has map coordinates, prerequisites and so on is counted in [docs/COVERAGE.md](docs/COVERAGE.md).
Short version: about half of all quest givers and enders have a map point; on Classic clients many of those points
were written for the current retail game, and the records say so (`exact_version: false`).

## Where the data comes from

Only two sources, both named on every record:

* **[Warcraft Wiki](https://warcraft.wiki.gg)** (CC BY-SA 4.0): quest names, givers, enders, objectives,
  prerequisites, chains, NPC and object locations, achievement criteria. Every record carries the wiki page title
  and the revision id it was read from.
* **Blizzard client data** (DB2 tables, exported by [wago.tools](https://wago.tools) at one pinned build per
  client): which client has which quest (`QuestV2`), retail quest map pins (`QuestPOIBlob` / `QuestPOIPoint`),
  retail quest objectives, achievements and their criteria, garrison/class hall/covenant missions, and the map
  geometry. Every record carries the table name and the build.

No emulator database, no other addon's database and no commercial guide was used. The research behind that choice,
with each related project's licence, is in [docs/SOURCES.md](docs/SOURCES.md).

## Layout

```
data/meta.json                      sources, builds, counts
data/<client>/quests/<range>.json   quests, bucketed by id (000000-000999.json, ...)
data/<client>/npcs/<range>.json     NPCs the client's records point at, bucketed by first NPC id
data/<client>/objects/<range>.json  game objects, the same way
data/<client>/achievements/...      mop and retail only (the other clients have no achievements)
data/<client>/missions/...          retail only (GarrMission)
data/<client>/maps.json             uiMapIDs with names and world rectangles (for coordinate conversion)
data/<client>/questv2.json          every quest id the client knows, and why the wiki rules exclude some
corrections/*.json                  community fixes, applied last by the build
tools/build_db.py                   export (maintainers) and build (anyone)
tools/validate.py                   checks + docs/COVERAGE.md
```

Each bucket file is ordinary JSON with **one record per line**, so a change to one quest is a one-line diff:

```json
{
 "flavor": "era",
 "kind": "quests",
 "bucket": "000000-000999",
 "count": 876,
 "records": [
{"id":5,"name":"Jitters' Growling Gut","flavors":["era","tbc","forever"],"faction":"Alliance", ...},
...
 ]
}
```

Coordinates are `{"map": uiMapID, "x": 0-100, "y": 0-100}` on that client's own maps, with the source of every
point (`coord_source`) and whether it was written for this game version (`exact_version`). The full field list is
in [docs/SCHEMA.md](docs/SCHEMA.md).

## Using it

Read the JSON directly (any language), or build the SQLite database:

```
python3 tools/build_db.py build            # -> build/completionist.sqlite (about 200 MB, gitignored)
python3 tools/build_db.py build --json     # also build/json/<client>/<kind>.json, one corrected file per kind
```

Python 3.9+ and nothing else. The build applies `corrections/` last, so the SQLite file and the merged JSON are the
corrected data. Example queries:

```sql
-- where do I pick up and hand in quest 783 on Classic Era?
select role, name, map, x, y, coord_type, exact_version from quest_endpoints
 where flavor = 'era' and quest_id = 783;

-- what has to be done before quest 6144? (grp: the ids in one group are alternatives)
select prereq_id, class, grp from quest_prereqs where flavor = 'era' and quest_id = 6144;
```

From an addon: generate a Lua table from the JSON at build time (the data is too large to parse in game). The
addon's generators will move to reading this repository; see [docs/HANDOFF.md](docs/HANDOFF.md).

## Fixing something

Found a wrong coordinate, a missing prerequisite or a quest that is not in the game? Add an entry to a file in
`corrections/` and open a pull request; [CONTRIBUTING.md](CONTRIBUTING.md) shows the format with examples. If the
mistake is on the Warcraft Wiki, please fix it there too, so the next export carries it for everyone.

```
python3 tools/validate.py                  # must say 0 errors
python3 -m unittest discover -s tests      # the test suite
```

## Licences

* Data (`data/`, `corrections/`, the coverage report): **CC BY-SA 4.0**, see [LICENSE-DATA](LICENSE-DATA) and
  [ATTRIBUTION.md](ATTRIBUTION.md). If you ship it, credit the Warcraft Wiki contributors and this project, and
  share your changes to the data under the same licence.
* Code (`tools/`, `tests/`): PolyForm Noncommercial 1.0.0 with a commercial-use rider, see [LICENSE](LICENSE).

World of Warcraft and Blizzard Entertainment are trademarks of Blizzard Entertainment, Inc. This project is not
affiliated with or endorsed by Blizzard Entertainment or by Warcraft Wiki.

Contact: help@batesai.org · https://batesai.org
