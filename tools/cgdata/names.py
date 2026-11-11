# wow-completionist-data :: tools/cgdata/names.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Fixed spellings for faction, class and race values (the wiki mixes "Death knight" / "Death Knight", "horde" /
"Horde", "neutral").  Output uses the in-game names; schema.py makes these the only allowed values."""
import re

FACTIONS = ("Alliance", "Horde", "Both", "Aldor", "Scryers", "Kyrian", "Necrolord", "Night Fae", "Venthyr")
_FACTION_ALIAS = {"neutral": "Both", "both": "Both", "alliance": "Alliance", "horde": "Horde"}
CLASSES = ("Warrior", "Paladin", "Hunter", "Rogue", "Priest", "Death Knight", "Shaman", "Mage", "Warlock", "Monk",
           "Druid", "Demon Hunter", "Evoker")
RACES = ("Human", "Dwarf", "Night Elf", "Gnome", "Draenei", "Worgen", "Pandaren", "Orc", "Undead", "Tauren", "Troll",
         "Blood Elf", "Goblin", "Void Elf", "Lightforged Draenei", "Dark Iron Dwarf", "Kul Tiran", "Mechagnome",
         "Nightborne", "Highmountain Tauren", "Mag'har Orc", "Zandalari Troll", "Vulpera", "Dracthyr", "Earthen",
         "Haranir", "Skyborne")
_BY_KEY = {re.sub(r"[^a-z]", "", v.lower()): v for v in FACTIONS + CLASSES + RACES}
_BY_KEY.update({"forsaken": "Undead", "scourge": "Undead", "bloodelves": "Blood Elf", "nightelves": "Night Elf",
                "dwarves": "Dwarf", "dk": "Death Knight", "dh": "Demon Hunter"})


def _key(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def faction(v):
    """wiki faction -> one of FACTIONS ("neutral" and empty -> "Both"); an unknown value is returned unchanged so
    validation reports it"""
    v = (v or "").strip()
    if not v:
        return "Both"
    k = _key(v)
    if k in _FACTION_ALIAS:
        return _FACTION_ALIAS[k]
    return next((f for f in FACTIONS if _key(f) == k), v)


def side(v):
    """Alliance / Horde / None"""
    f = faction(v)
    return f if f in ("Alliance", "Horde") else None


def canon(v, allowed):
    """one class or race name -> its in-game spelling (unknown values unchanged)"""
    hit = _BY_KEY.get(_key(v))
    return hit if hit in allowed else v.strip()
