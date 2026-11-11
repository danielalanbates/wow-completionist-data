#!/usr/bin/env python3
# wow-completionist-data :: tools/fetch_db2.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Download the few Blizzard DB2 tables the export needs beyond the addon's caches, pinned to the same build as the
addon's tools/db2/<flavor>/BUILD, into cache/db2/<flavor>/ (gitignored).

    python3 tools/fetch_db2.py [--addon PATH] [--force] [flavor ...]

Tables: UiMap + UiMapAssignment (map geometry of the same build as the client's quest tables, so map ids and
rectangles match the DB2 points) and TaxiNodes (flight points: Blizzard positions used to check wiki coordinates).
Source: the public CSV exports at https://wago.tools/db2/<Table>/csv?build=<build> (column names from WoWDBDefs).
One request at a time, at least 1.5 s apart; a file that already exists for the same build is not fetched again.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cgdata import common as C  # noqa: E402
from build_db import find_addon  # noqa: E402

TABLES = ("UiMap", "UiMapAssignment", "TaxiNodes")
UA = "wow-completionist-data-tools/1.0"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--addon")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("flavors", nargs="*")
    args = ap.parse_args()
    addon = find_addon(args.addon)
    flavors = args.flavors or list(C.FLAVORS)
    last = 0.0
    for fl in flavors:
        if fl not in C.FLAVORS:
            sys.exit(f"unknown flavor {fl!r}")
        build_file = addon / "tools" / "db2" / fl / "BUILD"
        if not build_file.exists():
            sys.exit(f"{fl}: the addon has no tools/db2/{fl}/BUILD (run its tools/wiki/fetch_db2.py first)")
        full = build_file.read_text(encoding="utf-8").strip()
        build = full.split()[-1]
        out = C.CACHE_DB2 / fl
        out.mkdir(parents=True, exist_ok=True)
        old = (out / "BUILD").read_text(encoding="utf-8").strip() if (out / "BUILD").exists() else None
        for t in TABLES:
            p = out / f"{t}.csv"
            if p.exists() and p.stat().st_size > 0 and old == full and not args.force:
                print(f"{fl} {t}: cached")
                continue
            wait = 1.5 - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            url = f"https://wago.tools/db2/{t}/csv?build={build}"
            print("GET", url)
            r = subprocess.run(["curl", "-sS", "-L", "-f", "-m", "120", "-A", UA, "-o", str(p) + ".part", url])
            last = time.time()
            if r.returncode != 0:
                Path(str(p) + ".part").unlink(missing_ok=True)
                sys.exit(f"{fl} {t}: download failed (curl exit {r.returncode})")
            Path(str(p) + ".part").replace(p)
        (out / "BUILD").write_text(full + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
