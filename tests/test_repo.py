# wow-completionist-data :: tests/test_repo.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
"""Checks on the repository itself: the shipped data validates, the privacy gate passes and works.
Set CG_SKIP_DATA=1 to skip the full-data validation (it reads every data file, about ten seconds)."""
import hashlib
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import privacy_check  # noqa: E402
import validate  # noqa: E402
from cgdata import common as C  # noqa: E402
from cgdata.sqlite_build import corrected_records  # noqa: E402


class ShippedData(unittest.TestCase):
    @unittest.skipIf(os.environ.get("CG_SKIP_DATA") == "1", "CG_SKIP_DATA=1")
    def test_all_flavors_validate(self):
        if not (C.DATA / "meta.json").exists():
            self.skipTest("no data/ yet")
        rep = validate.Report()
        corrections = C.load_corrections()
        validate.validate_corrections(corrections, rep)
        cov = {fl: Counter() for fl in C.FLAVORS}
        for fl in C.FLAVORS:
            validate.validate_flavor(fl, rep, cov, corrections, C.DATA)
            self.assertGreater(cov[fl]["quests"], 1000, fl)
            self.assertEqual(cov[fl]["questv2_ids"],
                             cov[fl]["quests"] + cov[fl]["questv2_excluded_by_wiki_rules"]
                             + cov[fl]["questv2_ids_without_wiki_page"], fl)
        self.assertEqual(rep.n_errors(), 0, rep.errors)

    def test_correction_template_applies(self):
        """corrections/_example.json (never applied by the build) must stay a working template"""
        if not (C.DATA / "meta.json").exists():
            self.skipTest("no data/ yet")
        doc = C.load_json(C.CORRECTIONS / "_example.json")
        corr = [("_example.json", i, c) for i, c in enumerate(doc["corrections"])]
        for _f, _i, c in corr:
            self.assertEqual(C.correction_problems(c), [], c["id"])
        log = []
        for kind in ("quests", "npcs"):
            for _r in corrected_records("era", kind, corr, C.DATA, log, strict=True):
                pass
        self.assertEqual(sorted(x[0] for x in log if x[4] == "applied"),
                         sorted(c["id"] for _f, _i, c in corr))

    def test_meta_names_sources(self):
        if not (C.DATA / "meta.json").exists():
            self.skipTest("no data/ yet")
        meta = C.load_json(C.DATA / "meta.json")
        self.assertEqual(meta["sources"]["wiki"]["licence"], "CC BY-SA 4.0")
        for fl in C.FLAVORS:
            self.assertTrue(meta["sources"]["db2"][fl]["build"], fl)


class Privacy(unittest.TestCase):
    def test_repository_is_clean(self):
        hits = privacy_check.scan(privacy_check.files())
        self.assertEqual(hits, [])

    def test_gate_catches_problems(self):
        with tempfile.TemporaryDirectory(dir=privacy_check.REPO) as t:
            p = Path(t) / "probe.txt"
            home = "/" + "Us" + "ers" + "/someone/x"
            mail = "a.person" + "@" + "example.com"
            p.write_text(f"mail {mail} or help@batesai.org; path {home}; key ghp_{'a' * 30}; testword\n")
            old = set(privacy_check.DENY_HASHES)
            privacy_check.DENY_HASHES.add(hashlib.sha256(b"testword").hexdigest())
            try:
                hits = privacy_check.scan([p])
            finally:
                privacy_check.DENY_HASHES.clear()
                privacy_check.DENY_HASHES.update(old)
            text = "\n".join(hits)
            self.assertIn(mail, text)
            self.assertNotIn("help@batesai.org", text)
            self.assertIn("home-directory path", text)
            self.assertIn("credential-shaped", text)
            self.assertIn("deny list", text)


if __name__ == "__main__":
    unittest.main()
