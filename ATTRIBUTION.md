# Attribution

Use this when you redistribute the data. CC BY-SA 4.0 asks for the title, the authors, the source and the licence,
and a note of any changes.

## Short form (for an addon's About page or a README)

> Quest data from wow-completionist-data (https://github.com/danielalanbates/wow-completionist-data), adapted from
> Warcraft Wiki (https://warcraft.wiki.gg) by its contributors, licensed CC BY-SA 4.0
> (https://creativecommons.org/licenses/by-sa/4.0/). Includes World of Warcraft client data from Blizzard
> Entertainment.

## What comes from where

| Material | Authors | Source | Licence |
|---|---|---|---|
| Quest names, givers, enders, objective lines, `previous` / `next` chains, breadcrumb notes, NPC / object / place coordinates, achievement criteria lists | Warcraft Wiki contributors (each page's history lists them) | [warcraft.wiki.gg](https://warcraft.wiki.gg); the exact page and revision are in each record's `source.wiki` and `coord_source` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| Quest ids per client (`QuestV2`), retail quest map pins (`QuestPOIBlob`, `QuestPOIPoint`), retail objectives (`QuestObjective`), achievements (`Achievement`, `Achievement_Category`, `Criteria`, `CriteriaTree`), missions (`GarrMission`), map geometry (`UiMap`, `UiMapAssignment`) | Blizzard Entertainment | World of Warcraft client files, exported by [wago.tools](https://wago.tools) at the builds in `data/meta.json` | Blizzard's game data; no open licence. See the notice in [LICENSE-DATA](LICENSE-DATA). |
| DB2 column names used to read those exports | WoWDBDefs contributors | [github.com/wowdev/WoWDBDefs](https://github.com/wowdev/WoWDBDefs) (the definitions wago.tools uses) | definitions: CC BY-SA 4.0 |
| Corrections in `corrections/` | their contributors (git history) | this repository | CC BY-SA 4.0 |
| Selection, arrangement, conversion and the derived fields (`flavors`, `exact_version`, prerequisite classes, converted coordinates) | Daniel Bates and contributors | this repository | CC BY-SA 4.0 |

The page-parsing and coordinate-conversion logic is the
[Completionist's Guide](https://github.com/danielalanbates/wow-completionist-guide) addon's own `tools/wiki`
pipeline (same author), imported by `tools/cgdata/export.py`.

## Finding a page's authors

Every wiki-derived record names its page, e.g. `"source": {"wiki": {"page": "A Threat Within", "revid": 6225851}}`.
The authors are at `https://warcraft.wiki.gg/wiki/<page>?action=history`, and the exact text that was read is at
`https://warcraft.wiki.gg/index.php?oldid=<revid>`.
