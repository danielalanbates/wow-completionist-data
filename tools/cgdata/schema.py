# wow-completionist-data :: tools/cgdata/schema.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Record schemas (docs/SCHEMA.md is the prose version) and a small dependency-free checker.

Spec language: a Python type (int, str, bool, float = any number), None, a tuple = one of, a frozenset = one of
these literal values, [spec] = list of spec, {name: spec} = object with exactly these members ("?name" = may be
absent; any other member is an error).
"""
from .names import CLASSES, FACTIONS, RACES

NUM = float
COORD = {"map": int, "x": NUM, "y": NUM}
CONFIDENCE = frozenset({"high", "medium", "low"})
READ_AS = frozenset({"retail", "classic", "tbc", "forever", "mop"})
READ_BY = frozenset({"tag", "check", "zone-default", "default"})
CHECK = {"against": frozenset({"QuestPOIBlob", "TaxiNodes"}), "build": str, "id": int, "yards": int, "?quest": int}
SOURCE_WIKI = {"type": frozenset({"wiki"}), "page": str, "revid": (int, None), "via": str, "?item_page": str,
               "read_as": READ_AS, "read_by": READ_BY, "?check": CHECK}
REPLACED = {"page": (str, None), "revid": (int, None), "via": (str, None), "map": int, "x": NUM, "y": NUM,
            "yards": int}
SOURCE_DB2 = {"type": frozenset({"db2"}), "table": str, "build": str, "blob": int, "via": str, "?replaces": REPLACED}
SOURCE_FIX = {"type": frozenset({"correction"}), "correction": str}
COORD_SOURCE = (None, SOURCE_WIKI, SOURCE_DB2, SOURCE_FIX)
KIND = frozenset({"npc", "object", "item", "place", "quest", "achievement", "auto", "unknown"})
SIDE = (None, frozenset({"Alliance", "Horde"}))
ENDPOINT = {"kind": KIND, "ids": [int], "name": (str, None), "page": (str, None), "faction": SIDE,
            "coords": [COORD], "coord_source": COORD_SOURCE, "exact_version": (bool, None),
            "confidence": (None, CONFIDENCE)}
TARGET = {"kind": KIND, "ids": [int], "name": (str, None), "page": (str, None)}
OBJECTIVE = {"index": int, "kind": frozenset({"kill", "item", "talk", "use", "progress", "other", "provided", "object"}),
             "text": (str, None), "count": (int, None), "optional": bool, "target": (None, TARGET), "coords": [COORD],
             "coord_source": COORD_SOURCE, "exact_version": (bool, None), "confidence": (None, CONFIDENCE),
             "?db2_objective": int, "?db2_type": int}
PREREQS = {"required": [[int]], "breadcrumb": [int], "optional": [int], "in_progress": [int],
           "inferred_from_next": [int], "basis": frozenset({"none", "single", "explicit", "list"}),
           "?faction": dict, "?wiki_text": str, "?unresolved_links": int}
WIKI_REF = {"page": str, "revid": (int, None)}
DB2_REF = {"table": str, "build": str}
FLAVOR = frozenset({"era", "tbc", "mop", "retail", "forever"})
QUEST_BODY = {
    "name": str, "faction": frozenset(FACTIONS), "level": (int, None), "min_level": (int, None),
    "type": (str, None), "category": (str, None), "zone_map": (int, None),
    "zone_map_source": (None, frozenset({"category", "coords"})), "classes": [frozenset(CLASSES)],
    "races": [frozenset(RACES)],
    "profession": (str, None), "is_breadcrumb": (None, frozenset({"yes", "optional"})), "auto_accept": bool,
    "start": [ENDPOINT], "end": [ENDPOINT], "end_same_as_start": bool,
    "start_item": (None, {"ids": [int], "name": (str, None), "page": (str, None)}),
    "objectives_text": (str, None), "objectives_source": (None, frozenset({"wiki", "db2"})), "objectives": [OBJECTIVE],
    "prerequisites": PREREQS, "next": [int],
}
VARIANT = dict(QUEST_BODY, source={"wiki": WIKI_REF})
ID_CLAIM = {"page": str, "revid": (int, None), "name": str, "faction": str}
QUEST = dict({"id": int, "flavors": [FLAVOR]}, **QUEST_BODY, **{
    "source": {"wiki": WIKI_REF, "db2": DB2_REF}, "?variants": [VARIANT], "?id_conflict": [ID_CLAIM],
    "?corrections": [str]})
NPC_COORD = {"map": int, "x": NUM, "y": NUM, "exact_version": bool, "via": (str, None), "confidence": CONFIDENCE,
             "?read_as": READ_AS, "?read_by": READ_BY, "?check": CHECK, "?correction": str}
NPC = {"key": str, "kind": frozenset({"npc", "object"}), "ids": [int], "name": str, "coords": [NPC_COORD],
       "source": {"wiki": WIKI_REF}, "?corrections": [str]}
LOCATION = (None, {"map": int, "x": NUM, "y": NUM, "via": str, "?quest": int, "?page": str, "?revid": (int, None),
                   "?exact_version": bool, "?confidence": CONFIDENCE})
CRITERION = {"tree": int, "criteria": int, "type": (int, None), "type_name": (str, None), "asset": (int, None),
             "amount": (int, None), "text": (str, None), "location": LOCATION}
WIKI_CRITERION = {"text": (str, None), "link": (str, None), "quest": (int, None), "location": LOCATION}
ACHIEVEMENT = {
    "id": int, "name": (str, None), "description": (str, None), "reward": (str, None),
    "category": {"id": int, "path": [str]}, "points": int, "faction": str, "flags": int, "statistic": bool,
    "guild": bool, "account_wide": bool, "criteria": [CRITERION],
    "wiki": (None, {"page": str, "revid": (int, None), "category": (str, None), "criteria": [WIKI_CRITERION]}),
    "source": {"db2": DB2_REF, "?wiki": WIKI_REF}, "?corrections": [str],
}
MISSION = {
    "id": int, "name": (str, None), "location": (str, None), "description": (str, None), "garrison_type": int,
    "garrison_type_name": (str, None), "mission_type": int, "follower_type": int, "max_followers": int,
    "target_level": int, "target_item_level": int, "duration_s": int, "travel_s": int, "cost": int,
    "cost_currency": int, "area_id": int, "map_pos": [NUM], "source": {"db2": DB2_REF}, "?corrections": [str],
}
SCHEMAS = {"quests": QUEST, "npcs": NPC, "objects": NPC, "achievements": ACHIEVEMENT, "missions": MISSION}


def check(value, spec, path="$", out=None, limit=20):
    """-> list of 'path: problem' strings (at most `limit`)"""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(spec, tuple):
        for s in spec:
            if not check(value, s, path, [], limit):
                return out
        out.append(f"{path}: {short(value)} matches none of the allowed shapes")
        return out
    if spec is None:
        if value is not None:
            out.append(f"{path}: expected null")
        return out
    if isinstance(spec, frozenset):
        if not isinstance(value, (str, int)) or isinstance(value, bool) or value not in spec:
            out.append(f"{path}: {short(value)} not in {sorted(spec)}")
        return out
    if spec is bool:
        if not isinstance(value, bool):
            out.append(f"{path}: expected true/false")
        return out
    if spec is int:
        if not isinstance(value, int) or isinstance(value, bool):
            out.append(f"{path}: expected an integer, got {short(value)}")
        return out
    if spec is NUM:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            out.append(f"{path}: expected a number, got {short(value)}")
        return out
    if spec is str:
        if not isinstance(value, str):
            out.append(f"{path}: expected a string, got {short(value)}")
        return out
    if spec is dict:
        if not isinstance(value, dict):
            out.append(f"{path}: expected an object")
        return out
    if isinstance(spec, list):
        if not isinstance(value, list):
            out.append(f"{path}: expected a list, got {short(value)}")
            return out
        for i, v in enumerate(value):
            check(v, spec[0], f"{path}[{i}]", out, limit)
        return out
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            out.append(f"{path}: expected an object, got {short(value)}")
            return out
        names = {k.lstrip("?"): k.startswith("?") for k in spec}
        for k in value:
            if k not in names:
                out.append(f"{path}.{k}: unknown member")
        for k, s in spec.items():
            name = k.lstrip("?")
            if name not in value:
                if not k.startswith("?"):
                    out.append(f"{path}.{name}: missing")
                continue
            check(value[name], s, f"{path}.{name}", out, limit)
        return out
    raise TypeError(f"bad spec at {path}: {spec!r}")


def short(v):
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."
