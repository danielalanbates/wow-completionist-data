# wow-completionist-data :: tools/cgdata/export.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Stage 1 of tools/build_db.py: the addon's parsed Warcraft Wiki tables + pinned Blizzard DB2 tables -> data/.

Reads (never writes) the addon repository (github.com/danielalanbates/wow-completionist-guide):
  tools/wiki/wiki.sqlite              parsed wiki tables (tools/wiki/parse_wiki.py)
  tools/wiki/cache/wiki_raw.sqlite    raw wikitext + revision ids (tools/wiki/fetch_wiki.py, fetch_titles.py)
  tools/db2/<flavor>/*.csv + BUILD    DB2 tables pinned to one build per client (tools/wiki/fetch_db2.py)
  tools/maps_<flavor>.lua             UiMap/UiMapAssignment per client (tools/gen_maps.py)
and imports the addon's own logic by path so both projects read the wiki the same way:
  tools/wiki/wikimaps.py         zone name -> uiMapID, cross-version coordinate conversion (incl. KEEP_NUMBERS)
  tools/wiki/gen_wiki_guides.py  flavor membership rules, page-variant choice, best point on an NPC page
  tools/wiki/wikitext.py         template / link helpers
Nothing here reads third-party addon data or any commercial guide data.
"""
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import common as C
from .prereqs import lead_breadcrumb, parse_previous

csv.field_size_limit(1 << 28)
GENERATOR = "tools/build_db.py export"
SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")
OBJ_KIND_DB2 = {0: "kill", 1: "item", 2: "object", 3: "talk", 15: "progress"}
CRITERIA_TYPE = {0: "kill_creature", 8: "earn_achievement", 27: "complete_quest", 36: "obtain_item",
                 43: "explore_area", 68: "use_object"}
GARR_TYPE = {2: "Garrison (Warlords of Draenor)", 3: "Class Hall (Legion)", 9: "War Campaign (Battle for Azeroth)",
             111: "Covenant (Shadowlands)"}
ACH_FLAG_COUNTER, ACH_FLAG_GUILD, ACH_FLAG_ACCOUNT = 0x1, 0x4000, 0x20000
# the DB2 tables each client's export actually reads (mop's QuestPOIBlob has no quest rows, so it is not used)
USED_TABLES = {"mop": ("QuestV2", "Achievement", "Achievement_Category", "Criteria", "CriteriaTree"),
               "retail": ("QuestV2", "QuestObjective", "QuestPOIBlob", "QuestPOIPoint", "Achievement",
                          "Achievement_Category", "Criteria", "CriteriaTree", "GarrMission")}


def r1(v):
    return round(float(v) + 0.0, 1)


def strip_suffix(title):
    return SUFFIX.sub("", title or "").strip() or title


def split_list(s):
    parts = re.split(r",|/|\band\b|\bor\b", s or "")
    return [p.strip() for p in parts if p.strip()]


def int_list(s):
    return list(dict.fromkeys(int(x) for x in re.findall(r"\d+", s or "")))


def parse_pts(text):
    out = []
    for pr in (text or "").split(";"):
        try:
            x, y = (float(v) for v in pr.split(","))
        except ValueError:
            continue
        out.append((r1(x), r1(y)))
    return out


class Addon:
    """read-only view of the addon repository"""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.wiki_dir = self.root / "tools" / "wiki"
        self.wiki_db = self.wiki_dir / "wiki.sqlite"
        self.raw_db = self.wiki_dir / "cache" / "wiki_raw.sqlite"
        self.db2 = self.root / "tools" / "db2"
        for p in (self.wiki_db, self.raw_db, self.db2, self.wiki_dir / "wikimaps.py",
                  self.wiki_dir / "gen_wiki_guides.py"):
            if not p.exists():
                sys.exit(f"addon input missing: {p.relative_to(self.root) if p.is_relative_to(self.root) else p} "
                         f"(run the addon's tools/wiki pipeline first, see docs/HANDOFF.md)")
        sys.path.insert(0, str(self.wiki_dir))
        sys.dont_write_bytecode = True   # no __pycache__ files inside the addon checkout
        import gen_wiki_guides  # noqa: E402  (imports wikimaps, gen_spine)
        import wikimaps  # noqa: E402
        import wikitext  # noqa: E402
        self.G, self.wm, self.W = gen_wiki_guides, wikimaps, wikitext

    def ro(self, path):
        # immutable: no locks, no -shm/-wal writes; the addon's files are never touched
        con = sqlite3.connect(Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def build(self, fl):
        p = self.db2 / fl / "BUILD"
        return p.read_text(encoding="utf-8").strip() if p.exists() else None

    def csv_path(self, fl, table):
        p = self.db2 / fl / f"{table}.csv"
        return p if p.exists() and p.stat().st_size > 0 else None

    def rows(self, fl, table):
        p = self.csv_path(fl, table)
        if not p:
            return
        with open(p, newline="", encoding="utf-8") as f:
            yield from csv.DictReader(f)

    def maps_build(self, fl):
        first = (self.root / "tools" / f"maps_{fl}.lua").read_text(encoding="utf-8").splitlines()[0]
        m = re.search(r"build (\d+(?:\.\d+)+)", first)
        return m.group(1) if m else None


class Exporter:
    def __init__(self, addon, data_dir=C.DATA, log=print):
        self.A = addon
        self.data_dir = Path(data_dir)
        self.log = log
        G = addon.G
        db = addon.ro(addon.wiki_db)
        self.wiki = db
        # a read-only twin of gen_wiki_guides.Gen (no fallback guides, no SQL writes): its location methods are reused
        g = G.Gen.__new__(G.Gen)
        g.db = db
        g.atlas = addon.wm.Atlas()
        g.use_fallback = False
        g.titles = {r["title"]: (r["page_title"], r["kind"]) for r in db.execute("select * from titles order by title")}
        g.npc_pts = defaultdict(list)
        for r in db.execute("select title, zone, x, y, source, badge, classic from npc_coords order by title, idx"):
            g.npc_pts[r["title"]].append((r["zone"], r["x"], r["y"], r["source"], r["badge"], r["classic"]))
        g.npc_classic = {r["title"]: r["page_classic"] for r in db.execute("select title, page_classic from npcs")}
        g.items = {r["title"]: (r["item_id"], json.loads(r["sources_json"] or "[]"))
                   for r in db.execute("select * from items order by title")}
        g.objs = defaultdict(list)
        for r in db.execute("select * from quest_objectives order by quest_id, page_title, idx"):
            g.objs[(r["quest_id"], r["page_title"])].append(dict(r))
        g.rows = [dict(r) for r in db.execute("select * from quests order by id, page_title")]
        g.qv2 = {}
        for fl in C.FLAVORS:
            g.qv2[fl] = {int(r["ID"]) for r in addon.rows(fl, "QuestV2")}
            if not g.qv2[fl]:
                sys.exit(f"tools/db2/{fl}/QuestV2.csv missing in the addon repo (run tools/wiki/fetch_db2.py there)")
        g.qobj = Counter()
        g.conflicts, g.place_cache, g.clean_pts, g.subzone_dropped = [], {}, {}, []
        self.g = g
        self.npc_meta = {r["title"]: (r["kind"], r["npc_id"]) for r in db.execute("select title, kind, npc_id from npcs")}
        self.npc_by_id = defaultdict(list)
        self.obj_by_id = defaultdict(list)
        for title, (kind, nid) in sorted(self.npc_meta.items()):
            for i in int_list(nid):
                (self.npc_by_id if kind == "npc" else self.obj_by_id)[i].append(title)
        # quest page title -> ids (parse_wiki's resolution, plus redirects / lower-case variants)
        self.ids_by_title = defaultdict(set)
        for r in g.rows:
            self.ids_by_title[r["page_title"]].add(r["id"])
        for frm, (to, _k) in g.titles.items():
            if frm != to and to in self.ids_by_title and frm not in self.ids_by_title:
                self.ids_by_title[frm] = self.ids_by_title[to]
        self.revs = {}
        self.prev, self.self_bc = {}, {}
        self._scan_raw()

    # ---- raw wikitext: revisions, `previous` fields, breadcrumb leads ------------------------------------
    def _scan_raw(self):
        raw = self.A.ro(self.A.raw_db)
        for r in raw.execute("select title, revid, timestamp from pages"):
            self.revs[r["title"]] = (r["revid"], r["timestamp"])
        W = self.A.W
        qb = re.compile(r"questbox", re.I)
        quest_pages = {r["page_title"] for r in self.g.rows}
        for r in raw.execute("select p.title, p.wikitext from pages p join page_templates t on t.pageid = p.pageid "
                             "and t.template = 'Questbox' order by p.title"):
            if r["title"] not in quest_pages:
                continue
            text = r["wikitext"] or ""
            box = next(W.find_templates(text, qb), None)
            if not box:
                continue
            _pos, f = W.split_params(box[3])
            self.prev[r["title"]] = parse_previous(f.get("previous", ""))
            lead = text[box[1]:].split("\n==", 1)[0]
            bc = lead_breadcrumb(lead)
            if bc:
                self.self_bc[r["title"]] = bc
        raw.close()

    def rev(self, title):
        return (self.revs.get(title) or (None, None))[0]

    def wiki_src(self, page, via, **extra):
        d = {"type": "wiki", "page": page, "revid": self.rev(page), "via": via}
        d.update(extra)
        return d

    # ---- entities ---------------------------------------------------------------------------------------
    def entity(self, title):
        """wiki link title -> (kind, page, ids)"""
        g = self.g
        page, kind = g.resolve_title(title)
        if not page:
            return "unknown", None, []
        ids = []
        if kind in ("npc", "object"):
            ids = int_list((self.npc_meta.get(page) or (None, ""))[1])
        elif kind == "item":
            iid = (g.items.get(page) or (None,))[0]
            ids = [int(iid)] if iid else []
        elif kind == "quest":
            ids = sorted(self.ids_by_title.get(page, ()))
        return kind or "unknown", page, ids

    def entity_coords(self, title, fl, added, home_name, depth=0):
        """(mapID, [(x, y)], page, exact, item_page) for a linked page; items follow their drop sources once"""
        g = self.g
        page, kind = g.resolve_title(title)
        if not page:
            return None
        if kind in ("npc", "object", "place") or page in g.npc_pts:
            pts, ex = g.page_points(page, fl, home_name)
            if pts:
                c = g.coords_list(pts, fl, bool(g.npc_classic.get(page)), added, home_name)
                if c:
                    return c[0], parse_pts(c[1]), page, ex, None
        if depth == 0 and page in g.items:
            for src in g.items[page][1]:
                c = self.entity_coords(src, fl, added, home_name, 1)
                if c:
                    return c[0], c[1], c[2], c[3], page
        return None

    def page_all_points(self, page, fl):
        """every coordinate row of an NPC/object page placed on this client's maps (deduplicated, page order)"""
        g = self.g
        out, seen = [], set()
        for zone, x, y, src, badge, classic in g.page_rows(page):
            p = g.place(zone, x, y, fl, bool(classic), None)
            if not p:
                continue
            k = (p[0], r1(p[1]), r1(p[2]))
            if k in seen:
                continue
            seen.add(k)
            out.append({"map": p[0], "x": k[1], "y": k[2],
                        "exact_version": bool(self.A.G.Gen.exact(fl, classic, badge)),
                        "via": (src or "").split(":")[0] or None})
        return out

    @staticmethod
    def coords_of(mid, pts):
        return [{"map": mid, "x": x, "y": y} for x, y in pts]

    # ---- retail quest POI (Blizzard DB2) ----------------------------------------------------------------
    def load_poi(self, fl):
        """quest -> {"turnin": (blobID, map, x, y) or None, "obj": {QuestObjective.ID: point},
        "idx": {ObjectiveIndex: point}}; ObjectiveIndex 32 (the client's next-waypoint hint) is skipped"""
        A = self.A
        if not A.csv_path(fl, "QuestPOIBlob") or not A.csv_path(fl, "QuestPOIPoint"):
            return {}, []
        maps = self.g.atlas.sets[fl].maps
        acc = {}
        for p in A.rows(fl, "QuestPOIPoint"):
            b = int(p["QuestPOIBlobID"])
            a = acc.setdefault(b, [0.0, 0.0, 0])
            a[0] += float(p["X"])
            a[1] += float(p["Y"])
            a[2] += 1
        poi = {}
        self.poi_stats = Counter()
        for b in sorted(A.rows(fl, "QuestPOIBlob"), key=lambda r: int(r["ID"])):
            qid, oi, bid = int(b["QuestID"]), int(b["ObjectiveIndex"]), int(b["ID"])
            if not qid or oi == 32 or bid not in acc:
                continue
            self.poi_stats["blobs"] += 1
            m = maps.get(int(b["UiMapID"]))
            if not m or not m["w"] or not m["h"]:
                self.poi_stats["skipped_map_not_in_maps_file"] += 1
                continue
            sx, sy, n = acc[bid]
            wx, wy = sx / n, sy / n
            y01, x01 = (m["topX"] - wx) / m["h"], (m["leftY"] - wy) / m["w"]
            if not (-0.02 <= x01 <= 1.02 and -0.02 <= y01 <= 1.02):
                self.poi_stats["skipped_off_map"] += 1
                continue
            pt = (bid, int(b["UiMapID"]), r1(min(max(x01, 0), 1) * 100), r1(min(max(y01, 0), 1) * 100))
            rec = poi.setdefault(qid, {"turnin": None, "obj": {}, "idx": {}})
            if oi == -1:
                if rec["turnin"] is None:
                    rec["turnin"] = pt
            else:
                rec["idx"].setdefault(oi, pt)
                if int(b["ObjectiveID"]):
                    rec["obj"].setdefault(int(b["ObjectiveID"]), pt)
        qobj = defaultdict(list)
        for r in A.rows(fl, "QuestObjective"):
            qobj[int(r["QuestID"])].append({"id": int(r["ID"]), "type": int(r["Type"]), "amount": int(r["Amount"]),
                                            "object": int(r["ObjectID"]), "order": int(r["OrderIndex"]),
                                            "text": (r["Description_lang"] or "").strip()})
        for v in qobj.values():
            v.sort(key=lambda o: (o["order"], o["id"]))
        return poi, qobj

    # ---- one client -------------------------------------------------------------------------------------
    def membership(self):
        """-> chosen[fl][qid] = wiki row, excluded[fl][qid] = reason, flavors_of[qid] = [fl...]"""
        G, g = self.A.G, self.g
        chosen = {fl: {} for fl in C.FLAVORS}
        excluded = {fl: {} for fl in C.FLAVORS}
        by_id = defaultdict(list)
        for r in g.rows:
            by_id[r["id"]].append(r)
        for fl in C.FLAVORS:
            pref = G.VARIANT_PREF[fl]
            for qid, rs in by_id.items():
                ok_rows, why = [], None
                for r in rs:
                    ok, reason = G.membership(r, fl, g.qv2)
                    if ok:
                        ok_rows.append(r)
                    elif why is None or why == "not in QuestV2":
                        why = reason
                if ok_rows:
                    def rank(r):
                        v = (r["variant"] or "").lower()
                        return (pref.index(v) if v in pref else len(pref), -(r["revid"] or 0), r["page_title"])
                    chosen[fl][qid] = sorted(ok_rows, key=rank)[0]
                elif qid in g.qv2[fl]:
                    excluded[fl][qid] = (why or "excluded", sorted(r["page_title"] for r in rs)[0])
        flavors_of = defaultdict(list)
        for fl in C.FLAVORS:
            for qid in chosen[fl]:
                flavors_of[qid].append(fl)
        return chosen, excluded, flavors_of

    def quest_ids(self, title):
        return self.ids_by_title.get(title) or self.ids_by_title.get(self.g.resolve_title(title)[0] or "") or set()

    def prerequisites(self, fl, qid, r, chosen):
        pp = self.prev.get(r["page_title"]) or {"groups": [], "basis": "none", "text": ""}
        out = {"required": [], "breadcrumb": [], "optional": [], "in_progress": [], "faction": {},
               "inferred_from_next": [], "basis": pp["basis"]}
        unresolved = 0
        for grp in pp["groups"]:
            alts = []
            for title, fac in grp["titles"]:
                ids = sorted(i for i in self.quest_ids(title) if i in chosen and i != qid)
                if not ids:
                    unresolved += 1
                for i in ids:
                    if i not in [a for a, _ in alts]:
                        alts.append((i, fac))
            if not alts:
                continue
            cls = grp["class"]
            if cls == "required" and len(alts) == 1 and self.self_bc.get(chosen[alts[0][0]]["page_title"]):
                cls = "breadcrumb"
            for i, fac in alts:
                if fac:
                    out["faction"][str(i)] = fac
            if cls == "required":
                out["required"].append([a for a, _ in alts])
            else:
                for a, _ in alts:
                    if a not in out[cls]:
                        out[cls].append(a)
        if unresolved or pp["basis"] in ("explicit", "list") or (pp["groups"] == [] and pp["text"]):
            out["wiki_text"] = pp["text"][:300]
        if unresolved:
            out["unresolved_links"] = unresolved
        if not out["faction"]:
            del out["faction"]
        return out

    def export_flavor(self, fl, chosen_all, excluded_all, flavors_of):
        G, g, A = self.A.G, self.g, self.A
        maps = g.atlas.sets[fl]
        chosen = chosen_all[fl]
        build = A.build(fl)
        poi, qobj = self.load_poi(fl) if fl == "retail" else ({}, {})
        st = Counter()
        ref_pages = set()          # npc / object pages this flavor's records point at
        quests = {}
        for qid in sorted(chosen):
            r = chosen[qid]
            page = r["page_title"]
            added = G.pkey(r["added_patch"])
            classic_q = bool(r["page_classic"])
            variant = (r["variant"] or "").lower()
            page_exact = G.Gen.exact(fl, classic_q, 0) or (
                fl == "mop" and variant in G.VARIANT_FOR and "mop" in G.VARIANT_FOR[variant])
            zone_name = r["zone"] or r["category"] or ""
            zmid = maps.resolve(zone_name, added) if zone_name else None
            home_name = maps.maps[zmid]["name"] if zmid else zone_name
            starts = json.loads(r["start_json"] or "[]")
            ends = json.loads(r["end_json"] or "[]")
            end_same = not ends
            ends = ends or starts
            if r["faction"] in ("Alliance", "Horde"):
                starts = [e for e in starts if e.get("faction") in ("", r["faction"])] or starts
                ends = [e for e in ends if e.get("faction") in ("", r["faction"])] or ends

            def endpoint(e):
                if e.get("auto") and not e.get("title"):
                    kind, epage, ids = "auto", None, []
                elif e.get("title"):
                    kind, epage, ids = self.entity(e["title"])
                else:
                    kind, epage, ids = "unknown", None, []
                ep = {"kind": kind, "ids": ids, "name": (e.get("label") or strip_suffix(epage or "") or None),
                      "page": epage, "faction": e.get("faction") or None, "coords": [], "coord_source": None,
                      "exact_version": None}
                if e.get("coords"):
                    c = g.coords_list([(x[2], x[0], x[1]) for x in e["coords"]], fl, classic_q, added, home_name)
                    if c:
                        ep["coords"] = self.coords_of(c[0], parse_pts(c[1]))
                        ep["coord_source"] = self.wiki_src(page, "questbox")
                        ep["exact_version"] = bool(page_exact)
                if not ep["coords"] and e.get("title"):
                    c = self.entity_coords(e["title"], fl, added, home_name)
                    if c:
                        ep["coords"] = self.coords_of(c[0], c[1])
                        ep["coord_source"] = (self.wiki_src(c[2], "item-source", item_page=c[4]) if c[4]
                                              else self.wiki_src(c[2], "entity-page"))
                        ep["exact_version"] = bool(c[3])
                        ref_pages.add(c[2])
                if epage and kind in ("npc", "object"):
                    ref_pages.add(epage)
                return ep

            start = [endpoint(e) for e in starts]
            end = [endpoint(e) for e in ends]
            # retail: Blizzard's turn-in pin when the wiki has no end point
            pq = poi.get(qid)
            if fl == "retail" and not any(e["coords"] for e in end) and pq and pq["turnin"]:
                bid, mid, x, y = pq["turnin"]
                if not end:
                    end = [{"kind": "unknown", "ids": [], "name": None, "page": None, "faction": None, "coords": [],
                            "coord_source": None, "exact_version": None}]
                end[0]["coords"] = [{"map": mid, "x": x, "y": y}]
                end[0]["coord_source"] = {"type": "db2", "table": "QuestPOIBlob", "build": build, "blob": bid,
                                          "via": "turn-in-pin"}
                end[0]["exact_version"] = True
            elif fl == "retail" and pq and pq["turnin"] and any(e["coords"] for e in end):
                e0 = next(e for e in end if e["coords"])
                if e0["coords"][0]["map"] == pq["turnin"][1]:
                    yd = g.atlas.yards(fl, pq["turnin"][1], (e0["coords"][0]["x"], e0["coords"][0]["y"]),
                                       pq["turnin"][2:])
                    if yd is not None:
                        st["turnin_compared"] += 1
                        st["turnin_over_50yd"] += yd > 50
            # objectives
            bullets = g.objs.get((qid, page), [])
            counted = [b for b in bullets if b["kind"] != "provided"]
            qo = qobj.get(qid, []) if fl == "retail" else []
            by_order = bool(qo) and len(qo) == len(counted)
            # the POI blobs' ObjectiveIndex is the objective's 0-based place in the quest log; it is used only when
            # every indexed blob fits the wiki's bullet count (the addon's retail guides read it the same way)
            by_index = bool(pq and pq["idx"]) and max(pq["idx"]) < len(counted)
            objectives, n_counted = [], 0
            for b in bullets:
                ob = {"index": b["idx"], "kind": b["kind"], "text": b["text"] or None, "count": b["count"],
                      "optional": bool(b["optional"]), "target": None, "coords": [], "coord_source": None,
                      "exact_version": None}
                tids = []
                if b["target_title"]:
                    kind, tpage, tids = self.entity(b["target_title"])
                    ob["target"] = {"kind": kind, "ids": tids, "name": strip_suffix(tpage or b["target_title"]),
                                    "page": tpage}
                    if tpage and kind in ("npc", "object"):
                        ref_pages.add(tpage)
                if b["kind"] != "provided":
                    n_counted += 1
                    bc = json.loads(b["coords_json"] or "[]")
                    if bc:
                        c = g.coords_list([(x[2], x[0], x[1]) for x in bc], fl, classic_q, added, home_name)
                        if c:
                            ob["coords"] = self.coords_of(c[0], parse_pts(c[1]))
                            ob["coord_source"] = self.wiki_src(page, "objective")
                            ob["exact_version"] = bool(page_exact)
                    if not ob["coords"] and b["target_title"]:
                        c = self.entity_coords(b["target_title"], fl, added, home_name)
                        if c:
                            ob["coords"] = self.coords_of(c[0], c[1])
                            ob["coord_source"] = (self.wiki_src(c[2], "item-source", item_page=c[4]) if c[4]
                                                  else self.wiki_src(c[2], "entity-page"))
                            ob["exact_version"] = bool(c[3])
                            ref_pages.add(c[2])
                    pt = None
                    if not ob["coords"] and qo and pq:
                        row = next((o for o in qo if o["object"] and o["object"] in tids), None)
                        if row is None and by_order:
                            row = qo[n_counted - 1]
                        pt = pq["obj"].get(row["id"]) if row else None
                        via = "objective-area"
                    if not ob["coords"] and pq and not pt and by_index:
                        pt = pq["idx"].get(n_counted - 1)
                        via = "objective-area-by-index"
                    if not ob["coords"] and pq and pt:
                        ob["coords"] = [{"map": pt[1], "x": pt[2], "y": pt[3]}]
                        ob["coord_source"] = {"type": "db2", "table": "QuestPOIBlob", "build": build,
                                              "blob": pt[0], "via": via}
                        ob["exact_version"] = True
                objectives.append(ob)
            obj_source = "wiki" if bullets else None
            if fl == "retail" and not counted and not qo and pq and pq["idx"]:
                # no wiki bullets and no QuestObjective rows: one objective per POI area, located but unnamed
                obj_source = "db2"
                for oi in sorted(pq["idx"]):
                    pt = pq["idx"][oi]
                    objectives.append({"index": oi + 1, "kind": "other", "text": None, "count": None,
                                       "optional": False, "target": None,
                                       "coords": [{"map": pt[1], "x": pt[2], "y": pt[3]}],
                                       "coord_source": {"type": "db2", "table": "QuestPOIBlob", "build": build,
                                                        "blob": pt[0], "via": "objective-area-by-index"},
                                       "exact_version": True})
            if fl == "retail" and not counted and qo:
                obj_source = "db2"
                for i, o in enumerate(qo, 1):
                    kind = OBJ_KIND_DB2.get(o["type"], "other")
                    target = None
                    if o["type"] in (0, 3) and o["object"]:
                        pages = self.npc_by_id.get(o["object"], [])
                        target = {"kind": "npc", "ids": [o["object"]], "name": strip_suffix(pages[0]) if pages else None,
                                  "page": pages[0] if pages else None}
                        if pages:
                            ref_pages.add(pages[0])
                    elif o["type"] == 2 and o["object"]:
                        pages = self.obj_by_id.get(o["object"], [])
                        target = {"kind": "object", "ids": [o["object"]],
                                  "name": strip_suffix(pages[0]) if pages else None, "page": pages[0] if pages else None}
                        if pages:
                            ref_pages.add(pages[0])
                    elif o["type"] == 1 and o["object"]:
                        target = {"kind": "item", "ids": [o["object"]], "name": None, "page": None}
                    ob = {"index": i, "kind": kind, "text": o["text"] or None, "count": o["amount"] or None,
                          "optional": False, "target": target, "coords": [], "coord_source": None,
                          "exact_version": None, "db2_objective": o["id"], "db2_type": o["type"]}
                    pt = (pq["obj"].get(o["id"]) or pq["idx"].get(o["order"])) if pq else None
                    if pt:
                        ob["coords"] = [{"map": pt[1], "x": pt[2], "y": pt[3]}]
                        ob["coord_source"] = {"type": "db2", "table": "QuestPOIBlob", "build": build, "blob": pt[0],
                                              "via": "objective-area"}
                        ob["exact_version"] = True
                    objectives.append(ob)
            # zone: the quest-log category when it is a map, else where the first located endpoint is
            zone_map, zone_src = (zmid, "category") if zmid is not None else (None, None)
            if zone_map is None:
                for e in start + end + objectives:
                    if e["coords"]:
                        zone_map, zone_src = maps.home(e["coords"][0]["map"]), "coords"
                        break
            item = r["item_start"]
            start_item = None
            if item:
                kind, ipage, ids = self.entity(item)
                if kind == "item":
                    start_item = {"ids": ids, "name": strip_suffix(ipage), "page": ipage}
            next_ids = []
            for n in int_list(r["next_ids"]):
                if n in chosen and n != qid and n not in next_ids:
                    next_ids.append(n)
            prereq = self.prerequisites(fl, qid, r, chosen)
            # cross-check with the addon's chain (parse_wiki prev_ids: every non-"(optional)" link, read as any-of)
            addon_pre = {int(p) for p in (r["prev_ids"] or "").split(",") if p and int(p) in chosen and int(p) != qid}
            mine_pre = {i for g_ in prereq["required"] for i in g_} | set(prereq["breadcrumb"]) | set(
                prereq["in_progress"])
            if addon_pre or mine_pre:
                st["prereq_quests"] += 1
                st["prereq_same_ids_as_addon"] += addon_pre == mine_pre
            st["prereq_breadcrumb_split"] += bool(prereq["breadcrumb"])
            st["prereq_optional_split"] += bool(prereq["optional"])
            st["prereq_multi_group"] += len(prereq["required"]) > 1
            q = {
                "id": qid,
                "name": r["name"] or strip_suffix(page),
                "flavors": flavors_of[qid],
                "faction": r["faction"] or "Both",
                "level": r["level"] if (r["level"] or 0) > 0 else None,
                "min_level": r["levelreq"] if (r["levelreq"] or 0) > 0 else None,
                "type": r["qtype"] or None,
                "category": r["category"] or None,
                "zone_map": zone_map,
                "zone_map_source": zone_src,
                "classes": split_list(r["classes"]),
                "races": split_list(r["races"]),
                "profession": r["profession"] or None,
                "is_breadcrumb": self.self_bc.get(page),
                "auto_accept": bool(starts) and all(e.get("auto") for e in starts),
                "start": start,
                "end": end,
                "end_same_as_start": end_same,
                "start_item": start_item,
                "objectives_text": r["objectives_text"] or None,
                "objectives_source": obj_source,
                "objectives": objectives,
                "prerequisites": prereq,
                "next": next_ids,
                "source": {"wiki": {"page": page, "revid": r["revid"]}, "db2": {"table": "QuestV2", "build": build}},
            }
            quests[qid] = q
        # prerequisites inferred from another quest's `next` when the quest itself names none on this client
        for qid in sorted(quests):
            for n in quests[qid]["next"]:
                p = quests[n]["prerequisites"]
                if not (p["required"] or p["breadcrumb"] or p["optional"] or p["in_progress"]):
                    if qid not in p["inferred_from_next"]:
                        p["inferred_from_next"].append(qid)
        for q in quests.values():
            q["prerequisites"]["inferred_from_next"].sort()
        # addon cross-check: the same membership as the addon's last generator run (flavor_quests), apart from the
        # time-limited types the addon leaves out on purpose
        addon_ids = {row[0] for row in self.wiki.execute("select quest_id from flavor_quests where flavor=?", (fl,))}
        mine = {qid for qid, r in chosen.items() if not G.SKIP_TYPES.search(r["qtype"] or "")}
        st["addon_flavor_quests"] = len(addon_ids)
        st["addon_only"] = len(addon_ids - mine)
        st["data_only"] = len(mine - addon_ids)
        return quests, ref_pages, st, poi

    def npc_records(self, fl, pages):
        npcs, objects = [], []
        for page in sorted(pages):
            kind, nid = self.npc_meta.get(page, (None, None))
            if kind not in ("npc", "object"):
                continue
            rec = {"key": page, "kind": kind, "ids": int_list(nid), "name": strip_suffix(page),
                   "coords": self.page_all_points(page, fl),
                   "source": {"wiki": {"page": page, "revid": self.rev(page)}}}
            (npcs if kind == "npc" else objects).append(rec)
        return npcs, objects

    # ---- achievements (mop, retail) ---------------------------------------------------------------------
    def achievements(self, fl, quests, ref_pages):
        A = self.A
        if not A.csv_path(fl, "Achievement"):
            return []
        build = A.build(fl)
        cats = {int(r["ID"]): (r["Name_lang"], int(r["Parent"])) for r in A.rows(fl, "Achievement_Category")}

        def cat_path(cid):
            out, seen = [], set()
            while cid in cats and cid not in seen:
                seen.add(cid)
                out.append(cats[cid][0])
                cid = cats[cid][1]
            return list(reversed(out))
        tree_kids = defaultdict(list)
        tree = {}
        for r in A.rows(fl, "CriteriaTree"):
            t = (int(r["ID"]), int(r["Parent"]), int(r["CriteriaID"]), int(r["Amount"]), int(r["OrderIndex"]),
                 (r["Description_lang"] or "").strip())
            tree[t[0]] = t
            tree_kids[t[1]].append(t)
        for v in tree_kids.values():
            v.sort(key=lambda t: (t[4], t[0]))
        crit = {int(r["ID"]): (int(r["Type"]), int(r["Asset"])) for r in A.rows(fl, "Criteria")}
        wiki_ach = {}
        for r in self.wiki.execute("select * from achievements where id is not null order by id, revid desc, page_title"):
            wiki_ach.setdefault(r["id"], []).append(dict(r))
        wcrit = defaultdict(list)
        for r in self.wiki.execute("select * from achievement_criteria where ach_id is not null order by ach_id, idx"):
            wcrit[r["ach_id"]].append(dict(r))

        def leaves(root):
            """leaf criteria of a criteria tree, depth first in the tree's own order (the order the UI lists them)"""
            out, seen = [], set()

            def walk(n):
                if n in seen:
                    return
                seen.add(n)
                for ch in tree_kids.get(n, []):
                    if ch[2]:
                        out.append(ch)
                    if ch[0] in tree_kids:
                        walk(ch[0])
            if root in tree and tree[root][2]:
                out.append(tree[root])
            walk(root)
            return out

        def quest_loc(qid):
            q = quests.get(qid)
            if not q:
                return None
            for role in ("start", "end"):
                for e in q[role]:
                    if e["coords"]:
                        c = e["coords"][0]
                        return {"map": c["map"], "x": c["x"], "y": c["y"], "via": f"quest-{role}", "quest": qid}
            return None

        def page_loc(page, via):
            pts = self.page_all_points(page, fl)
            if not pts:
                return None
            best = next((p for p in pts if p["exact_version"]), pts[0])
            ref_pages.add(page)
            return {"map": best["map"], "x": best["x"], "y": best["y"], "via": via, "page": page,
                    "revid": self.rev(page), "exact_version": best["exact_version"]}

        out = []
        for r in sorted(A.rows(fl, "Achievement"), key=lambda r: int(r["ID"])):
            aid = int(r["ID"])
            flags = int(r["Flags"])
            criteria = []
            for t in leaves(int(r["Criteria_tree"])) if int(r["Criteria_tree"]) else []:
                ctype, asset = crit.get(t[2], (None, None))
                c = {"tree": t[0], "criteria": t[2], "type": ctype, "type_name": CRITERIA_TYPE.get(ctype),
                     "asset": asset, "amount": t[3] or None, "text": t[5] or None, "location": None}
                if ctype == 27 and asset:
                    c["location"] = quest_loc(asset)
                elif ctype == 0 and asset and self.npc_by_id.get(asset):
                    c["location"] = page_loc(self.npc_by_id[asset][0], "npc-page")
                elif ctype == 68 and asset and self.obj_by_id.get(asset):
                    c["location"] = page_loc(self.obj_by_id[asset][0], "object-page")
                criteria.append(c)
            wiki = None
            pages = wiki_ach.get(aid) or []
            if pages:
                title = r["Title_lang"] or ""
                w = next((p for p in pages if (p["name"] or "").lower() == title.lower()), pages[0])
                wc = []
                for c in wcrit.get(aid, []):
                    loc = None
                    if c["quest_id"]:
                        loc = quest_loc(c["quest_id"])
                    elif c["link_title"]:
                        lp, lk = self.g.resolve_title(c["link_title"])
                        if lk in ("npc", "object", "place"):
                            loc = page_loc(lp, f"{lk}-page")
                    wc.append({"text": c["text"] or None, "link": c["link_title"], "quest": c["quest_id"],
                               "location": loc})
                wiki = {"page": w["page_title"], "revid": w["revid"], "category": w["category"] or None,
                        "criteria": wc}
            fac = int(r["Faction"])
            rec = {
                "id": aid,
                "name": r["Title_lang"] or (wiki and pages[0]["name"]) or None,
                "description": r["Description_lang"] or None,
                "reward": r.get("Reward_lang") or None,
                "category": {"id": int(r["Category"]), "path": cat_path(int(r["Category"]))},
                "points": int(r["Points"]),
                "faction": {-1: "Both", 0: "Horde", 1: "Alliance"}.get(fac, str(fac)),
                "flags": flags,
                "statistic": bool(flags & ACH_FLAG_COUNTER),
                "guild": bool(flags & ACH_FLAG_GUILD),
                "account_wide": bool(flags & ACH_FLAG_ACCOUNT),
                "criteria": criteria,
                "wiki": wiki,
                "source": {"db2": {"table": "Achievement", "build": build},
                           **({"wiki": {"page": wiki["page"], "revid": wiki["revid"]}} if wiki else {})},
            }
            out.append(rec)
        return out

    # ---- missions (retail GarrMission) ------------------------------------------------------------------
    def missions(self, fl):
        A = self.A
        if not A.csv_path(fl, "GarrMission"):
            return []
        build = A.build(fl)
        out = []
        for r in sorted(A.rows(fl, "GarrMission"), key=lambda r: int(r["ID"])):
            gt = int(r["GarrTypeID"])
            out.append({
                "id": int(r["ID"]), "name": r["Name_lang"] or None, "location": r["Location_lang"] or None,
                "description": r["Description_lang"] or None, "garrison_type": gt,
                "garrison_type_name": GARR_TYPE.get(gt), "mission_type": int(r["GarrMissionTypeID"]),
                "follower_type": int(r["GarrFollowerTypeID"]), "max_followers": int(r["MaxFollowers"]),
                "target_level": int(r["TargetLevel"]), "target_item_level": int(r["TargetItemLevel"]),
                "duration_s": int(r["MissionDuration"]), "travel_s": int(r["TravelDuration"]),
                "cost": int(r["MissionCost"]), "cost_currency": int(r["MissionCostCurrencyTypesID"]),
                "area_id": int(r["AreaID"]), "map_pos": [float(r["MapPos_0"]), float(r["MapPos_1"])],
                "source": {"db2": {"table": "GarrMission", "build": build}},
            })
        return out

    # ---- files ------------------------------------------------------------------------------------------
    def write_maps(self, fl):
        maps = self.g.atlas.sets[fl].maps
        lines = ["{", f' "flavor": {json.dumps(fl)},',
                 f' "source": {{"tables": "UiMap + UiMapAssignment", "build": {json.dumps(self.A.maps_build(fl))}}},',
                 ' "fields": ["id", "name", "instance", "topX", "leftY", "width", "height", "parent", "type"],',
                 ' "maps": [']
        ids = sorted(maps)
        for i, mid in enumerate(ids):
            m = maps[mid]
            row = [mid, m["name"], m["inst"], m["topX"], m["leftY"], m["w"], m["h"], m["parent"], m["type"]]
            lines.append("  " + json.dumps(row, ensure_ascii=False) + ("," if i < len(ids) - 1 else ""))
        lines += [" ]", "}"]
        C.write_if_changed(self.data_dir / fl / "maps.json", "\n".join(lines) + "\n")
        return len(ids)

    def write_questv2(self, fl, excluded):
        ids = sorted(self.g.qv2[fl])
        exc = sorted(excluded.items())
        lines = ["{", f' "flavor": {json.dumps(fl)},', ' "table": "QuestV2",',
                 f' "build": {json.dumps(self.A.build(fl))},', f' "count": {len(ids)},',
                 ' "excluded": [']
        for i, (qid, (why, page)) in enumerate(exc):
            lines.append("  " + json.dumps({"id": qid, "page": page, "revid": self.rev(page), "reason": why},
                                           ensure_ascii=False) + ("," if i < len(exc) - 1 else ""))
        lines.append(" ],")
        lines.append(' "ids": [')
        chunks = [ids[i:i + 20] for i in range(0, len(ids), 20)]
        for i, ch in enumerate(chunks):
            lines.append("  " + ",".join(map(str, ch)) + ("," if i < len(chunks) - 1 else ""))
        lines += [" ]", "}"]
        C.write_if_changed(self.data_dir / fl / "questv2.json", "\n".join(lines) + "\n")

    def run(self, flavors=C.FLAVORS):
        chosen, excluded, flavors_of = self.membership()
        meta_counts, used_pages = {}, set()
        for fl in flavors:
            self.log(f"[{fl}] quests ...")
            quests, ref_pages, st, _poi = self.export_flavor(fl, chosen, excluded, flavors_of)
            achievements = self.achievements(fl, quests, ref_pages)
            missions = self.missions(fl)
            npcs, objects = self.npc_records(fl, ref_pages)
            for q in quests.values():
                used_pages.add(q["source"]["wiki"]["page"])
            used_pages.update(ref_pages)
            for a in achievements:
                if a["wiki"]:
                    used_pages.add(a["wiki"]["page"])
            counts = {"quests": len(quests), "npcs": len(npcs), "objects": len(objects),
                      "achievements": len(achievements), "missions": len(missions)}
            C.write_kind(fl, "quests", list(quests.values()), self.data_dir)
            C.write_kind(fl, "npcs", npcs, self.data_dir)
            C.write_kind(fl, "objects", objects, self.data_dir)
            for kind, recs in (("achievements", achievements), ("missions", missions)):
                if recs:
                    C.write_kind(fl, kind, recs, self.data_dir)
                else:
                    C.write_kind(fl, kind, [], self.data_dir)
                    d = self.data_dir / fl / kind
                    if d.exists() and not any(d.iterdir()):
                        d.rmdir()
            counts["maps"] = self.write_maps(fl)
            self.write_questv2(fl, excluded[fl])
            counts["questv2"] = len(self.g.qv2[fl])
            counts["questv2_excluded_by_wiki"] = len(excluded[fl])
            counts["questv2_without_wiki_page"] = len(self.g.qv2[fl] - set(r["id"] for r in self.g.rows))
            counts["addon_crosscheck"] = {k: st[k] for k in ("addon_flavor_quests", "addon_only", "data_only",
                                                             "prereq_quests", "prereq_same_ids_as_addon")}
            counts["prerequisite_split"] = {k: st[k] for k in ("prereq_breadcrumb_split", "prereq_optional_split",
                                                               "prereq_multi_group")}
            if fl == "retail":
                counts["retail_turnin_check"] = {"compared": st["turnin_compared"],
                                                 "over_50_yd": st["turnin_over_50yd"]}
                counts["retail_poi_blobs"] = dict(sorted(self.poi_stats.items()))
            meta_counts[fl] = counts
            self.log(f"[{fl}] {counts}")
            del quests, achievements, missions, npcs, objects
        ts = sorted(t for p in used_pages for t in [(self.revs.get(p) or (None, None))[1]] if t)
        meta = {
            "schema_version": C.SCHEMA_VERSION,
            "generator": GENERATOR,
            "flavors": {fl: C.FLAVOR_NAMES[fl] for fl in C.FLAVORS},
            "sources": {
                "wiki": {"site": "https://warcraft.wiki.gg", "licence": "CC BY-SA 4.0",
                         "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                         "pages_used": len(used_pages), "pages_without_revid": sum(1 for p in used_pages if not self.rev(p)),
                         "oldest_revision": ts[0] if ts else None, "newest_revision": ts[-1] if ts else None},
                "db2": {fl: {"build": self.A.build(fl),
                             "tables": sorted(t for t in USED_TABLES.get(fl, ("QuestV2",)) if self.A.csv_path(fl, t)),
                             "maps": {"tables": "UiMap + UiMapAssignment", "build": self.A.maps_build(fl)}}
                        for fl in C.FLAVORS},
            },
            "counts": meta_counts,
        }
        old = {}
        mp = self.data_dir / "meta.json"
        if mp.exists():
            old = C.load_json(mp)
        if set(flavors) != set(C.FLAVORS) and old.get("counts"):
            merged = dict(old["counts"])
            merged.update(meta_counts)
            meta["counts"] = {fl: merged[fl] for fl in C.FLAVORS if fl in merged}
        C.write_if_changed(mp, C.dump_json(meta))
        return meta
