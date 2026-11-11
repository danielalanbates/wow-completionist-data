#!/usr/bin/env python3
# wow-completionist-data :: tools/build_db.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Build the Completionist's Guide quest database.

    python3 tools/build_db.py build [--json] [--lenient]     data/ + corrections/ -> build/completionist.sqlite
    python3 tools/build_db.py export [--addon PATH] [flavor ...]
                                                             the addon's wiki/DB2 caches -> data/ (maintainers)
    python3 tools/build_db.py all [--addon PATH]             export, then build

`build` needs only this repository.  It streams data/<flavor>/<kind>/*.json one bucket at a time, applies every
corrections/*.json entry last (file-name order, then file order) and writes build/completionist.sqlite
(gitignored).  --json also writes build/json/<flavor>/<kind>.json (one corrected record per line).  A correction
that does not apply stops the build; --lenient logs it in the corrections_applied table instead.

`export` regenerates data/ from the addon repository's pipeline outputs (see docs/HANDOFF.md).  The addon path is
--addon, else $CG_ADDON_REPO, else ../wow-completionist-guide, else ../repo.  Both stages are deterministic: the
same inputs give byte-identical data/ files (no timestamps; every list is sorted).
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cgdata import common as C  # noqa: E402


def find_addon(arg):
    cands = [arg] if arg else []
    if os.environ.get("CG_ADDON_REPO"):
        cands.append(os.environ["CG_ADDON_REPO"])
    cands += [str(C.REPO.parent / "wow-completionist-guide"), str(C.REPO.parent / "repo")]
    for c in cands:
        p = Path(c).expanduser()
        if (p / "tools" / "wiki" / "gen_wiki_guides.py").exists():
            return p.resolve()
    sys.exit("addon repository not found: pass --addon PATH (a checkout of wow-completionist-guide with its "
             "tools/wiki pipeline outputs)")


def do_export(args):
    from cgdata.export import Addon, Exporter
    t0 = time.time()
    addon = Addon(find_addon(args.addon))
    flavors = [f for f in args.flavors if f in C.FLAVORS] or list(C.FLAVORS)
    bad = [f for f in args.flavors if f not in C.FLAVORS]
    if bad:
        sys.exit(f"unknown flavor(s) {bad}; choose from {list(C.FLAVORS)}")
    ex = Exporter(addon)
    print(f"loaded addon tables in {time.time() - t0:.0f}s")
    ex.run(flavors)
    print(f"export done in {time.time() - t0:.0f}s -> {C.DATA.relative_to(C.REPO)}/")


def do_build(args):
    from cgdata.sqlite_build import build_sqlite
    t0 = time.time()
    out = C.BUILD / "completionist.sqlite"
    counts, log = build_sqlite(out, json_dir=(C.BUILD / "json") if args.json else None, strict=not args.lenient)
    applied = sum(1 for x in log if x[4] == "applied")
    errors = [x for x in log if x[4] == "error"]
    print(f"built {out.relative_to(C.REPO)} in {time.time() - t0:.0f}s: "
          + "; ".join(f"{fl} " + ", ".join(f"{k} {v}" for k, v in c.items()) for fl, c in counts.items()))
    print(f"corrections: {applied} applied, {sum(1 for x in log if x[4] == 'skipped')} skipped, {len(errors)} errors")
    for e in errors:
        print("  correction error:", e)
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--addon")
    e.add_argument("flavors", nargs="*")
    b = sub.add_parser("build")
    b.add_argument("--json", action="store_true")
    b.add_argument("--lenient", action="store_true")
    a = sub.add_parser("all")
    a.add_argument("--addon")
    a.add_argument("--json", action="store_true")
    a.add_argument("--lenient", action="store_true")
    a.add_argument("flavors", nargs="*")
    args = ap.parse_args()
    if args.cmd in ("export", "all"):
        do_export(args)
    if args.cmd in ("build", "all"):
        return do_build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
