# wow-completionist-data :: tools/cgdata/evidence.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Which map a wiki coordinate row was written on, decided row by row from Blizzard positions, and how far a shipped
point is from Blizzard's position for the same NPC.

The Warcraft Wiki is retail-first, but many pages still carry numbers read off the pre-Cataclysm (Classic) map of a
zone, and the two maps of one zone often differ by several map units.  Nothing on the page says which it is, and it
varies page by page inside one zone.  So every untagged row (no "(Classic)" / "(Burning Crusade)" / "(Forever)" zone,
not on a Classic page) is read both ways and compared with Blizzard's own position of the same NPC or object:

* the retail client's quest turn-in pin (QuestPOIBlob, ObjectiveIndex -1, a single point) of every retail quest
  whose wiki ender is that page (or, for a {{co}} in a quest page's own start/end field, that quest's pin), and
* the flight points (TaxiNodes, Classic Era and retail) for flight-master pages.

Read on the retail map and within TOL yards of a Blizzard position: "retail".  Read on the Classic map: "classic".
Both ways (the two maps agree there): "either".  Neither: "conflict".  Only Blizzard positions inside the row's
own zone map count.  A row without evidence takes its zone's default: "classic" when at least ZONE_MIN checked rows
of that zone are Classic numbers and they outnumber the retail ones, else "retail" (the wiki's convention).  NPC /
object page rows and the {{co}} of quest pages are counted apart (a quest written after Cataclysm says nothing about
how an old NPC page was written).  These defaults replace the addon's hand-made KEEP_NUMBERS zone list
(docs/SOURCES.md says why).

Nothing here is shipped as a table of its own.  It decides how each wiki point is converted; each shipped wiki point
says how it was read (`coord_source.read_as` / `read_by`), what it was checked against (`coord_source.check`) and
the resulting `confidence` (docs/SCHEMA.md).
"""
import re
from collections import Counter, defaultdict

TOL = 50.0              # yards: a point this close to Blizzard's position for the same NPC agrees with it
ZONE_MIN = 3            # checked Classic-number rows a zone needs before its unchecked rows are read as Classic numbers
CONFLICT_SHARE = 0.25   # a zone whose checked rows disagree with Blizzard more often than this: unchecked rows are low
FM_TITLE = re.compile(r"^\s*\|\s*title\s*=\s*([^\n|]*)", re.I | re.M)
FM_WORDS = re.compile(r"flight master|gryphon master|wind rider master|hippogryph master|bat handler|"
                      r"dragonhawk master|wyvern master|flightmaster|griffon master|flight path", re.I)


def norm(s):
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def is_flight_master(wikitext):
    """the page's infobox title names a flight-master role (Gryphon Master, Wind Rider Master, ...)"""
    m = FM_TITLE.search((wikitext or "")[:3000])
    return bool(m and FM_WORDS.search(m.group(1)))


def inside(m, inst, wx, wy, margin=0.05):
    """world point on the map rectangle m (with a margin), same continent instance"""
    if not m or not m["w"] or not m["h"] or m["inst"] != inst:
        return False
    x01 = (m["leftY"] - wy) / m["w"]
    y01 = (m["topX"] - wx) / m["h"]
    return -margin <= x01 <= 1 + margin and -margin <= y01 <= 1 + margin


class Evidence:
    """refs are (source, id, instance, worldX, worldY, quest) tuples; source "QuestPOIBlob" or "TaxiNodes:<flavor>"."""

    def __init__(self, atlas):
        self.atlas = atlas
        self.rows = {}                     # key + (zone, x, y) -> verdict dict
        self.zone_counts = defaultdict(Counter)
        self.zone_default = {}

    def zone_key(self, zone):
        R = self.atlas.sets["retail"]
        mr = R.resolve(zone)
        return norm(R.maps[mr]["name"]) if mr is not None else norm(re.sub(r"\s*\([^()]*\)\s*$", "", zone or ""))

    def classify(self, key, rows, refs):
        """rows: [(zone, x, y, classic)] of one page (or one quest field); records a verdict for each untagged row"""
        R, E = self.atlas.sets["retail"], self.atlas.sets["era"]
        for zone, x, y, classic in rows:
            if self.atlas.source_set(zone, bool(classic)) != "retail":
                continue
            k = key + (zone, x, y)
            if k in self.rows:
                continue
            mr = R.resolve(zone)
            wr = R.to_world(mr, x, y) if mr is not None else None
            me = E.resolve(zone)
            wc = E.to_world(me, x, y) if me is not None else None
            v = {"verdict": None, "yards": None, "ref": None,
                 "differs": bool(wr and wc and wr[0] == wc[0] and dist(wr[1:], wc[1:]) > TOL)}
            best = {"retail": None, "classic": None}
            zmap = R.maps.get(mr) if mr is not None else None
            for ref in refs or ():
                _src, _rid, inst, wx, wy, _q = ref
                if not inside(zmap, inst, wx, wy):
                    continue
                for name, w in (("retail", wr), ("classic", wc)):
                    if w and w[0] == inst:
                        d = dist(w[1:], (wx, wy))
                        if best[name] is None or d < best[name][0]:
                            best[name] = (d, ref)
            if best["retail"] or best["classic"]:
                ok = {n: b is not None and b[0] <= TOL for n, b in best.items()}
                cands = [b for b in best.values() if b]
                if ok["retail"] and ok["classic"]:
                    v["verdict"], pick = "either", min(cands, key=lambda t: t[0])
                elif ok["retail"]:
                    v["verdict"], pick = "retail", best["retail"]
                elif ok["classic"]:
                    v["verdict"], pick = "classic", best["classic"]
                else:
                    v["verdict"], pick = "conflict", min(cands, key=lambda t: t[0])
                v["yards"], v["ref"] = round(pick[0]), pick[1]
                zc = self.zone_counts[(key[0], self.zone_key(zone))]
                zc["checked"] += 1
                if v["verdict"] == "conflict":
                    zc["conflict"] += 1
                elif v["verdict"] in ("retail", "classic") and v["differs"]:
                    zc[v["verdict"]] += 1
            self.rows[k] = v

    def finish(self):
        for zk, c in sorted(self.zone_counts.items()):
            self.zone_default[zk] = "classic" if c["classic"] >= ZONE_MIN and c["classic"] > c["retail"] else "retail"

    def verdict(self, key, zone, x, y):
        return self.rows.get(key + (zone, x, y))

    def reading(self, key, zone, x, y):
        """-> (read_as "retail"/"classic", read_by "check"/"zone-default"/"default") for an untagged row"""
        v = self.rows.get(key + (zone, x, y))
        if v and v["verdict"] in ("retail", "classic"):
            return v["verdict"], "check"
        if v and v["verdict"] == "either":
            return "retail", "check"
        zd = self.zone_default.get((key[0], self.zone_key(zone)))
        return (zd, "zone-default") if zd else ("retail", "default")

    def counts(self, key, zone):
        return self.zone_counts.get((key[0], self.zone_key(zone)))

    def classic_zones(self, kind):
        return sorted(z for (k, z), d in self.zone_default.items() if d == "classic" and k == kind)

    def summary(self):
        out = {"tolerance_yd": TOL, "zone_min": ZONE_MIN, "conflict_share": CONFLICT_SHARE}
        for kind, label in (("page", "npc_page_rows"), ("quest", "quest_page_rows")):
            verdicts = Counter(v["verdict"] or "no-evidence" for k, v in self.rows.items() if k[0] == kind)
            noisy = sorted(z for (k, z), c in self.zone_counts.items()
                           if k == kind and c["checked"] >= 4 and c["conflict"] / c["checked"] > CONFLICT_SHARE)
            zones = {z: [c["checked"], c["retail"], c["classic"], c["conflict"]]
                     for (k, z), c in sorted(self.zone_counts.items()) if k == kind}
            out[label] = {"untagged_rows_with_evidence": sum(verdicts.values()), "verdicts": dict(sorted(verdicts.items())),
                          "zones_read_as_classic": self.classic_zones(kind), "zones_mostly_conflicting": noisy,
                          "zones_fields": ["checked", "retail", "classic", "conflict"], "zones": zones}
        return out
