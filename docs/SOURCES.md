# Sources and related projects

Surveyed 2026-11-10 before building this dataset. Licences were read from each project's own licence file through
the GitHub API (`/repos/<owner>/<repo>/license`) or, for wikis, from the MediaWiki `siteinfo` rights field. The
question for each: may its data be **mixed into a CC BY-SA 4.0 dataset**? Permissive licences (MIT, BSD, CC BY,
CC BY-SA <= 4.0, public domain) can be; copyleft software licences (GPL, AGPL), NonCommercial or NoDerivatives
licences, and "no licence / all rights reserved" cannot.

**Rule for this repository:** shipped data comes only from the Warcraft Wiki and Blizzard client data. Nothing else
below is mixed in. A project marked "cross-check only" could at most be compared against offline, with no value
copied; none is used for that today.

## Used

| Project | Licence | Mix into CC BY-SA 4.0? | How it is used |
|---|---|---|---|
| [Warcraft Wiki](https://warcraft.wiki.gg) | CC BY-SA 4.0 (site rights field) | yes, same licence | the source of quest, NPC, object, prerequisite and achievement-criteria data; every record names page + revision |
| World of Warcraft client data (DB2), via [wago.tools](https://wago.tools) | Blizzard's game data; wago.tools publishes no data licence (its pages refuse automated reads, so none could be checked beyond the absence of one) | not a licence question: factual client data, kept with a notice (LICENSE-DATA) | QuestV2 membership, retail quest POI and objectives, achievements, criteria, missions, map geometry (UiMap + UiMapAssignment of the same build as each client's quest tables), flight points (TaxiNodes) and turn-in pins as the evidence for reading wiki coordinates; every record names table + build |
| [WoWDBDefs](https://github.com/wowdev/WoWDBDefs) | definitions CC BY-SA 4.0, code BSD-3-Clause (LICENSE.md) | yes | indirectly: wago.tools names the DB2 columns from these definitions; credited in ATTRIBUTION.md |
| [Completionist's Guide](https://github.com/danielalanbates/wow-completionist-guide) `tools/wiki` | PolyForm Noncommercial 1.0.0 + rider (same author) | n/a (code) | the parser, zone resolution and membership logic, imported by `tools/cgdata/export.py`; its `KEEP_NUMBERS` zone list is not used (see below) |

## Related, not used

| Project | What it is | Licence | Mix? | Notes |
|---|---|---|---|---|
| [Wowpedia](https://wowpedia.fandom.com) | the older Fandom wiki | CC BY-SA 3.0 | yes (BY-SA 3.0 allows adaptations under a later BY-SA version) | Warcraft Wiki continues it; not needed |
| [DBCD](https://github.com/wowdev/DBCD) | C# DB2 reader | MIT | yes (code) | a tool, not data |
| [wow.tools.local](https://github.com/Marlamin/wow.tools.local) | local DB2 browser | MIT | yes (code) | could replace wago.tools exports for reproducibility |
| [wow.export](https://github.com/Kruithne/wow.export) | client file exporter | MIT | yes (code) | a tool, not data |
| [TrinityCore](https://github.com/TrinityCore/TrinityCore) (+ TDB world database) | server emulator; its world DB has quest starters/enders, spawns, chains | GPL-2.0 | no | cross-check only |
| [AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) | 3.3.5 emulator + world DB | GPL-2.0 (GitHub licence field) | no | cross-check only |
| [CMaNGOS classic-db](https://github.com/cmangos/classic-db), [tbc-db](https://github.com/cmangos/tbc-db), [wotlk-db](https://github.com/cmangos/wotlk-db) | content databases for 1.12 / 2.4.3 / 3.3.5 | GPL-3.0 | no | cross-check only |
| [CMaNGOS core](https://github.com/cmangos/mangos-classic) | emulator | GPL-2.0 | no | |
| [VMaNGOS](https://github.com/vmangos/core) | progressive 1.x emulator + world DB | GPL-2.0 | no | cross-check only |
| [MaNGOS Zero database](https://github.com/mangoszero/database) | 1.12 world DB | CC BY-NC-SA 3.0 (LICENSE.md) | no (NonCommercial) | |
| [pfQuest](https://github.com/shagu/pfQuest) | Vanilla/TBC quest helper with a full database | MIT (code); its README says the database comes from VMaNGOS and CMaNGOS | no (the data is GPL-derived) | archived |
| [AllTheThings](https://github.com/ATTWoWAddon/AllTheThings) | collection tracker with large hand-made databases | MIT (LICENSE) | the licence would allow it | not used: the owner's rule is wiki + client data only, and the database's own sources are not documented |
| [Grail](https://github.com/smaitch/Grail) | quest database library addon | no licence file | no (all rights reserved by default) | |
| [BtWQuests](https://github.com/Breeni/BtWQuestsDragonflight) (and its other expansion repos) | quest chain browser | no licence file | no | |
| [HereBeDragons](https://github.com/Nevcairiel/HereBeDragons) | map coordinate library with map data | no licence file in the repo | no | this dataset takes map geometry from UiMapAssignment instead |
| [wow-classic-items](https://github.com/nexus-devs/wow-classic-items) | Classic item database | MIT (code); README says the data is scraped from Wowhead and the Blizzard API | no (scraped third-party data) | |
| [wowhead-quest-data-parser](https://github.com/helias/wowhead-quest-data-parser) | Wowhead quest scraper | AGPL-3.0 | no | |
| [SimulationCraft](https://github.com/simulationcraft/simc) | combat simulator with DB2 extracts | GPL-3.0 | no | not quest data |
| [Questie](https://github.com/Questie/Questie), [QuestieDB](https://github.com/Questie/QuestieDB) | Classic quest helper + database | LICENSE.md: "when in doubt consider Questie as all rights reserved"; parts moving to GPLv3 | no | excluded by rule; never read by this repository |
| [WoW-Pro Guides](https://github.com/Ludovicus-Maior/WoW-Pro-Guides) | guide addon | CC BY-NC-ND 3.0 (License.md) | no (NonCommercial, NoDerivatives) | excluded by rule |
| Wowhead and similar database sites | quest / NPC databases | proprietary site terms; no open licence offered (not reviewed in detail) | no | |
| The commercial guide addon this project replaced | commercial guides | proprietary | no | excluded by rule; not used in any form and not named in this repository |

## Why not take coordinates from an emulator database?

They are the most complete quest-giver positions for the old clients (Era, TBC, Forever have no Blizzard
coordinate data), so the gap is real: see docs/COVERAGE.md. But every one of them is GPL or NonCommercial. GPL is a
software licence whose copyleft would attach to the dataset and is not compatible with CC BY-SA 4.0 for data
mixing, so values cannot be copied, even one at a time. The legal way to close the gap is the Warcraft Wiki itself
(add `{{co}}` coordinates to NPC pages) and in-game checks submitted as corrections.

## Which map a wiki coordinate was written on: the addon's list, and what replaced it

The addon's `tools/wiki/wikimaps.py` carries `KEEP_NUMBERS`, five zones (Badlands, Arathi Highlands, Swamp of
Sorrows, Felwood, Teldrassil) whose wiki numbers it reads as Classic-map numbers on Classic clients. Its comment
says the list was "found by comparing wiki points with each client's own quest data per zone", and the addon's
docs/IDEAS.md says that comparison data was its "Classic fallback data, which cannot be part of a shippable
pipeline" (that fallback is the Questie-derived `Imported_Quests` files its `gen_wiki_guides.py` reads). No value
from it was ever copied, but the list decided shipped coordinates in those zones in this repository's first export
(2026-11-10).

The list is no longer used here. Since the second export (same day) `tools/cgdata/evidence.py` decides row by row
from shippable evidence only: Blizzard's retail quest turn-in pins (QuestPOIBlob) and the Classic Era and retail
flight points (TaxiNodes), all DB2 client data at the pinned builds. Zones whose unchecked rows are read as Classic
numbers come from those checks (`data/meta.json` `coordinate_reading`); in the 2026-11-10 export they are Arathi
Highlands and Dun Morogh. The evidence also showed the old list was wrong in places: in Badlands ten checked NPC
pages carry retail numbers and none carry Classic numbers.
