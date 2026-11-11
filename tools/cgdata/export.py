# wow-completionist-data :: tools/cgdata/export.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Stage 1 of tools/build_db.py: the addon's parsed Warcraft Wiki tables + pinned Blizzard DB2 tables -> data/.

Reads (never writes) the addon repository (github.com/danielalanbates/wow-completionist-guide):
  tools/wiki/wiki.sqlite              parsed wiki tables (tools/wiki/parse_wiki.py)
  tools/wiki/cache/wiki_raw.sqlite    raw wikitext + revision ids (tools/wiki/fetch_wiki.py, fetch_titles.py)
  tools/db2/<flavor>/*.csv + BUILD    DB2 tables pinned to one build per client (tools/wiki/fetch_db2.py)
  tools/maps_<flavor>.lua             UiMap/UiMapAssignment per client (tools/gen_maps.py), used only when
                                      cache/db2/<flavor>/ (tools/fetch_db2.py here) has no map tables of the DB2 build
and imports the addon's own logic by path so both projects read the wiki the same way:
  tools/wiki/wikimaps.py         zone name -> uiMapID, map sets, world <-> map conversion
  tools/wiki/gen_wiki_guides.py  flavor membership rules, page-variant choice, best rows on an NPC page
  tools/wiki/wikitext.py         template / link helpers
Which map an untagged wiki row was written on is decided here, row by row, from Blizzard positions
(tools/cgdata/evidence.py); the addon's KEEP_NUMBERS zone list is not used.
Nothing here reads third-party addon data or any commercial guide data.
"""
import csv
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import common as C
from . import maps as MAPS
from . import names as N
from .evidence import CONFLICT_SHARE, TOL, Evidence, dist, inside, is_flight_master
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
READ_LABEL = {"era": "classic", "retail": "retail", "tbc": "tbc", "forever": "forever", "mop": "mop"}
AMBIGUOUS_NAMES = 3      # an id that this many differently named wiki pages claim is left out


def r1(v):
    return round(float(v) + 0.0, 1)


def strip_suffix(title):
    return SUFFIX.sub("", title or "").strip() or title


def split_list(s):
    parts = re.split(r",|/|\band\b|\bor\b", s or "")
    return [p.strip() for p in parts if p.strip()]


def int_list(s):
    return list(dict.fromkeys(int(x) for x in re.findall(r"\d+", s or "")))


def name_key(r):
    return re.sub(r"[^a-z0-9]", "", (r["name"] or strip_suffix(r["page_title"]) or "").lower())


def name_groups(rows):
    """rows (best first) -> groups of rows that name the same quest (equal or near-equal names, e.g. a possessive
    spelled two ways), in the order of their best row"""
    groups = []
    for r in rows:
        k = name_key(r)
        for g in groups:
            gk = name_key(g[0])
            if k == gk or (k and gk and difflib.SequenceMatcher(None, k, gk).ratio() >= 0.9):
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def title_side(title):
    m = re.search(r"\((alliance|horde)\)\s*$", title or "", re.I)
    return m.group(1).capitalize() if m else None


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
        con = sqlite3_connect_ro(path)
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


def sqlite3_connect_ro(path):
    import sqlite3
    con = sqlite3.connect(Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


class Exporter:
    def __init__(self, addon, data_dir=C.DATA, log=print):
        self.A = addon
        self.data_dir = Path(data_dir)
        self.log = log
        G = addon.G
        db = addon.ro(addon.wiki_db)
        self.wiki = db
        # a read-only twin of gen_wiki_guides.Gen (no fallback guides, no SQL writes): its page_rows / page_points /
        # resolve_title are reused; placement and the version check are done here (place_row, exact_of)
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
        # map geometry of the same build as each client's DB2 tables (cache/db2, tools/fetch_db2.py) when present
        self.maps_build_of = {}
        for fl in C.FLAVORS:
            t = MAPS.map_table(fl)
            cb = MAPS.cache_build(fl)
            if t and cb == addon.build(fl):
                MAPS.apply_to_mapset(g.atlas.sets[fl], t)
                self.maps_build_of[fl] = cb.split()[-1]
            else:
                self.maps_build_of[fl] = addon.maps_build(fl)
        # flight points per client (TaxiNodes, same build as the client's DB2)
        self.taxi_refs = {}
        self.taxi_build = {}
        for fl in C.FLAVORS:
            cb = MAPS.cache_build(fl)
            nodes = MAPS.taxi_nodes(fl) if cb == addon.build(fl) else []
            self.taxi_build[fl] = cb if nodes else None
            self.taxi_refs[fl] = [(f"TaxiNodes:{fl}", nid, inst, wx, wy, None) for nid, _n, inst, wx, wy in nodes]
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
        self.faction_by_page = {r["page_title"]: N.faction(r["faction"]) for r in g.rows}
        self.row_by_page = {}
        for r in g.rows:
            self.row_by_page.setdefault(r["page_title"], r)
        self.dropped_links = []
        self.revs = {}
        self.prev, self.self_bc = {}, {}
        self.fm_pages = set()
        self._scan_raw()
        self.ev = Evidence(g.atlas)
        self.place_cache = {}
        self.differs_cache = {}
        self.page_pins = {}
        self.quest_pin = {}
        self.poi_retail = None

    # ---- raw wikitext: revisions, `previous` fields, breadcrumb leads, flight masters --------------------
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
        with_rows = set(self.g.npc_pts)
        for r in raw.execute("select title, substr(wikitext, 1, 3000) as head from pages order by title"):
            if r["title"] in with_rows and is_flight_master(r["head"]):
                self.fm_pages.add(r["title"])
        raw.close()

    def rev(self, title):
        return (self.revs.get(title) or (None, None))[0]

    def wiki_src(self, page, via, **extra):
        d = {"type": "wiki", "page": page, "revid": self.rev(page), "via": via}
        d.update(extra)
        return d

    # ---- placing wiki rows ------------------------------------------------------------------------------
    def place_row(self, zone, x, y, fl, classic, added, read_as):
        """one wiki (zone, x, y) row -> ((uiMapID, x, y), source map set) on client `fl`, or None.
        Adapted from the addon's wikimaps.Atlas.place (same author) with one change: an untagged row is read on the
        map `read_as` says (evidence.py) instead of the addon's per-zone KEEP_NUMBERS list."""
        k = (zone, x, y, fl, classic, added, read_as)
        if k in self.place_cache:
            return self.place_cache[k]
        atlas = self.g.atlas
        src = atlas.source_set(zone, classic)
        draenor = "alternate universe" in (zone or "").lower()
        if src == "retail" and read_as == "classic" and atlas.sets["era"].resolve(zone, added, draenor) is not None:
            src = "era"
        S = atlas.sets[src]
        smid = S.resolve(zone, added, draenor)
        if smid is None:
            for other in ("forever", "era", "tbc", "mop", "retail"):
                if other != src:
                    cand = atlas.sets[other].resolve(zone, added, draenor)
                    if cand is not None:
                        src, S, smid = other, atlas.sets[other], cand
                        break
        res = None
        if smid is not None:
            T = atlas.sets[fl]
            if src == fl:
                res = ((smid, x, y), src)
            else:
                sname = S.maps[smid]["name"]
                w = S.to_world(smid, x, y)
                if w is None:
                    tmid = T.resolve(sname)
                    res = ((tmid, x, y), src) if tmid is not None else None
                else:
                    r = T.from_world(w[0], w[1], w[2], prefer_name=sname, also_prefer=S.ancestors(smid))
                    res = (r, src) if r else None
        self.place_cache[k] = res
        return res

    def differs(self, zone, x, y):
        """the retail-map and Classic-map readings of a row are more than TOL yards apart"""
        k = (zone, x, y)
        if k not in self.differs_cache:
            R, E = self.g.atlas.sets["retail"], self.g.atlas.sets["era"]
            mr, me = R.resolve(zone), E.resolve(zone)
            wr = R.to_world(mr, x, y) if mr is not None else None
            wc = E.to_world(me, x, y) if me is not None else None
            self.differs_cache[k] = bool(wr and wc and wr[0] == wc[0] and dist(wr[1:], wc[1:]) > TOL)
        return self.differs_cache[k]

    def reading(self, key, zone, x, y, classic):
        if self.g.atlas.source_set(zone, classic) != "retail":
            return None, "tag"
        return self.ev.reading(key, zone, x, y)

    def place_group(self, rows, fl, added, home_name, key):
        """rows [(zone, x, y, classic, badge)] -> the points on one map like the addon's Gen.coords_list (rows in the
        guide's own zone first, at most four), plus how the first of them was read"""
        placed = []
        for zone, x, y, classic, badge in rows:
            read_as, read_by = self.reading(key, zone, x, y, bool(classic))
            res = self.place_row(zone, x, y, fl, bool(classic), added, read_as)
            if res:
                placed.append((res[0], res[1], read_by, zone, x, y, bool(classic), badge))
        if not placed:
            return None
        if home_name:
            hn = self.A.wm.norm(home_name)
            inz = [p for p in placed if self.A.wm.norm(self.g.atlas.sets[fl].maps[p[0][0]]["name"]) == hn]
            if inz:
                placed = inz
        mid = placed[0][0][0]
        same = [p for p in placed if p[0][0] == mid][:4]
        f = same[0]
        return {"map": mid, "pts": [(r1(p[0][1]), r1(p[0][2])) for p in same], "src": f[1], "read_by": f[2], "key": key,
                "zone": f[3], "row": (f[3], f[4], f[5]), "classic": f[6], "badge": f[7],
                "differs": f[2] != "tag" and self.differs(f[3], f[4], f[5])}

    def exact_of(self, fl, grp, extra=False):
        """written for this client's game version?  Retail: a row read on the retail map.  MoP: the addon's rule
        (badged rows) and not read on the Classic map.  Classic clients: the addon's rule (Classic page / zone,
        badged row) or a row whose Classic-map reading matched a Blizzard position."""
        if fl == "retail":
            return grp["src"] == "retail"
        base = bool(self.A.G.Gen.exact(fl, grp["classic"], grp["badge"])) or bool(extra)
        if fl == "mop":
            return base and grp["src"] not in ("era", "tbc", "forever")
        return base or (grp["read_by"] == "check" and grp["src"] == "era")

    def refs_for(self, fl, page=None, quest_refs=(), src=None):
        """Blizzard positions a point on client `fl` may be checked against: turn-in pins on retail and MoP (and on
        Classic clients for rows read on the Classic map: a match there means the NPC has not moved), and the
        client's own flight points for flight-master pages"""
        out = []
        pins = list(quest_refs) + (self.page_pins.get(page, []) if page else [])
        if fl in ("retail", "mop") or src == "era":
            out += pins
        if page and page in self.fm_pages:
            out += self.taxi_refs[fl]
        return out

    def ref_build(self, src):
        if src == "QuestPOIBlob":
            return self.A.build("retail")
        return self.taxi_build.get(src.split(":", 1)[1]) or ""

    def check(self, fl, mid, x, y, refs):
        if not refs:
            return None
        T = self.g.atlas.sets[fl]
        m = T.maps.get(mid)
        w = T.to_world(mid, x, y)
        if not w:
            return None
        best = None
        for ref in refs:
            src, rid, inst, wx, wy, q = ref
            if inst != w[0] or not inside(m, inst, wx, wy):
                continue
            d = dist(w[1:], (wx, wy))
            if best is None or (d, ref[:2]) < (best[0], best[1][:2]):
                best = (d, ref)
        if not best:
            return None
        src, rid, _inst, _wx, _wy, q = best[1]
        out = {"against": src.split(":", 1)[0], "build": self.ref_build(src), "id": rid, "yards": int(round(best[0]))}
        if q:
            out["quest"] = q
        return out

    def zone_share(self, key, zone):
        c = self.ev.counts(key, zone)
        if not c or c["checked"] < 4:
            return None
        return c["conflict"] / c["checked"]

    def confidence(self, exact, grp, chk):
        if chk is not None:
            return "high" if chk["yards"] <= TOL else "low"
        if grp["read_by"] in ("zone-default", "default") and grp["differs"]:
            return "low"     # unverified, and the two readings of the row are more than TOL apart
        if not exact:
            return "medium" if grp["read_by"] == "check" else "low"
        share = self.zone_share(grp["key"], grp["zone"])
        if share is not None and share > CONFLICT_SHARE:
            return "low"
        return "medium"

    def locate(self, holder, fl, grp, src_dict, exact, refs):
        """fill coords / coord_source / exact_version / confidence of an endpoint or objective from a placed group"""
        holder["coords"] = [{"map": grp["map"], "x": x, "y": y} for x, y in grp["pts"]]
        chk = self.check(fl, grp["map"], grp["pts"][0][0], grp["pts"][0][1], refs)
        cs = dict(src_dict)
        cs["read_as"] = READ_LABEL[grp["src"]]
        cs["read_by"] = grp["read_by"]
        if chk:
            cs["check"] = chk
            if chk["yards"] > TOL:
                exact = False
        holder["coord_source"] = cs
        holder["exact_version"] = bool(exact)
        holder["confidence"] = self.confidence(exact, grp, chk)

    def page_rows5(self, page):
        pc = bool(self.g.npc_classic.get(page))
        return [(z, x, y, bool(c) or pc, b) for z, x, y, _s, b, c in self.g.page_rows(page)]

    def entity_coords(self, title, fl, added, home_name, depth=0):
        """-> (group, page, item_page) for a linked page; items follow their drop sources once"""
        g = self.g
        page, kind = g.resolve_title(title)
        if not page:
            return None
        if kind in ("npc", "object", "place") or page in g.npc_pts:
            pts, _ex = g.page_points(page, fl, home_name)
            if pts:
                rows_by = {}
                for row in self.page_rows5(page):
                    rows_by.setdefault(row[:3], row)
                rows = [rows_by.get((z, x, y), (z, x, y, bool(g.npc_classic.get(page)), 0)) for z, x, y in pts]
                grp = self.place_group(rows, fl, added, home_name, ("page", page))
                if grp:
                    return grp, page, None
        if depth == 0 and page in g.items:
            for src in g.items[page][1]:
                c = self.entity_coords(src, fl, added, home_name, 1)
                if c:
                    return c[0], c[1], page
        return None

    def page_all_points(self, page, fl):
        """every coordinate row of an NPC/object page placed on this client's maps (deduplicated, page order)"""
        out, seen = [], set()
        pc = bool(self.g.npc_classic.get(page))
        for zone, x, y, via, badge, classic in self.g.page_rows(page):
            grp = self.place_group([(zone, x, y, bool(classic) or pc, badge)], fl, None, None, ("page", page))
            if not grp:
                continue
            k = (grp["map"], grp["pts"][0][0], grp["pts"][0][1])
            if k in seen:
                continue
            seen.add(k)
            exact = self.exact_of(fl, grp)
            chk = self.check(fl, k[0], k[1], k[2], self.refs_for(fl, page, src=grp["src"]))
            if chk and chk["yards"] > TOL:
                exact = False
            pt = {"map": k[0], "x": k[1], "y": k[2], "exact_version": bool(exact),
                  "via": (via or "").split(":")[0] or None, "read_as": READ_LABEL[grp["src"]], "read_by": grp["read_by"],
                  "confidence": self.confidence(exact, grp, chk)}
            if chk:
                pt["check"] = chk
            out.append(pt)
        return out

    @staticmethod
    def coords_of(mid, pts):
        return [{"map": mid, "x": x, "y": y} for x, y in pts]

    # ---- retail quest POI (Blizzard DB2) ----------------------------------------------------------------
    def load_poi(self, fl):
        """quest -> {"turnin": (blobID, map, x, y) or None, "pin": (blobID, instance, worldX, worldY) when that
        turn-in blob is a single point, "obj": {QuestObjective.ID: point}, "idx": {ObjectiveIndex: point}};
        ObjectiveIndex 32 (the client's next-waypoint hint) is skipped"""
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
            rec = poi.setdefault(qid, {"turnin": None, "pin": None, "obj": {}, "idx": {}})
            if oi == -1:
                if rec["turnin"] is None:
                    rec["turnin"] = pt
                    if n == 1 and int(b["NumPoints"]) == 1:
                        rec["pin"] = (bid, int(b["MapID"]), wx, wy)
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

    # ---- membership -------------------------------------------------------------------------------------
    def membership(self):
        """-> chosen[fl][qid] = wiki row, excluded[fl][qid] = (reason, page), flavors_of[qid] = [fl...],
        variants[fl][qid] = [row] (the other faction's page of a faction twin), conflicts[fl][qid] = [row]
        (pages that give the id to a differently named quest)"""
        G, g = self.A.G, self.g
        chosen = {fl: {} for fl in C.FLAVORS}
        excluded = {fl: {} for fl in C.FLAVORS}
        variants = {fl: {} for fl in C.FLAVORS}
        conflicts = {fl: {} for fl in C.FLAVORS}
        self.ambiguous = Counter()
        by_id = defaultdict(list)
        for r in g.rows:
            by_id[r["id"]].append(r)
        all_groups = {qid: len(name_groups(sorted(rs, key=lambda r: r["page_title"]))) for qid, rs in by_id.items()}
        for fl in C.FLAVORS:
            pref = G.VARIANT_PREF[fl]

            def rank(r):
                v = (r["variant"] or "").lower()
                return (pref.index(v) if v in pref else len(pref), -(r["revid"] or 0), r["page_title"])
            for qid, rs in sorted(by_id.items()):
                ok_rows, why = [], None
                for r in rs:
                    ok, reason = G.membership(r, fl, g.qv2)
                    if ok:
                        ok_rows.append(r)
                    elif why is None or why == "not in QuestV2":
                        why = reason
                if not ok_rows:
                    if qid in g.qv2[fl]:
                        excluded[fl][qid] = (why or "excluded", sorted(r["page_title"] for r in rs)[0])
                    continue
                ranked = sorted(ok_rows, key=rank)
                groups = name_groups(ranked)
                if all_groups[qid] >= AMBIGUOUS_NAMES:
                    # counted over every page that claims the id, on any client: a placeholder or copied id (788 is on
                    # seventeen unrelated pages), so even a single page passing here is not trustworthy
                    excluded[fl][qid] = (f"ambiguous id: {all_groups[qid]} wiki pages give it to differently named "
                                         f"quests", ranked[0]["page_title"])
                    self.ambiguous[fl] += 1
                    continue
                main = ranked[0]
                ms = N.side(main["faction"])
                other = None
                if ms:
                    other = next((r for r in ranked if N.side(r["faction"]) and N.side(r["faction"]) != ms), None)
                chosen[fl][qid] = main
                if other is not None:
                    variants[fl][qid] = [other]
                rest = [grp[0] for grp in groups if main not in grp and (other is None or other not in grp)]
                if rest:
                    conflicts[fl][qid] = rest
        flavors_of = defaultdict(list)
        for fl in C.FLAVORS:
            for qid in chosen[fl]:
                flavors_of[qid].append(fl)
        return chosen, excluded, flavors_of, variants, conflicts

    def quest_ids(self, title):
        return self.ids_by_title.get(title) or self.ids_by_title.get(self.g.resolve_title(title)[0] or "") or set()

    # ---- evidence pre-pass ------------------------------------------------------------------------------
    def end_entries(self, r):
        ends = json.loads(r["end_json"] or "[]") or json.loads(r["start_json"] or "[]")
        return self.faction_filter(ends, r["faction"])

    @staticmethod
    def faction_filter(entries, faction):
        f = N.side(faction)
        if f:
            return [e for e in entries if N.side(e.get("faction")) in (None, f)] or entries
        return entries

    def entity_pages(self, entries):
        out = set()
        for e in entries:
            if e.get("title"):
                kind, page, _ids = self.entity(e["title"])
                if kind in ("npc", "object") and page:
                    out.add(page)
        return out

    def prepare(self, chosen, variants):
        """Blizzard positions per NPC page and per quest, then a verdict for every untagged wiki row
        (evidence.py).  Must run before any client is exported."""
        self.poi_retail = self.load_poi("retail")
        poi, _q = self.poi_retail
        retail_stats = dict(self.poi_stats)
        self.quest_pin = {qid: rec["pin"] for qid, rec in sorted(poi.items()) if rec.get("pin")}
        page_pins = defaultdict(set)
        rows_retail = [chosen["retail"][q] for q in sorted(chosen["retail"])]
        rows_retail += [v for q in sorted(variants["retail"]) for v in variants["retail"][q]]
        for r in rows_retail:
            pin = self.quest_pin.get(r["id"])
            if not pin:
                continue
            pages = self.entity_pages(self.end_entries(r))
            if len(pages) == 1:
                page_pins[pages.pop()].add(("QuestPOIBlob", pin[0], pin[1], pin[2], pin[3], r["id"]))
        self.page_pins = {p: sorted(v) for p, v in sorted(page_pins.items())}
        taxi_cls = self.taxi_refs["era"] + self.taxi_refs["retail"]
        for page in sorted(self.g.npc_pts):
            refs = list(self.page_pins.get(page, []))
            if page in self.fm_pages:
                refs += taxi_cls
            if refs:
                self.ev.classify(("page", page), [r[:4] for r in self.page_rows5(page)], refs)
        # a {{co}} in a quest page's own start / end field: checked against that quest's turn-in pin (the start only
        # when the quest's giver is also its ender)
        seen = set()
        for fl in C.FLAVORS:
            for qid in sorted(chosen[fl]):
                for r in [chosen[fl][qid]] + variants[fl].get(qid, []):
                    if r["page_title"] in seen:
                        continue
                    seen.add(r["page_title"])
                    pin = self.quest_pin.get(r["id"])
                    if not pin:
                        continue
                    ref = [("QuestPOIBlob", pin[0], pin[1], pin[2], pin[3], r["id"])]
                    starts = self.faction_filter(json.loads(r["start_json"] or "[]"), r["faction"])
                    ends = self.end_entries(r)
                    same = self.entity_pages(starts) == self.entity_pages(ends) and len(self.entity_pages(ends)) == 1
                    pc = bool(r["page_classic"])
                    for role, entries in (("end", ends), ("start", starts if same else [])):
                        rows = [(c[2], c[0], c[1], pc) for e in entries for c in (e.get("coords") or [])]
                        if rows:
                            self.ev.classify(("quest", r["page_title"], role), rows, ref)
        self.ev.finish()
        self.poi_stats = Counter(retail_stats)

    # ---- one quest --------------------------------------------------------------------------------------
    def prerequisites(self, fl, qid, r, chosen):
        pp = self.prev.get(r["page_title"]) or {"groups": [], "basis": "none", "text": ""}
        out = {"required": [], "breadcrumb": [], "optional": [], "in_progress": [], "faction": {},
               "inferred_from_next": [], "basis": pp["basis"]}
        qside = N.side(r["faction"])
        qsides = {qside} if qside else {"Alliance", "Horde"}
        unresolved = 0
        for grp in pp["groups"]:
            alts = []
            for title, fac in grp["titles"]:
                page = self.g.resolve_title(title)[0] or title
                cand = sorted(i for i in self.quest_ids(title) if i in chosen and i != qid)
                # when several wiki pages claim one id, a link to a page other than the one shipped for that id (or
                # its faction twin, or the same quest's page for another version) counts only if the shipped quest
                # is open to every faction this quest is: otherwise it is not the quest the link means
                ids = [i for i in cand if self.links_record(fl, i, page) or qsides <= self.sides_of.get(i, set())]
                if cand and not ids:
                    self.st["prereq_link_to_other_page_of_id"] += 1
                    self.dropped_links.append((fl, qid, title, cand, "other page of id"))
                if qside and ids and not any(qside in self.sides_of.get(i, ()) for i in ids):
                    # a one-faction quest linking the other faction's quest: the wiki usually means the same-named
                    # quest of this quest's own faction ("X" -> "X (Horde)"); without one the link cannot be met
                    alt = sorted(i for i in self.quest_ids(f"{strip_suffix(page)} ({qside})")
                                 if i in chosen and i != qid and qside in self.sides_of.get(i, ()))
                    self.st["prereq_other_faction_" + ("to_own_faction_page" if alt else "dropped")] += 1
                    self.dropped_links.append((fl, qid, title, ids, f"other faction -> {alt}"))
                    ids = alt
                if not ids:
                    unresolved += 1
                own = N.side(self.faction_by_page.get(page) or self.faction_by_page.get(title)) or title_side(title)
                for i in ids:
                    if i not in [a for a, _f, _o in alts]:
                        alts.append((i, fac or None, own))
            if not alts:
                continue
            cls = grp["class"]
            if cls == "required" and len(alts) == 1 and self.self_bc.get(chosen[alts[0][0]]["page_title"]):
                cls = "breadcrumb"
            for i, fac, own in alts:
                if fac:
                    out["faction"][str(i)] = fac
                elif own and qside is None:
                    # a quest both factions take, linking a one-faction quest: that link applies to that faction only
                    out["faction"][str(i)] = own
            if cls == "required":
                out["required"].append([a for a, _f, _o in alts])
            else:
                for a, _f, _o in alts:
                    if a not in out[cls]:
                        out[cls].append(a)
        # "[[A]] <br> [[H]]" on a quest both factions take: one Alliance-only and one Horde-only group are
        # alternatives (each faction needs its own), not both required
        if qside is None and len(out["required"]) >= 2:
            sides = [{out["faction"].get(str(i)) for i in g_} for g_ in out["required"]]
            if all(len(s) == 1 and None not in s for s in sides):
                per = Counter(next(iter(s)) for s in sides)
                if set(per) == {"Alliance", "Horde"} and per["Alliance"] == 1 and per["Horde"] == 1:
                    out["required"] = [[i for g_ in out["required"] for i in g_]]
                    self.st["prereq_faction_merged"] += 1
        if unresolved or pp["basis"] in ("explicit", "list") or (pp["groups"] == [] and pp["text"]):
            out["wiki_text"] = pp["text"][:300]
        if unresolved:
            out["unresolved_links"] = unresolved
        if not out["faction"]:
            del out["faction"]
        else:
            out["faction"] = dict(sorted(out["faction"].items(), key=lambda kv: int(kv[0])))
        return out

    def links_record(self, fl, i, page):
        """is the quest shipped for id i on this client the linked page (the same page, its faction twin, or another
        version's page of the same quest, e.g. "X" for the era record "X (Classic)")?"""
        recs = self.pages_of.get(i, ())
        if page in recs:
            return True
        row = self.row_by_page.get(page)
        if row is None:
            return True     # the link resolved through a redirect / title variant to this id only
        return any(len(name_groups([row, self.row_by_page[p]])) == 1 for p in recs if p in self.row_by_page)

    def quest_record(self, fl, qid, r, ctx):
        G, g = self.A.G, self.g
        maps, chosen, poi, qobj, build, st, ref_pages = (ctx["maps"], ctx["chosen"], ctx["poi"], ctx["qobj"],
                                                         ctx["build"], ctx["st"], ctx["ref_pages"])
        page = r["page_title"]
        added = G.pkey(r["added_patch"])
        classic_q = bool(r["page_classic"])
        variant = (r["variant"] or "").lower()
        page_extra = fl == "mop" and variant in G.VARIANT_FOR and "mop" in G.VARIANT_FOR[variant]
        zone_name = r["zone"] or r["category"] or ""
        zmid = maps.resolve(zone_name, added) if zone_name else None
        home_name = maps.maps[zmid]["name"] if zmid else zone_name
        faction = N.faction(r["faction"])
        starts = json.loads(r["start_json"] or "[]")
        ends = json.loads(r["end_json"] or "[]")
        end_same = not ends
        ends = ends or starts
        starts = self.faction_filter(starts, faction)
        ends = self.faction_filter(ends, faction)
        pq = poi.get(qid)
        pin = pq.get("pin") if pq else None
        pin_ref = [("QuestPOIBlob", pin[0], pin[1], pin[2], pin[3], qid)] if pin else []
        same_actor = (len(self.entity_pages(ends)) == 1 and self.entity_pages(starts) == self.entity_pages(ends))

        def endpoint(e, role):
            if e.get("auto") and not e.get("title"):
                kind, epage, ids = "auto", None, []
            elif e.get("title"):
                kind, epage, ids = self.entity(e["title"])
            else:
                kind, epage, ids = "unknown", None, []
            ep = {"kind": kind, "ids": ids, "name": (e.get("label") or strip_suffix(epage or "") or None),
                  "page": epage, "faction": N.side(e.get("faction")), "coords": [], "coord_source": None,
                  "exact_version": None, "confidence": None}
            qrefs = pin_ref if (role == "end" or same_actor) else []
            if e.get("coords"):
                rows = [(x[2], x[0], x[1], classic_q, 0) for x in e["coords"]]
                grp = self.place_group(rows, fl, added, home_name, ("quest", page, role))
                if grp:
                    self.locate(ep, fl, grp, self.wiki_src(page, "questbox"), self.exact_of(fl, grp, page_extra),
                                self.refs_for(fl, None, qrefs, grp["src"]))
            if not ep["coords"] and e.get("title"):
                c = self.entity_coords(e["title"], fl, added, home_name)
                if c:
                    grp, cpage, item_page = c
                    src = (self.wiki_src(cpage, "item-source", item_page=item_page) if item_page
                           else self.wiki_src(cpage, "entity-page"))
                    refs = self.refs_for(fl, None if item_page else cpage, qrefs if not item_page else (),
                                         grp["src"])
                    self.locate(ep, fl, grp, src, self.exact_of(fl, grp), refs)
                    ref_pages.add(cpage)
            if epage and kind in ("npc", "object"):
                ref_pages.add(epage)
            return ep

        start = [endpoint(e, "start") for e in starts]
        end = [endpoint(e, "end") for e in ends]
        if fl == "retail" and pq and pq["turnin"]:
            e0 = next((e for e in end if e["coords"]), None)
            if e0 is None:
                # Blizzard's turn-in pin when the wiki has no end point
                bid, mid, x, y = pq["turnin"]
                if not end:
                    end = [{"kind": "unknown", "ids": [], "name": None, "page": None, "faction": None, "coords": [],
                            "coord_source": None, "exact_version": None, "confidence": None}]
                end[0]["coords"] = [{"map": mid, "x": x, "y": y}]
                end[0]["coord_source"] = {"type": "db2", "table": "QuestPOIBlob", "build": build, "blob": bid,
                                          "via": "turn-in-pin"}
                end[0]["exact_version"] = True
                end[0]["confidence"] = "high"
            elif pin:
                # the wiki end point against the single-point turn-in pin: more than TOL yards off -> the pin wins,
                # and the record keeps the wiki point it replaced
                c0 = e0["coords"][0]
                T = g.atlas.sets[fl]
                w = T.to_world(c0["map"], c0["x"], c0["y"])
                if w and w[0] == pin[1]:
                    yd = dist(w[1:], pin[2:])
                    st["turnin_compared"] += 1
                    if yd > TOL:
                        st["turnin_over_50yd"] += 1
                        bid, mid, x, y = pq["turnin"]
                        old = e0["coord_source"]
                        e0["coord_source"] = {"type": "db2", "table": "QuestPOIBlob", "build": build, "blob": bid,
                                              "via": "turn-in-pin",
                                              "replaces": {"page": old.get("page"), "revid": old.get("revid"),
                                                           "via": old.get("via"), "map": c0["map"], "x": c0["x"],
                                                           "y": c0["y"], "yards": int(round(yd))}}
                        e0["coords"] = [{"map": mid, "x": x, "y": y}]
                        e0["exact_version"] = True
                        e0["confidence"] = "high"
        # objectives
        bullets = g.objs.get((qid, page), [])
        counted = [b for b in bullets if b["kind"] != "provided"]
        qo = qobj.get(qid, []) if fl == "retail" else []
        by_order = bool(qo) and len(qo) == len(counted)
        # the POI blobs' ObjectiveIndex is the objective's 0-based place in the quest log; it is used only when every
        # indexed blob fits the wiki's bullet count (the addon's retail guides read it the same way)
        by_index = bool(pq and pq["idx"]) and max(pq["idx"]) < len(counted)
        objectives, n_counted = [], 0
        for b in bullets:
            ob = {"index": b["idx"], "kind": b["kind"], "text": b["text"] or None, "count": b["count"],
                  "optional": bool(b["optional"]), "target": None, "coords": [], "coord_source": None,
                  "exact_version": None, "confidence": None}
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
                    rows = [(x[2], x[0], x[1], classic_q, 0) for x in bc]
                    grp = self.place_group(rows, fl, added, home_name, ("quest", page, "objective"))
                    if grp:
                        self.locate(ob, fl, grp, self.wiki_src(page, "objective"), self.exact_of(fl, grp, page_extra),
                                    [])
                if not ob["coords"] and b["target_title"]:
                    c = self.entity_coords(b["target_title"], fl, added, home_name)
                    if c:
                        grp, cpage, item_page = c
                        src = (self.wiki_src(cpage, "item-source", item_page=item_page) if item_page
                               else self.wiki_src(cpage, "entity-page"))
                        self.locate(ob, fl, grp, src, self.exact_of(fl, grp),
                                    self.refs_for(fl, None if item_page else cpage, (), grp["src"]))
                        ref_pages.add(cpage)
                pt = None
                via = None
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
                    ob["confidence"] = "high"
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
                                   "exact_version": True, "confidence": "high"})
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
                      "exact_version": None, "confidence": None, "db2_objective": o["id"], "db2_type": o["type"]}
                pt = (pq["obj"].get(o["id"]) or pq["idx"].get(o["order"])) if pq else None
                if pt:
                    ob["coords"] = [{"map": pt[1], "x": pt[2], "y": pt[3]}]
                    ob["coord_source"] = {"type": "db2", "table": "QuestPOIBlob", "build": build, "blob": pt[0],
                                          "via": "objective-area"}
                    ob["exact_version"] = True
                    ob["confidence"] = "high"
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
        return {
            "id": qid,
            "name": r["name"] or strip_suffix(page),
            "flavors": ctx["flavors_of"][qid],
            "faction": faction,
            "level": r["level"] if (r["level"] or 0) > 0 else None,
            "min_level": r["levelreq"] if (r["levelreq"] or 0) > 0 else None,
            "type": r["qtype"] or None,
            "category": r["category"] or None,
            "zone_map": zone_map,
            "zone_map_source": zone_src,
            "classes": list(dict.fromkeys(N.canon(c, N.CLASSES) for c in split_list(r["classes"]))),
            "races": list(dict.fromkeys(N.canon(c, N.RACES) for c in split_list(r["races"]))),
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

    # ---- one client -------------------------------------------------------------------------------------
    def export_flavor(self, fl, chosen_all, excluded_all, flavors_of, variants_all, conflicts_all):
        G, A = self.A.G, self.A
        chosen = chosen_all[fl]
        poi, qobj = self.poi_retail if fl == "retail" else ({}, {})
        st = Counter()
        self.st = st
        ref_pages = set()          # npc / object pages this flavor's records point at
        ctx = {"maps": self.g.atlas.sets[fl], "chosen": chosen, "poi": poi, "qobj": qobj, "build": A.build(fl),
               "st": st, "ref_pages": ref_pages, "flavors_of": flavors_of}
        self.pages_of = {qid: {r["page_title"]} | {v["page_title"] for v in variants_all[fl].get(qid, [])}
                         for qid, r in chosen.items()}
        self.sides_of = {}
        for qid, r in chosen.items():
            sides = set()
            for x in [r] + variants_all[fl].get(qid, []):
                sides |= {N.side(x["faction"])} if N.side(x["faction"]) else {"Alliance", "Horde"}
            self.sides_of[qid] = sides
        quests = {}
        for qid in sorted(chosen):
            r = chosen[qid]
            q = self.quest_record(fl, qid, r, ctx)
            vs = []
            for vr in variants_all[fl].get(qid, []):
                v = self.quest_record(fl, qid, vr, ctx)
                for k in ("id", "flavors"):
                    del v[k]
                v["source"] = {"wiki": v["source"]["wiki"]}
                vs.append(v)
            if vs:
                q["variants"] = vs
                st["faction_twins"] += 1
            if conflicts_all[fl].get(qid):
                q["id_conflict"] = [{"page": c["page_title"], "revid": c["revid"],
                                     "name": c["name"] or strip_suffix(c["page_title"]),
                                     "faction": N.faction(c["faction"])} for c in conflicts_all[fl][qid]]
                st["id_conflicts"] += 1
            # cross-check with the addon's chain (parse_wiki prev_ids: every non-"(optional)" link, read as any-of)
            prereq = q["prerequisites"]
            addon_pre = {int(p) for p in (r["prev_ids"] or "").split(",") if p and int(p) in chosen and int(p) != qid}
            mine_pre = {i for g_ in prereq["required"] for i in g_} | set(prereq["breadcrumb"]) | set(
                prereq["in_progress"])
            if addon_pre or mine_pre:
                st["prereq_quests"] += 1
                st["prereq_same_ids_as_addon"] += addon_pre == mine_pre
            st["prereq_breadcrumb_split"] += bool(prereq["breadcrumb"])
            st["prereq_optional_split"] += bool(prereq["optional"])
            st["prereq_multi_group"] += len(prereq["required"]) > 1
            quests[qid] = q
        # prerequisites inferred from another quest's `next` when the quest itself names none on this client
        for qid in sorted(quests):
            q = quests[qid]
            for holder in [q] + q.get("variants", []):
                for n in holder["next"]:
                    p = quests[n]["prerequisites"]
                    if not (p["required"] or p["breadcrumb"] or p["optional"] or p["in_progress"]):
                        if qid not in p["inferred_from_next"]:
                            p["inferred_from_next"].append(qid)
        for q in quests.values():
            q["prerequisites"]["inferred_from_next"].sort()
        # addon cross-check: the same membership as the addon's last generator run (flavor_quests), apart from the
        # time-limited types the addon leaves out on purpose and the ambiguous ids left out here
        addon_ids = {row[0] for row in self.wiki.execute("select quest_id from flavor_quests where flavor=?", (fl,))}
        mine = {qid for qid, r in chosen.items() if not G.SKIP_TYPES.search(r["qtype"] or "")}
        amb = {qid for qid, (why, _p) in excluded_all[fl].items() if why.startswith("ambiguous id")}
        st["addon_flavor_quests"] = len(addon_ids)
        st["addon_only"] = len(addon_ids - mine)
        st["addon_only_ambiguous"] = len((addon_ids - mine) & amb)
        st["data_only"] = len(mine - addon_ids)
        return quests, ref_pages, st

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
                        return {"map": c["map"], "x": c["x"], "y": c["y"], "via": f"quest-{role}", "quest": qid,
                                "confidence": e["confidence"]}
            return None

        page_cache = {}

        def page_loc(page, via):
            if page not in page_cache:
                page_cache[page] = self.page_all_points(page, fl)
            pts = page_cache[page]
            if not pts:
                return None
            rank = {"high": 0, "medium": 1, "low": 2}
            best = sorted(pts, key=lambda p: (not p["exact_version"], rank[p["confidence"]]))[0]
            ref_pages.add(page)
            return {"map": best["map"], "x": best["x"], "y": best["y"], "via": via, "page": page,
                    "revid": self.rev(page), "exact_version": best["exact_version"], "confidence": best["confidence"]}

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

    # ---- files ------------------------------------------------------------------------------------------
    def write_maps(self, fl):
        maps = self.g.atlas.sets[fl].maps
        lines = ["{", f' "flavor": {json.dumps(fl)},',
                 f' "source": {{"tables": "UiMap + UiMapAssignment", "build": {json.dumps(self.maps_build_of[fl])}}},',
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
        chosen, excluded, flavors_of, variants, conflicts = self.membership()
        self.prepare(chosen, variants)
        meta_counts, used_pages = {}, set()
        for fl in flavors:
            self.log(f"[{fl}] quests ...")
            quests, ref_pages, st = self.export_flavor(fl, chosen, excluded, flavors_of, variants, conflicts)
            achievements = self.achievements(fl, quests, ref_pages)
            missions = self.missions(fl)
            npcs, objects = self.npc_records(fl, ref_pages)
            for q in quests.values():
                used_pages.add(q["source"]["wiki"]["page"])
                for v in q.get("variants", []):
                    used_pages.add(v["source"]["wiki"]["page"])
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
            counts["questv2_excluded_ambiguous_id"] = self.ambiguous[fl]
            counts["questv2_without_wiki_page"] = len(self.g.qv2[fl] - set(r["id"] for r in self.g.rows))
            counts["faction_twins"] = st["faction_twins"]
            counts["id_conflicts"] = st["id_conflicts"]
            counts["addon_crosscheck"] = {k: st[k] for k in ("addon_flavor_quests", "addon_only", "addon_only_ambiguous",
                                                             "data_only", "prereq_quests", "prereq_same_ids_as_addon")}
            counts["prerequisite_split"] = {k: st[k] for k in ("prereq_breadcrumb_split", "prereq_optional_split",
                                                               "prereq_multi_group", "prereq_faction_merged",
                                                               "prereq_link_to_other_page_of_id",
                                                               "prereq_other_faction_to_own_faction_page",
                                                               "prereq_other_faction_dropped")}
            if fl == "retail":
                counts["retail_turnin_check"] = {"compared": st["turnin_compared"],
                                                 "over_50_yd_replaced_by_pin": st["turnin_over_50yd"]}
                counts["retail_poi_blobs"] = dict(sorted(self.poi_stats.items()))
            meta_counts[fl] = counts
            self.log(f"[{fl}] {counts}")
            del quests, achievements, missions, npcs, objects
        ts = sorted(t for p in used_pages for t in [(self.revs.get(p) or (None, None))[1]] if t)
        evs = self.ev.summary()
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
                             "tables": sorted(set(t for t in USED_TABLES.get(fl, ("QuestV2",)) if self.A.csv_path(fl, t))
                                              | ({"TaxiNodes"} if self.taxi_build.get(fl) else set())),
                             "maps": {"tables": "UiMap + UiMapAssignment", "build": self.maps_build_of[fl]}}
                        for fl in C.FLAVORS},
            },
            "coordinate_reading": {
                "rule": "docs/SCHEMA.md#coordinates; tools/cgdata/evidence.py",
                "checked_against": {"QuestPOIBlob": self.A.build("retail"),
                                    "TaxiNodes": {fl: self.taxi_build[fl] for fl in C.FLAVORS if self.taxi_build[fl]}},
                "npc_pages_with_turnin_pins": len(self.page_pins), "flight_master_pages": len(self.fm_pages),
                **evs,
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
