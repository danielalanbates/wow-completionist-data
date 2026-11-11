# Handoff (for the next maintainer or AI)

State as of the second export, 2026-11-10 (schema version 2). Read this, then README.md, docs/SCHEMA.md and
docs/COVERAGE.md.

## What exists

* `data/` for five clients: 51,829 quests (era 3,296, tbc 5,018, mop 10,552, retail 29,480, forever 3,483), the
  NPCs (29,948 records summed over clients) and objects (5,269) they point at, 18,137 achievements (mop 3,998, retail
  14,139), 1,757 retail missions, map tables and the clients' full QuestV2 id lists. 502 files, about 116 MB of
  JSON; the largest file is 1.5 MB. Wiki revisions 2019-08-26 .. 2026-11-07 (62,924 pages), DB2 builds in
  `data/meta.json`.
* `tools/build_db.py export` regenerates `data/` from the addon's caches; `build` turns `data/` + `corrections/`
  into `build/completionist.sqlite` (about 200 MB) and, with `--json`, `build/json/<client>/<kind>.json`.
  `tools/fetch_db2.py` downloads UiMap, UiMapAssignment and TaxiNodes for the addon's pinned builds into `cache/db2/`
  (gitignored; the export uses them when their build matches the addon's `tools/db2/<client>/BUILD`).
* `tools/validate.py` (0 errors; warnings: 2,736 points more than 50 yd from a Blizzard position, 273 quests whose id
  another page also claims, 17 game ids on two wiki pages) and `--coverage` for docs/COVERAGE.md + docs/coverage.csv.
  `tools/privacy_check.py` is the pre-commit gate.
* `tests/` (unittest, 49 tests): prerequisite parser, buckets, JSON Pointer, corrections, validation of good and
  broken fixtures, SQLite build determinism and its record check, coordinate reading on a synthetic two-map zone,
  value normalisation, faction checks, full validation of the shipped data, regression checks for the cases the
  first review found (below), the privacy gate, the correction template.
* No corrections yet (`corrections/_example.json` is a template that is never applied).

Verified: running the export twice gives byte-identical `data/` (same checksum over all 502 files). The quest set per
client equals the addon's own generator output (`wiki.sqlite` `flavor_quests`) except the ids left out here as
ambiguous (era 3, tbc 3, mop 10, retail 14 of the addon's, forever 3) and the 2,856 retail world quests / callings
/ emissary quests the addon leaves out on purpose and this dataset keeps. Measured on the 8 GB Mac: export about
18 s and 775 MB peak memory, validate about 6 s, build about 12 s / 60 MB, tests about 22 s.

## What the second export changed (review of 2026-11-10)

1. **Coordinates are read row by row, not zone by zone.** The first export took the addon's `KEEP_NUMBERS` list
   (five zones whose wiki numbers are read as Classic-map numbers on Classic clients). Stale numbers vary page by
   page, so points were 200-660 yd off, e.g. era Ragnar Thunderbrew (Dun Morogh 46.8, 52.5, a Classic number,
   shipped converted to 39.7, 54.2) and Donova Snowden (Winterspring 31.0, 45.0, shipped at 36.4, 33.5), while in
   Arathi Highlands Skuerto and Apprentice Kryten have retail numbers and were kept. Now `tools/cgdata/evidence.py`
   reads every untagged row both ways against Blizzard's own positions of the same NPC (retail turn-in pins,
   TaxiNodes for flight masters) and zone defaults come from those checks (docs/SCHEMA.md#coordinates). All five
   cases above now ship right, with `confidence: "high"` / `"medium"`. The list was also calibrated against
   Questie-derived data (docs/SOURCES.md), so it is gone.
2. **Retail wiki end points no longer beat Blizzard's turn-in pin.** 1,011 wiki end points more than 50 yd from the
   quest's single-point pin were replaced by the pin (`coord_source.replaces` keeps the wiki point). The first
   COVERAGE.md blamed the pin for being an area centroid; turn-in blobs are single points (17,860 of them), and whole
   zones of wiki numbers are stale (The Ringing Deeps: +4.2 map units in x, map unchanged between 12.1.0 and 12.1.5).
   Retail points from Classic or `(Burning Crusade)` rows are `exact_version: false` now.
3. **Shared quest ids.** An id that 3+ differently named wiki pages claim is left out (19 ids, e.g. 788 on seventeen
   pages, 1, 8647); an Alliance page + Horde page pair ships as the record plus `variants` (era 8978 "Return to
   Mokvar" / "Return to Deliana"); other differently named claims are listed in `id_conflict`.
4. **Faction-aware prerequisites.** A quest both factions take that listed one Alliance-only and one Horde-only
   quest as both required (era 1386 "Assault on the Kolkar": Brutal Politics + Magram Alliance) now has one any-of
   group with `faction` tags. Links to a page that lost its id, and one-faction quests linking the other faction's
   quest, are resolved or left unresolved (counts in `data/meta.json` `prerequisite_split`). `tools/validate.py`
   fails on any requirement no player can meet; the shipped data has none.
5. **Values normalised**: faction (`neutral` -> `Both`, case), classes and races in the in-game spelling, as enums.
6. **Retail map geometry is from 12.1.5** (the retail DB2 build): The Underbelly (2613) changed its rectangle and six
   maps are new; POI blobs dropped for unknown maps went from 26 to 2, off-map from 77 to 74.
7. **Corrections**: the template's NPC example names one client (coordinates are per client); NPC point corrections
   mark the points instead of adding record-level keys; `corrections_applied` logs the record key; the build checks
   each corrected record's schema and coordinates and stops on a problem.

## How to rebuild

1. In the addon repository (github.com/danielalanbates/wow-completionist-guide), produce its gitignored inputs as its
   `tools/wiki/README.md` describes: `fetch_wiki.py`, `parse_wiki.py`, `fetch_titles.py` + `parse_wiki.py` again,
   `fetch_db2.py`; the extra DB2 tables this export reads come from
   `python3 tools/wiki/db2_fetch.py QuestPOIBlob QuestPOIPoint Achievement Achievement_Category Criteria CriteriaTree GarrMission -- mop retail`
   (wago returns 400 for tables a client does not have; that is recorded and fine).
2. Here: `python3 tools/fetch_db2.py --addon <path>` (UiMap, UiMapAssignment, TaxiNodes for the same builds into
   `cache/db2/`; skipped when already there). Without it the export falls back to the addon's `tools/maps_<client>.lua`
   (older map builds) and has no flight points to check against.
3. `python3 tools/build_db.py export --addon <path to the addon checkout>` (or set `CG_ADDON_REPO`; the default
   looks for `../wow-completionist-guide`, then `../repo`). On the 8 GB machine prefix heavy runs with the shared
   `heavy.sh` lock.
4. `python3 tools/validate.py --coverage`, `python3 -m unittest discover -s tests`, `python3 tools/privacy_check.py`.
5. Review the diff (one line per record), commit.

The export opens the addon's SQLite files with `mode=ro&immutable=1`, sets `sys.dont_write_bytecode`, and never
writes into the addon checkout. It imports `tools/wiki/wikimaps.py`, `gen_wiki_guides.py` and `wikitext.py` by path
and builds a read-only twin of `gen_wiki_guides.Gen` to reuse `page_rows`, `page_points`, `resolve_title`, `exact`,
`membership`, `VARIANT_PREF`, `SKIP_TYPES`, `pkey`. Placement (`Exporter.place_row`, adapted from
`wikimaps.Atlas.place` without `KEEP_NUMBERS`) and the version check (`exact_of`) live here. If the addon renames
those, the export fails loudly.

## Plan: the addon's generators read this repository as their single input

Goal: one place where wiki and DB2 facts are turned into data; the addon only turns data into guides.

1. **Reader.** Add `tools/data_repo.py` to the addon: it locates this repository (env var or sibling folder), runs
   `tools/build_db.py build --json` here (or reads a release asset), and yields corrected records per client from
   `build/json/<client>/quests.json`, `npcs.json`, `achievements.json`.
2. **gen_wiki_guides.py** keeps its output format and drops its inputs: membership = the records present for the
   client (skip `type` world quest / calling / emissary as today; pick the `variants` entry that matches the
   guide's faction); `A` steps from `start` (first located endpoint; `confidence` replaces its 300-yd version check,
   which needed Questie-derived fallback points that cannot be shipped: show `low` points as approximate);
   `C` steps from `objectives` (QO = `index` when `objectives_source` is `wiki` and the retail objective count
   matches, as now); `T` from `end` (retail turn-in pins are already merged in); `PRE` = every id of
   `prerequisites.required` after the faction filter (a multi-id group is the existing ";" any-of) plus
   `inferred_from_next`; breadcrumbs and optional quests become notes, not gates. Diff the generated guides against
   today's: expected changes are the "(optional)" multi-link quests that stop gating (retail 27, mop 19, tbc 1),
   quest 835 on era / tbc / forever (gains its `{{quest|...}}` prerequisite), the faction-merged prerequisites, the
   19 ambiguous ids that disappear, and Classic points that move (Dun Morogh and Arathi Highlands rows now read as
   Classic numbers, KEEP_NUMBERS zones without evidence now read as retail numbers).
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

* **Coordinates are the weak spot, and Classic clients most of all.** Starts located: era 46.8%, tbc 48.9%, mop
  61.1%, retail 47.3%, forever 48.3%; rated high or medium: 19.4%, 23.1%, 27.2%, 36.4%, 18.9%. The wiki has no
  `{{co}}` on most NPC pages, Classic clients have no Blizzard quest coordinates, and every complete open source of
  Classic positions is GPL or NC (docs/SOURCES.md). Fix path: wiki edits and in-game corrections, which the
  `confidence` field now points at (fix the `low` points first).
* **Rows without evidence are still guesses** (flagged `low`). Examples worth checking in game:
  * Burning Steppes, Helendis Riverhorn (wiki 85.8, 68.9) and Oralius (84.6, 68.6) at Morgan's Vigil. Burning
    Steppes' checked rows are mostly retail numbers (11 to 1), so these convert to about 98-99, 72 on the Classic
    map, its east edge; they are probably Classic numbers.
  * Dun Morogh is read as Classic numbers by default (6 checked rows to 3). Right for Branstock Khalder, Granis
    Swiftaxe (Anvilmar 28.6, 66.5 / Thunderbrew 47.3, 52.6), but Azar Stronghammer's 54.6, 50.4 is a retail number
    (converted it lands at 47.5, 52.1, in the Thunderbrew Distillery next to Ragnar), so his era point is now
    about 350 yd off.
  * Blasted Lands: the conversion is right for pages with retail numbers (Alexandra Constantine lands 2 yd from the
    Nethergarde flight point), but pre-Cataclysm pages carry Classic numbers that end up about 5.5 map units off
    (Daio 34, 50 -> 35.7, 55.4; Kum'isha 52, 36 -> 55.4, 40.1). With no Blizzard position for them they read as
    retail numbers (the zone's checked rows are 7 to 0 retail).
  * Winterspring: Donova Snowden is fixed by her pin; other Classic-only NPCs there have no evidence.
  * Points carried over from retail to Classic clients are right only if the NPC did not move in Cataclysm or later
    (2 of 78 era points with a retail pin are still more than 100 yd off for that reason: Archmage Angela Dosantos,
    Pozzik). Nothing shippable says which NPCs moved.
* **MoP `exact_version` is strict** (2.2% of starts) because the addon's rule only trusts badged
  `{{Npclocations}}` rows there; `confidence` is the better guide on MoP (retail pins check 2,072 MoP start points).
* **Prerequisites are the wiki's statements**, parsed from free text. 418 quests (all clients summed) list several
  links separated only by line breaks (`basis: "list"`, read as all-of; some are really either/or, e.g. Classic
  "The Tome of Nobility" lists its Stormwind and Ironforge versions). Breadcrumbs are only recognised from the
  prerequisite page's first sentence or an explicit "(breadcrumb)".
* **Faction twins and id conflicts**: 232 quests carry a `variants` entry and 273 an `id_conflict` list (summed over
  clients). Which page is right for a conflicted id needs an in-game check; a correction can then remove the wrong
  version.
* **Retail QuestV2 ids without a wiki page: 31,662** (mostly hidden tracking quests). They could be added as
  DB2-only stubs (id + POI pins, no name) if a consumer needs them.
* `parse_wiki.py` in the addon reports 2,488 pages that embed `{{Questbox}}` but whose box it could not parse
  (`questbox_missing_box`); some are real quests missing here. Pages without an `id` are missing too: the orc
  starter "Cutting Teeth" (widely known as quest 788) has no `id` in its questbox, so the 17 pages that do claim
  788 are all copies of a wrong id and 788 is left out.
* Map geometry: retail now matches its DB2 build. Two retail POI blobs sit on maps without a rectangle and 74 fall
  off their map; those are dropped.
* Achievement criteria locations are thin (retail 9.5% of criteria): only quest, kill-creature and use-object
  criteria and wiki criteria linking to located pages can be placed.
* Addon repository observation (not changed from here): its `LICENSE` starts with a stray one-word first line
  before the copyright line.

## Publishing (main session)

This repository has no remote. To publish: create `danielalanbates/wow-completionist-data` on GitHub, add it as
`origin`, push `main`. Every file is far below GitHub's 50 MB warning size, so no Git LFS is needed. Run
`python3 tools/privacy_check.py` before every push.
