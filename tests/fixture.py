# wow-completionist-data :: tests/fixture.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
"""A tiny synthetic dataset (one flavor) written into a temporary directory, for the pipeline tests.
The records are invented test values in the real schema, not game data."""
import copy
import json
from pathlib import Path

from cgdata import common as C

WIKI = {"type": "wiki", "page": "Test NPC", "revid": 11, "via": "entity-page"}


def endpoint(name, mid=1429, x=40.0, y=50.0, located=True):
    return {"kind": "npc", "ids": [900001], "name": name, "page": "Test NPC", "faction": None,
            "coords": [{"map": mid, "x": x, "y": y}] if located else [],
            "coord_source": dict(WIKI) if located else None, "exact_version": True if located else None}


def quest(qid, prereq=None, nxt=None):
    return {
        "id": qid, "name": f"Test quest {qid}", "flavors": ["era"], "faction": "Both", "level": 5, "min_level": 3,
        "type": None, "category": "Elwynn Forest", "zone_map": 1429, "zone_map_source": "category", "classes": [],
        "races": [], "profession": None, "is_breadcrumb": None, "auto_accept": False,
        "start": [endpoint("Giver")], "end": [endpoint("Ender", located=False)], "end_same_as_start": False,
        "start_item": None, "objectives_text": "Do it.", "objectives_source": "wiki",
        "objectives": [{"index": 1, "kind": "kill", "text": "Test mob slain (3)", "count": 3, "optional": False,
                        "target": {"kind": "npc", "ids": [900002], "name": "Test mob", "page": "Test mob"},
                        "coords": [], "coord_source": None, "exact_version": None}],
        "prerequisites": {"required": prereq or [], "breadcrumb": [], "optional": [], "in_progress": [],
                          "inferred_from_next": [], "basis": "single" if prereq else "none"},
        "next": nxt or [],
        "source": {"wiki": {"page": f"Test quest {qid}", "revid": 100 + qid},
                   "db2": {"table": "QuestV2", "build": "test 0.0.0.1"}},
    }


def npc(key, nid, located=True):
    return {"key": key, "kind": "npc", "ids": [nid], "name": key,
            "coords": [{"map": 1429, "x": 41.5, "y": 65.2, "exact_version": True, "via": "location"}] if located else [],
            "source": {"wiki": {"page": key, "revid": 7}}}


QUESTS = [quest(10, nxt=[11]), quest(11, prereq=[[10]]), quest(2500, prereq=[[10, 11]])]
NPCS = [npc("Test NPC", 900001), npc("Test mob", 900002, located=False)]


def write(data_dir, quests=None, npcs=None, questv2=(10, 11, 12, 2500), excluded=()):
    data_dir = Path(data_dir)
    C.write_kind("era", "quests", copy.deepcopy(quests if quests is not None else QUESTS), data_dir)
    C.write_kind("era", "npcs", copy.deepcopy(npcs if npcs is not None else NPCS), data_dir)
    (data_dir / "era").mkdir(parents=True, exist_ok=True)
    (data_dir / "era" / "maps.json").write_text(json.dumps({
        "flavor": "era", "source": {"tables": "UiMap + UiMapAssignment", "build": "test"},
        "fields": ["id", "name", "instance", "topX", "leftY", "width", "height", "parent", "type"],
        "maps": [[1429, "Elwynn Forest", 0, 1.0, 1.0, 1.0, 1.0, 1415, 3]]}))
    (data_dir / "era" / "questv2.json").write_text(json.dumps({
        "flavor": "era", "table": "QuestV2", "build": "test 0.0.0.1", "count": len(questv2),
        "excluded": [{"id": i, "page": f"Removed {i}", "revid": 1, "reason": "removed 1.0"} for i in excluded],
        "ids": list(questv2)}))
    (data_dir / "meta.json").write_text(json.dumps({"schema_version": 1, "sources": {}, "counts": {}}))
    return data_dir


def write_corrections(corr_dir, corrections, name="fix.json"):
    corr_dir = Path(corr_dir)
    corr_dir.mkdir(parents=True, exist_ok=True)
    (corr_dir / name).write_text(json.dumps({"corrections": corrections}))
    return corr_dir
