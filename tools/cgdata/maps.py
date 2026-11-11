# wow-completionist-data :: tools/cgdata/maps.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Map geometry and flight points from Blizzard DB2 tables (cache/db2/<flavor>/, tools/fetch_db2.py).

`map_table` turns UiMap + UiMapAssignment into the same rows as the addon's tools/maps_<flavor>.lua, with the same
algorithm as the addon's tools/gen_maps.py (same author): per map the OrderIndex-0 / largest assignment, its region
extrapolated to the full 0..1 UI square, values rounded to 0.01 yd as gen_maps.py writes them.  Maps without a usable
assignment (dungeon floors, scenarios) are left out: the addon's wikimaps.load_maps skips them too, and no point can
sit on a map without a rectangle.

World convention (HereBeDragons, the addon): worldX = topX - y/100 * h ; worldY = leftY - x/100 * w.
"""
import csv
import re

from . import common as C

csv.field_size_limit(1 << 28)


def cache_build(fl):
    p = C.CACHE_DB2 / fl / "BUILD"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def _rows(fl, table):
    p = C.CACHE_DB2 / fl / f"{table}.csv"
    if not p.exists() or p.stat().st_size == 0:
        return None
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def map_table(fl):
    """-> {uiMapID: {name, inst, topX, leftY, w, h, parent, type}} or None when the tables are not cached"""
    ui_rows, asg = _rows(fl, "UiMap"), _rows(fl, "UiMapAssignment")
    if not ui_rows or not asg:
        return None
    ui = {int(r["ID"]): r for r in ui_rows}
    best = {}
    for r in asg:
        mid = int(r["UiMapID"])
        if mid not in ui:
            continue
        x0, y0, x1, y1 = float(r["Region_0"]), float(r["Region_1"]), float(r["Region_3"]), float(r["Region_4"])
        umin0, umin1, umax0, umax1 = (float(r["UiMin_0"]), float(r["UiMin_1"]), float(r["UiMax_0"]),
                                      float(r["UiMax_1"]))
        if umax0 - umin0 <= 0 or umax1 - umin1 <= 0:
            continue
        w = (y1 - y0) / (umax0 - umin0)
        h = (x1 - x0) / (umax1 - umin1)
        left_y = y1 + umin0 * w
        top_x = x1 + umin1 * h
        key = (int(r["OrderIndex"]) != 0, -abs(w * h))
        if mid not in best or key < best[mid][0]:
            best[mid] = (key, int(r["MapID"]), top_x, left_y, w, h)
    out = {}
    for mid, u in ui.items():
        name = u.get("Name_lang") or ""
        parent, typ = int(u.get("ParentUiMapID") or 0), int(u.get("Type") or 0)
        if mid in best:
            _k, inst, top_x, left_y, w, h = best[mid]
            out[mid] = {"name": name, "inst": inst, "topX": round(top_x, 2), "leftY": round(left_y, 2),
                        "w": round(w, 2), "h": round(h, 2), "parent": parent, "type": typ}
    return out


def taxi_nodes(fl):
    """-> [(node id, name, continent instance id, worldX, worldY)] from TaxiNodes, or [] when not cached"""
    rows = _rows(fl, "TaxiNodes") or []
    out = []
    for r in rows:
        try:
            out.append((int(r["ID"]), r.get("Name_lang") or "", int(r["ContinentID"]), float(r["Pos_0"]),
                        float(r["Pos_1"])))
        except (KeyError, ValueError):
            continue
    return sorted(out)


def apply_to_mapset(ms, table):
    """replace a wikimaps.MapSet's maps with `table` and rebuild its lookup indexes (the addon's MapSet.__init__)"""
    ms.maps = table
    ms.by_norm = {}
    for mid, m in sorted(table.items()):
        ms.by_norm.setdefault(_norm(m["name"]), []).append(mid)
    ms.cache = {}
    ms.by_inst = {}
    for mid, m in sorted(table.items()):
        if m["w"] and m["h"] and m["type"] in (3, 4, 5, 6):
            ms.by_inst.setdefault(m["inst"], []).append(mid)


def _norm(s):
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())
