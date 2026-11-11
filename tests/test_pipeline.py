# wow-completionist-data :: tests/test_pipeline.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
"""Bucket files, JSON Pointer, the corrections overlay, validation and the SQLite build on a synthetic fixture."""
import json
import sqlite3
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture  # noqa: E402
import validate  # noqa: E402
from cgdata import common as C  # noqa: E402
from cgdata.sqlite_build import build_sqlite, corrected_records  # noqa: E402


def run_validate(data_dir, corr_dir=None):
    rep = validate.Report()
    corrections = C.load_corrections(corr_dir) if corr_dir else []
    validate.validate_corrections(corrections, rep)
    cov = {"era": Counter()}
    validate.validate_flavor("era", rep, cov, corrections, data_dir)
    return rep, cov["era"]


class Buckets(unittest.TestCase):
    def test_bucket_names(self):
        self.assertEqual(C.bucket_of("quests", {"id": 783}), "000000-000999")
        self.assertEqual(C.bucket_of("quests", {"id": 91234}), "091000-091999")
        self.assertEqual(C.bucket_of("npcs", {"key": "x", "ids": [197, 5]}), "0000000-0009999")
        self.assertEqual(C.bucket_of("npcs", {"key": "x", "ids": []}), "no-id")

    def test_write_is_deterministic_and_line_per_record(self):
        with tempfile.TemporaryDirectory() as t:
            d = fixture.write(t)
            first = {p.name: p.read_text() for p in sorted((d / "era" / "quests").glob("*.json"))}
            fixture.write(t)
            again = {p.name: p.read_text() for p in sorted((d / "era" / "quests").glob("*.json"))}
            self.assertEqual(first, again)
            self.assertEqual(sorted(first), ["000000-000999.json", "002000-002999.json"])
            doc = json.loads(first["000000-000999.json"])
            self.assertEqual([r["id"] for r in doc["records"]], [10, 11])
            self.assertEqual(len(first["000000-000999.json"].splitlines()), 6 + 2 + 2)
            # a bucket that is no longer needed is removed
            C.write_kind("era", "quests", [fixture.quest(10)], d)
            self.assertEqual(sorted(p.name for p in (d / "era" / "quests").glob("*.json")), ["000000-000999.json"])


class Pointer(unittest.TestCase):
    def test_ops(self):
        doc = {"a": [{"b": 1}, {"b": 2}], "c": {"d": "x"}}
        self.assertEqual(C.pointer_get(doc, "/a/1/b"), 2)
        C.pointer_apply(doc, "set", "/a/0/b", 5)
        C.pointer_apply(doc, "add", "/a/-", {"b": 3})
        C.pointer_apply(doc, "add", "/a/0", {"b": 0})
        C.pointer_apply(doc, "remove", "/c/d")
        C.pointer_apply(doc, "set", "/c/e~1f", True)
        self.assertEqual(doc, {"a": [{"b": 0}, {"b": 5}, {"b": 2}, {"b": 3}], "c": {"e/f": True}})
        with self.assertRaises(KeyError):
            C.pointer_apply(doc, "set", "/a/9/b", 1)
        with self.assertRaises(ValueError):
            C.pointer_parts("a/b")


class Corrections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = fixture.write(Path(self.tmp.name) / "data")
        self.corr = Path(self.tmp.name) / "corrections"

    def tearDown(self):
        self.tmp.cleanup()

    def records(self, corrections, strict=True):
        log = []
        recs = {r["id"]: r for r in corrected_records("era", "quests", corrections, self.data, log, strict)}
        return recs, log

    def test_set_coordinate_marks_source(self):
        fixture.write_corrections(self.corr, [{
            "id": "era-11-end", "flavor": "era", "kind": "quest", "key": 11, "op": "set", "path": "/end/0/coords",
            "value": [{"map": 1429, "x": 42.1, "y": 65.9}], "reason": "wiki has no point", "evidence": "in game"}])
        recs, log = self.records(C.load_corrections(self.corr))
        e = recs[11]["end"][0]
        self.assertEqual(e["coords"], [{"map": 1429, "x": 42.1, "y": 65.9}])
        self.assertEqual(e["coord_source"], {"type": "correction", "correction": "era-11-end"})
        self.assertIs(e["exact_version"], True)
        self.assertEqual(recs[11]["corrections"], ["era-11-end"])
        self.assertNotIn("corrections", recs[10])
        self.assertEqual([x[4] for x in log], ["applied"])
        rep, cov = run_validate(self.data, self.corr)
        self.assertEqual(rep.n_errors(), 0, rep.errors)
        self.assertEqual(cov["quests_end_located"], 1)
        self.assertEqual(cov["corrections_applied"], 1)

    def test_prerequisite_and_whole_record(self):
        new = fixture.quest(12)
        fixture.write_corrections(self.corr, [
            {"id": "p1", "flavor": "all", "kind": "quest", "key": 11, "op": "add", "path": "/prerequisites/breadcrumb/-",
             "value": 10, "reason": "breadcrumb", "evidence": "x"},
            {"id": "p2", "flavor": "era", "kind": "quest", "key": 12, "op": "add", "path": "", "value": new,
             "reason": "missing quest", "evidence": "x"},
            {"id": "p3", "flavor": "era", "kind": "quest", "key": "2500", "op": "remove", "path": "",
             "reason": "not in game", "evidence": "x"}])
        recs, _log = self.records(C.load_corrections(self.corr))
        self.assertEqual(recs[11]["prerequisites"]["breadcrumb"], [10])
        self.assertEqual(sorted(recs), [10, 11, 12])
        self.assertEqual(recs[12]["corrections"], ["p2"])

    def test_bad_corrections_are_errors(self):
        fixture.write_corrections(self.corr, [
            {"id": "bad1", "flavor": "era", "kind": "quest", "key": 999, "op": "set", "path": "/name", "value": "x",
             "reason": "no such quest", "evidence": "x"},
            {"id": "bad2", "flavor": "era", "kind": "quest", "key": 10, "op": "set", "path": "/start/5/coords",
             "value": [], "reason": "bad path", "evidence": "x"},
            {"id": "bad3", "flavor": "era", "kind": "quest", "key": 10, "op": "set", "path": "/start/0/coords",
             "value": [{"map": 1, "x": 140, "y": 2}], "reason": "bad map and x", "evidence": "x"},
            {"id": "bad3", "flavor": "mars", "kind": "spell", "key": 10, "op": "move", "reason": ""}])
        with self.assertRaises(ValueError):
            self.records(C.load_corrections(self.corr))
        rep, _cov = run_validate(self.data, self.corr)
        kinds = {k for (lvl, k) in rep.count if lvl == "error"}
        self.assertTrue({"correction", "coords"} <= kinds, rep.errors)
        text = "\n".join(rep.errors)
        self.assertIn("bad1", text)
        self.assertIn("bad2", text)
        self.assertIn("map 1 is not in maps.json", text)
        self.assertIn("duplicate id 'bad3'", text)

    def test_underscore_files_are_ignored(self):
        fixture.write_corrections(self.corr, [{"id": "ex"}], name="_example.json")
        self.assertEqual(C.load_corrections(self.corr), [])


class Validation(unittest.TestCase):
    def test_clean_fixture(self):
        with tempfile.TemporaryDirectory() as t:
            rep, cov = run_validate(fixture.write(t))
            self.assertEqual(rep.n_errors(), 0, rep.errors)
            self.assertEqual(cov["quests"], 3)
            self.assertEqual(cov["quests_start_located"], 3)
            self.assertEqual(cov["questv2_ids_without_wiki_page"], 1)
            self.assertEqual(cov["npcs_located"], 1)

    def test_detects_broken_data(self):
        bad = [fixture.quest(10), fixture.quest(11, prereq=[[77]]), fixture.quest(3000)]
        bad[0]["start"][0]["coords"][0]["x"] = 101.0
        bad[0]["start"][0]["coords"][0]["map"] = 5
        bad[2]["start"][0]["coord_source"] = None
        dup = fixture.quest(11)
        with tempfile.TemporaryDirectory() as t:
            d = fixture.write(t, quests=bad, excluded=(11,))
            # a record in the wrong bucket and a duplicate id, written by hand
            p = d / "era" / "quests" / "000000-000999.json"
            doc = json.loads(p.read_text())
            doc["records"].append(dup)
            doc["records"].append(fixture.quest(1500))
            doc["count"] = len(doc["records"])
            p.write_text(json.dumps(doc))
            rep, _cov = run_validate(d)
            text = "\n".join(rep.errors)
            for needle in ("x=101.0", "map 5 is not in maps.json", "required quest 77", "duplicate quest id",
                           "not in the client's QuestV2", "also listed as excluded", "coordinates without coord_source",
                           "belongs in 001000-001999"):
                self.assertIn(needle, text)

    def test_schema_rejects_unknown_and_missing_members(self):
        q = fixture.quest(10)
        q["surprise"] = 1
        del q["name"]
        q["prerequisites"]["basis"] = "guess"
        with tempfile.TemporaryDirectory() as t:
            rep, _cov = run_validate(fixture.write(t, quests=[q]))
            text = "\n".join(rep.errors)
            self.assertIn("surprise: unknown member", text)
            self.assertIn("name: missing", text)


class SqliteBuild(unittest.TestCase):
    def dump(self, path):
        con = sqlite3.connect(path)
        out = {}
        for (t,) in con.execute("select name from sqlite_master where type='table' order by name"):
            out[t] = sorted(map(repr, con.execute(f"select * from {t}")))
        con.close()
        return out

    def test_build_and_determinism(self):
        with tempfile.TemporaryDirectory() as t:
            d = fixture.write(Path(t) / "data")
            corr = fixture.write_corrections(Path(t) / "corrections", [{
                "id": "c1", "flavor": "era", "kind": "npc", "key": "Test mob", "op": "set", "path": "/coords",
                "value": [{"map": 1429, "x": 30.0, "y": 70.0, "exact_version": True, "via": "correction"}],
                "reason": "mob camp", "evidence": "x"}])
            a, b = Path(t) / "a.sqlite", Path(t) / "b.sqlite"
            counts, log = build_sqlite(a, d, corr, json_dir=Path(t) / "json", flavors=("era",))
            build_sqlite(b, d, corr, flavors=("era",))
            self.assertEqual(counts["era"]["quests"], 3)
            self.assertEqual(self.dump(a), self.dump(b))
            con = sqlite3.connect(a)
            self.assertEqual(con.execute("select prereq_id, grp from quest_prereqs where quest_id=2500 order by 1").fetchall(),
                             [(10, 0), (11, 0)])
            self.assertEqual(con.execute("select status from questv2 where id=12").fetchone(), ("no_wiki_page",))
            self.assertEqual(con.execute("select x, y from npc_points where key='Test mob'").fetchall(), [(30.0, 70.0)])
            self.assertEqual(con.execute("select correction, status from corrections_applied").fetchall(),
                             [("c1", "applied")])
            merged = json.loads((Path(t) / "json" / "era" / "quests.json").read_text())
            self.assertEqual([q["id"] for q in merged], [10, 11, 2500])


if __name__ == "__main__":
    unittest.main()
