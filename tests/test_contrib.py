# wow-completionist-data :: tests/test_contrib.py
# Copyright (c) 2026 Daniel Bates. All rights reserved. PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
"""Player contributions: validation, the per-contributor cap, replacement, clustering, confidence, no names stored."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import contrib  # noqa: E402

A = """era|1.15.8|A:179|1429,48.6,42.0,3;1429,48.8,42.0,3;1429,48.8,42.2,6;1429,20.0,80.0,1
era|1.15.8|C:200:1|1429,30.0,30.0,4;1429,30.2,30.2,4;1429,60.0,55.0,2;1429,60.2,55.0,4
not a line
era|1.15.8|A:999999999|1429,10,10,1
era|1.15.8|A:5|99999999,10,10,1;1429,150,10,1
era|1.15.8|A:6|1429,10,10,1; rm -rf /
"""
B = "era|1.15.9|A:179|1429,48.8,42.0,3;1429,49.0,42.2,2\nera|1.15.9|C:200:1|1429,30.2,30.0,2\n"


class Contrib(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        contrib.BASE = os.path.join(self.tmp.name, "contributions")
        contrib.RAW = os.path.join(contrib.BASE, "raw")
        self.out = []

    def tearDown(self):
        self.tmp.cleanup()

    def areas(self, flavor="era"):
        return json.load(open(os.path.join(contrib.BASE, "areas", flavor + ".json")))["areas"]

    def test_parse_rejects_bad_lines_and_caps_weight(self):
        rows, problems = contrib.parse(A)
        self.assertEqual(sorted(k for _, k in rows), ["A:179", "A:6", "C:200:1"])
        self.assertTrue(all(w <= contrib.CAP for cells in rows.values() for w in cells.values()))
        self.assertEqual(len(rows[("era", "A:6")]), 1)          # the junk after the first cell is dropped
        self.assertGreaterEqual(len(problems), 3)

    def test_merge_cluster_and_confidence(self):
        contrib.add(A, "Alice", out=self.out.append)
        contrib.rebuild(out=self.out.append)
        a = self.areas()
        self.assertEqual(len(a["A:179"]), 1)                    # the stray cell at 20,80 is noise
        self.assertEqual(a["A:179"][0]["confidence"], "single")
        self.assertEqual(len(a["C:200:1"]), 2)                  # two camps
        contrib.add(B, "bob", out=self.out.append)
        contrib.rebuild(out=self.out.append)
        a = self.areas()
        self.assertEqual(a["A:179"][0]["confidence"], "confirmed")
        self.assertEqual(a["A:179"][0]["contributors"], 2)
        self.assertAlmostEqual(a["A:179"][0]["x"], 48.8, delta=0.2)

    def test_resubmission_replaces_and_trusted(self):
        contrib.add(A, "alice", out=self.out.append)
        contrib.add(B, "ALICE ", out=self.out.append)           # same person: the newest wins
        contrib.rebuild(out=self.out.append)
        self.assertEqual(len(os.listdir(contrib.RAW)), 1)
        self.assertNotIn("C:200:1", [k for k in self.areas() if len(self.areas()[k]) > 1])
        contrib.add(B, "maintainer", trusted=True, out=self.out.append)
        contrib.rebuild(out=self.out.append)
        self.assertEqual(self.areas()["A:179"][0]["confidence"], "trusted")

    def test_no_names_and_sql(self):
        contrib.add(A, "Someone Recognisable", out=self.out.append)
        contrib.rebuild(out=self.out.append)
        for root, _, files in os.walk(contrib.BASE):
            for f in files:
                if not f.endswith(".sqlite"):
                    self.assertNotIn("recognisable", open(os.path.join(root, f), encoding="utf-8").read().lower())
                self.assertNotIn("recognisable", f.lower())
        db = sqlite3.connect(os.path.join(contrib.BASE, "contributions.sqlite"))
        self.assertEqual(db.execute("select count(*) from areas where flavor='era' and key='A:179'").fetchone()[0], 1)
        self.assertEqual(db.execute("select count(*) from contributors").fetchone()[0], 1)
        self.assertGreater(db.execute("select count(*) from spots").fetchone()[0], 5)

    def test_empty_or_oversized(self):
        self.assertEqual(contrib.add("hello\n### Export text\n", "x", out=self.out.append), 0)
        rows, problems = contrib.parse("era||A:1|1,1,1,1\n" * (contrib.MAX_LINES + 1))
        self.assertEqual(rows, {})
        self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
