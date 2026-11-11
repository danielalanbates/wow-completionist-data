# wow-completionist-data :: tests/test_fixes.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
"""Coordinate reading from Blizzard positions, shared quest ids, faction-aware prerequisites, value normalisation,
the build's own record check, and regression checks on the shipped data for the cases the first review found.
Set CG_SKIP_DATA=1 to skip the shipped-data checks."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture  # noqa: E402
import validate  # noqa: E402
from cgdata import common as C  # noqa: E402
from cgdata import names as N  # noqa: E402
from cgdata.evidence import Evidence, is_flight_master  # noqa: E402
from cgdata.export import name_groups  # noqa: E402
from cgdata.sqlite_build import build_sqlite  # noqa: E402


class _Maps:
    def __init__(self, maps):
        self.maps = maps

    def resolve(self, name, *_a):
        name = name.replace(" (Classic)", "")
        return next((mid for mid, m in sorted(self.maps.items()) if m["name"] == name), None)

    def to_world(self, mid, x, y):
        m = self.maps[mid]
        return m["inst"], m["topX"] - y / 100 * m["h"], m["leftY"] - x / 100 * m["w"]


class _Atlas:
    """two map sets of one zone whose Classic rectangle sits 100 yd off the retail one, and one zone that agrees"""

    def __init__(self):
        r = {"name": "Testzone", "inst": 0, "topX": 1000.0, "leftY": 1000.0, "w": 1000.0, "h": 1000.0}
        e = dict(r, topX=1200.0, w=1200.0, h=1200.0, leftY=1100.0)
        same = {"name": "Samezone", "inst": 1, "topX": 1000.0, "leftY": 1000.0, "w": 1000.0, "h": 1000.0}
        self.sets = {"retail": _Maps({1: r, 2: same}), "era": _Maps({11: e, 12: dict(same)})}

    @staticmethod
    def source_set(zone, classic):
        return "era" if classic or "(Classic)" in zone else "retail"


def pin(wx, wy, inst=0, n=1):
    return ("QuestPOIBlob", n, inst, wx, wy, n)


class CoordinateReading(unittest.TestCase):
    def setUp(self):
        self.ev = Evidence(_Atlas())
        # row (50, 50): retail reading -> world (500, 500); Classic reading -> world (600, 500)
        self.ev.classify(("page", "A"), [("Testzone", 50.0, 50.0, False)], [pin(500, 500)])
        for p in ("B", "D", "E"):
            self.ev.classify(("page", p), [("Testzone", 50.0, 50.0, False)], [pin(605, 500)])
        self.ev.classify(("page", "C"), [("Testzone", 50.0, 50.0, False)], [pin(100, 100)])
        self.ev.classify(("page", "F"), [("Samezone", 50.0, 50.0, False)], [pin(500, 500, inst=1)])
        self.ev.classify(("page", "T"), [("Testzone (Classic)", 50.0, 50.0, False)], [pin(500, 500)])
        self.ev.classify(("quest", "Q", "end"), [("Testzone", 50.0, 50.0, False)], [pin(500, 500)])
        self.ev.finish()

    def test_verdicts(self):
        v = {k[1]: x["verdict"] for k, x in self.ev.rows.items() if k[0] == "page"}
        self.assertEqual(v, {"A": "retail", "B": "classic", "D": "classic", "E": "classic", "C": "conflict",
                             "F": "either"})
        self.assertEqual(self.ev.verdict(("page", "C"), "Testzone", 50.0, 50.0)["yards"], 566)

    def test_tagged_rows_are_not_guessed(self):
        self.assertNotIn(("page", "T", "Testzone (Classic)", 50.0, 50.0), self.ev.rows)

    def test_reading(self):
        self.assertEqual(self.ev.reading(("page", "A"), "Testzone", 50.0, 50.0), ("retail", "check"))
        self.assertEqual(self.ev.reading(("page", "B"), "Testzone", 50.0, 50.0), ("classic", "check"))
        self.assertEqual(self.ev.reading(("page", "F"), "Samezone", 50.0, 50.0), ("retail", "check"))
        # no evidence: the zone's default from its checked NPC-page rows (3 Classic against 1 retail)
        self.assertEqual(self.ev.reading(("page", "new"), "Testzone", 10.0, 10.0), ("classic", "zone-default"))
        self.assertEqual(self.ev.classic_zones("page"), ["testzone"])
        # quest-page rows are counted apart and have only retail evidence here
        self.assertEqual(self.ev.reading(("quest", "R", "end"), "Testzone", 10.0, 10.0), ("retail", "zone-default"))
        self.assertEqual(self.ev.reading(("page", "x"), "Nowhere", 1.0, 1.0), ("retail", "default"))

    def test_flight_master_title(self):
        self.assertTrue(is_flight_master("{{Npcbox\n | name = X\n | title = Gryphon Master\n}}"))
        self.assertTrue(is_flight_master("{{Npcbox\n|title=Wind Rider Master\n}}"))
        self.assertFalse(is_flight_master("{{Npcbox\n | title = Innkeeper\n}} a flight master nearby"))


class Values(unittest.TestCase):
    def test_faction(self):
        for raw, want in (("horde", "Horde"), ("ALLIANCE", "Alliance"), ("neutral", "Both"), ("", "Both"),
                          ("Night Fae", "Night Fae"), ("Scryers", "Scryers")):
            self.assertEqual(N.faction(raw), want, raw)
        self.assertIsNone(N.side("Both"))

    def test_class_and_race(self):
        self.assertEqual(N.canon("Death knight", N.CLASSES), "Death Knight")
        self.assertEqual(N.canon("demon hunter", N.CLASSES), "Demon Hunter")
        self.assertEqual(N.canon("troll", N.RACES), "Troll")
        self.assertEqual(N.canon("Mag'har orc", N.RACES), "Mag'har Orc")
        self.assertEqual(N.canon("Blood elf", N.RACES), "Blood Elf")

    def test_name_groups(self):
        rows = [{"name": "Ursangous's Paw", "page_title": "a"}, {"name": "Ursangous' Paw", "page_title": "b"},
                {"name": "Red Linen Goods", "page_title": "c"}, {"name": None, "page_title": "Fine Linen Goods (quest)"}]
        self.assertEqual([[r["page_title"] for r in g] for g in name_groups(rows)], [["a", "b"], ["c"], ["Fine Linen Goods (quest)"]])


class FactionPrerequisites(unittest.TestCase):
    def test_unmeetable(self):
        avail = {1: {"Alliance"}, 2: {"Horde"}, 3: {"Alliance", "Horde"}}
        both = {"faction": "Both", "prerequisites": {"required": [[1], [2]]}}
        self.assertEqual(validate.unmeetable(both, avail), [("Alliance", [2]), ("Horde", [1])])
        tagged = {"faction": "Both", "prerequisites": {"required": [[1, 2]], "faction": {"1": "Alliance", "2": "Horde"}}}
        self.assertEqual(validate.unmeetable(tagged, avail), [])
        alliance = {"faction": "Alliance", "prerequisites": {"required": [[2]]}}
        self.assertEqual(validate.unmeetable(alliance, avail), [("Alliance", [2])])
        self.assertEqual(validate.unmeetable({"faction": "Horde", "prerequisites": {"required": [[3]]}}, avail), [])

    def test_validation_reports_it(self):
        qs = [fixture.quest(10, faction="Alliance"), fixture.quest(11, prereq=[[10]], faction="Horde")]
        with tempfile.TemporaryDirectory() as t:
            from test_pipeline import run_validate
            rep, _cov = run_validate(fixture.write(t, quests=qs))
            self.assertIn("no Horde player can complete", "\n".join(rep.errors))


class BuildChecksRecords(unittest.TestCase):
    def test_bad_correction_stops_strict_build(self):
        with tempfile.TemporaryDirectory() as t:
            d = fixture.write(Path(t) / "data")
            corr = fixture.write_corrections(Path(t) / "corrections", [
                {"id": "b1", "flavor": "era", "kind": "quest", "key": 10, "op": "set", "path": "/level", "value": "ten",
                 "reason": "x", "evidence": "x"},
                {"id": "b2", "flavor": "era", "kind": "quest", "key": 11, "op": "set", "path": "/start/0/coords",
                 "value": [{"map": 1429, "x": 150, "y": 2}], "reason": "x", "evidence": "x"}])
            with self.assertRaises(ValueError):
                build_sqlite(Path(t) / "a.sqlite", d, corr, flavors=("era",))
            _counts, log = build_sqlite(Path(t) / "b.sqlite", d, corr, flavors=("era",), strict=False)
            errs = [x for x in log if x[4] == "error"]
            self.assertEqual(len(errs), 2, log)
            self.assertIn("x=150", " ".join(x[5] for x in errs))


SKIP = os.environ.get("CG_SKIP_DATA") == "1" or not (C.DATA / "meta.json").exists()


def record(fl, kind, key):
    for _p, r in C.iter_records(fl, kind):
        if C.record_key(kind, r) == key:
            return r
    return None


@unittest.skipIf(SKIP, "CG_SKIP_DATA=1 or no data/")
class ShippedCases(unittest.TestCase):
    """the concrete cases from the first review, checked on the shipped data"""

    def test_classic_numbers_kept_when_the_pin_says_so(self):
        for fl in ("era", "tbc", "forever"):
            r = record(fl, "npcs", "Ragnar Thunderbrew")
            p = next(c for c in r["coords"] if c["map"] == 1426)
            self.assertEqual((p["x"], p["y"], p["read_as"], p["read_by"], p["confidence"]),
                             (46.8, 52.5, "classic", "check", "high"), fl)
            d = record(fl, "npcs", "Donova Snowden")["coords"][0]
            self.assertEqual((d["x"], d["y"], d["read_as"]), (31.0, 45.0, "classic"), fl)

    def test_retail_numbers_converted_when_the_pin_says_so(self):
        p = record("era", "npcs", "Skuerto")["coords"][0]
        self.assertEqual((p["map"], p["read_as"], p["read_by"]), (1417, "retail", "check"))
        self.assertLess(abs(p["x"] - 46.2) + abs(p["y"] - 47.8), 1.0)

    def test_unchecked_points_are_low(self):
        p = record("era", "npcs", "Helendis Riverhorn")["coords"][0]
        self.assertEqual(p["confidence"], "low")
        self.assertIs(p["exact_version"], False)

    def test_retail_classic_numbers_converted(self):
        p = next(c for c in record("retail", "npcs", "Ragnar Thunderbrew")["coords"] if c["map"] == 27)
        self.assertEqual((p["read_as"], p["exact_version"], p["confidence"]), ("classic", False, "high"))
        self.assertLessEqual(p["check"]["yards"], 50)

    def test_retail_stale_end_point_replaced_by_pin(self):
        e = record("retail", "quests", 81689)["end"][0]
        cs = e["coord_source"]
        self.assertEqual((cs["type"], cs["via"]), ("db2", "turn-in-pin"))
        self.assertGreater(cs["replaces"]["yards"], 50)
        self.assertEqual((e["coords"][0]["x"], e["coords"][0]["y"]), (43.0, 34.1))

    def test_ambiguous_ids_left_out(self):
        for fl in C.FLAVORS:
            self.assertIsNone(record(fl, "quests", 788), fl)
            q2 = C.load_json(C.DATA / fl / "questv2.json")
            reasons = {e["id"]: e["reason"] for e in q2["excluded"]}
            self.assertTrue(reasons[788].startswith("ambiguous id"), fl)

    def test_faction_twin_variant(self):
        q = record("era", "quests", 8978)
        sides = {q["faction"]} | {v["faction"] for v in q.get("variants", [])}
        self.assertEqual(sides, {"Alliance", "Horde"})
        self.assertEqual({q["name"]} | {v["name"] for v in q["variants"]}, {"Return to Mokvar", "Return to Deliana"})
        self.assertEqual(record("era", "quests", 8926)["prerequisites"]["required"], [[8978]])

    def test_faction_alternatives_merged(self):
        p = record("era", "quests", 1386)["prerequisites"]
        self.assertEqual([sorted(g) for g in p["required"]], [[1367, 1385]])
        self.assertEqual(p["faction"], {"1367": "Horde", "1385": "Alliance"})

    def test_values_normalised(self):
        seen = set()
        for fl in C.FLAVORS:
            for _p, r in C.iter_records(fl, "quests"):
                seen.add(r["faction"])
                for c in r["classes"]:
                    self.assertIn(c, N.CLASSES)
                for c in r["races"]:
                    self.assertIn(c, N.RACES)
        self.assertLessEqual(seen, set(N.FACTIONS))

    def test_retail_maps_match_the_db2_build(self):
        m = C.load_json(C.DATA / "retail" / "maps.json")
        meta = C.load_json(C.DATA / "meta.json")
        self.assertEqual(m["source"]["build"], meta["sources"]["db2"]["retail"]["build"].split()[-1])
        row = next(r for r in m["maps"] if r[0] == 2613)
        self.assertEqual(row[3:7], [6400.0, -10137.8, 502.5, 335.0])


if __name__ == "__main__":
    unittest.main()
