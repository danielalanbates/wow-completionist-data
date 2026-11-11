# Handoff (for the next maintainer or AI)

State as of the first build, 2026-11-10. Read this, then README.md, docs/SCHEMA.md and docs/COVERAGE.md.

## What exists

* `data/` for five clients: 51,866 quests (era 3,299, tbc 5,021, mop 10,562, retail 29,498, forever 3,486), the
  NPCs (29,945 records summed over clients) and objects (5,269) they point at, 18,137 achievements (mop 3,998, retail
  14,139), 1,757 retail missions, map tables and the clients' full QuestV2 id lists. 502 files, about 107 MB of
  JSON; the largest file is 1.3 MB. Wiki revisions 2019-08-26 .. 2026-11-07 (62,770 pages), DB2 builds in
  `data/meta.json`.
* `tools/build_db.py export` regenerates `data/` from the addon's caches; `build` turns `data/` + `corrections/`
  into `build/completionist.sqlite` (about 200 MB) and, with `--json`, `build/json/<client>/<kind>.json`.
* `tools/validate.py` (0 errors, 17 warnings: game ids that appear on two wiki pages) and `--coverage` for
  docs/COVERAGE.md + docs/coverage.csv. `tools/privacy_check.py` is the pre-commit gate.
* `tests/` (unittest, 29 tests): prerequisite parser, bucket files, JSON Pointer, corrections, validation of good and
  broken fixtures, SQLite build determinism, full validation of the shipped data, the privacy gate, the correction
  template.
* No corrections yet (`corrections/_example.json` is a template that is never applied).

Verified: running the export twice gives byte-identical `data/` (same checksum over all 502 files); the quest set
per client equals the addon's own generator output (`wiki.sqlite` `flavor_quests`) with 0 missing and 0 extra, apart
from the 2,856 retail world quests / callings / emissary quests the addon leaves out on purpose and this dataset
keeps. Measured costs on the 8 GB Mac: export 13-16 s and about 710 MB peak memory, validate 7 s / 66 MB,
build 7 s / 58 MB, tests about 20-30 s.

## How to rebuild

1. In the addon repository (github.com/danielalanbates/wow-completionist-guide), produce its gitignored inputs as its
   `tools/wiki/README.md` describes: `fetch_wiki.py`, `parse_wiki.py`, `fetch_titles.py` + `parse_wiki.py` again,
   `fetch_db2.py`; the extra DB2 tables this export reads come from
   `python3 tools/wiki/db2_fetch.py QuestPOIBlob QuestPOIPoint Achievement Achievement_Category Criteria CriteriaTree GarrMission -- mop retail`
   (wago returns 400 for tables a client does not have; that is recorded and fine). Map tables are
   `tools/maps_<client>.lua` (tools/gen_maps.py) and are already in the addon.
2. Here: `python3 tools/build_db.py export --addon <path to the addon checkout>` (or set `CG_ADDON_REPO`; the
   default looks for `../wow-completionist-guide`, then `../repo`). On the 8 GB machine prefix heavy runs with
   the shared `heavy.sh` lock.
3. `python3 tools/validate.py --coverage`, `python3 -m unittest discover -s tests`, `python3 tools/privacy_check.py`.
4. Review the diff (one line per record), commit.

The export opens the addon's SQLite files with `mode=ro&immutable=1` and never writes into the addon checkout.
It imports `tools/wiki/wikimaps.py`, `gen_wiki_guides.py` and `wikitext.py` by path, and builds a read-only twin
of `gen_wiki_guides.Gen` (no fallback guides, no SQL writes) to reuse its location methods (`page_rows`,
`page_points`, `coords_list`, `place`, `exact`). If the addon renames those, the export fails loudly.

## Plan: the addon's generators read this repository as their single input

Goal: one place where wiki and DB2 facts are turned into data; the addon only turns data into guides.

1. **Reader.** Add `tools/data_repo.py` to the addon: it locates this repository (env var or sibling folder), runs
   `tools/build_db.py build --json` here (or reads a release asset), and yields corrected records per client from
   `build/json/<client>/quests.json`, `npcs.json`, `achievements.json`.
2. **gen_wiki_guides.py** keeps its output format and drops its inputs: membership = the records present for the
   client (skip `type` world quest / calling / emissary as today); `A` steps from `start` (first located endpoint;
   `exact_version` replaces its 300-yd version check, which needed Questie-derived fallback points that cannot be
   shipped); `C` steps from `objectives` (QO = `index` when `objectives_source` is `wiki` and the retail objective
   count matches, as now); `T` from `end` (retail turn-in pins are already merged in); `PRE` = every id of
   `prerequisites.required` (a multi-id group is the existing ";" any-of) plus `inferred_from_next`; breadcrumbs and
   optional quests become notes, not gates. Diff the generated guides against today's: the expected changes are
   the quests where one "(optional)" covers several links, which stop gating (retail 27, mop 19, tbc 1), and
   quest 835 on era / tbc / forever, which gains its `{{quest|...}}` prerequisite.
3. **gen_spine.py / routing** need no change: they consume the same step lines.
4. **Achievements.** `tools/gen_completion_guides.py` keeps its DB2 criteria ticks and can take map points for
   quest / kill / object criteria from `criteria[].location`.
5. **Local-only extras stay in the addon.** `_gaps` guides (Questie / Blizzard POI points for quests without wiki
   pages) are not shippable data and remain gitignored there.
6. **Then move the wiki pipeline.** Once step 2 is merged, `tools/wiki/fetch_*.py` and `parse_wiki.py` can move into
   this repository so it is the only thing that reads the wiki; the addon then pins a tagged data release.
7. **Release.** Tag data releases (`data-YYYY.MM.DD`) and attach `completionist.sqlite` + the merged JSON as release
   assets so consumers do not need Python.

## Known gaps and open questions

* **Coordinates are the weak spot.** Starts located: era 46.7%, tbc 48.9%, mop 61.1%, retail 47.3%, forever 48.3%;
  written for the client's own version: 15.4%, 13.1%, 2.3%, 47.3%, 15.0%. The wiki simply has no `{{co}}` on most
  NPC pages (97% of era quests' start-NPC pages were fetched; about 42% carry coordinates). Classic clients have no
  Blizzard coordinate table to fall back on, and every complete open source of Classic positions is GPL or NC
  (docs/SOURCES.md). Fix path: wiki edits and in-game corrections.
* **MoP `exact_version` is strict** (2.3%) because the addon's rule only trusts badged `{{Npclocations}}` rows
  there. MoP Classic uses post-Cataclysm maps, so retail-page points are right in zones that did not change after
  5.x; a per-zone allow list would raise that number honestly. Not done: it needs zone-by-zone checking.
* **Prerequisites are the wiki's statements**, parsed from free text. 418 quests (all clients summed) list several
  links separated only by line breaks (`basis: "list"`, read as all-of; some are really either/or, e.g. Classic
  "The Tome of Nobility" lists its Stormwind and Ironforge versions, which look like alternatives). Breadcrumbs are only
  recognised from the prerequisite page's first sentence or an explicit "(breadcrumb)".
* **Retail QuestV2 ids without a wiki page: 31,662** (mostly hidden tracking quests). They could be added as
  DB2-only stubs (id + POI pins, no name) if a consumer needs them.
* `parse_wiki.py` in the addon reports 2,488 pages that embed `{{Questbox}}` but whose box it could not parse
  (`questbox_missing_box`); some may be real quests missing here.
* Retail map geometry is from build 12.1.0.69382 while the retail DB2 build is 12.1.5.70783: 26 of 45,132 retail POI
  blobs sit on maps that file lacks and 77 fall off their map; those are dropped. Regenerating the addon's
  `maps_retail.lua` from 12.1.5 would recover them.
* Achievement criteria locations are thin (retail 9.5% of criteria): only quest, kill-creature and use-object
  criteria and wiki criteria linking to located pages can be placed.
* Addon repository observation (not changed from here): its `LICENSE` starts with a stray one-word first line
  before the copyright line.

## Publishing (main session)

This repository has no remote. To publish: create `danielalanbates/wow-completionist-data` on GitHub, add it as
`origin`, push `main`. Every file is far below GitHub's 50 MB warning size, so no Git LFS is needed. Run
`python3 tools/privacy_check.py` before every push.
