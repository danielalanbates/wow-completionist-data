#!/usr/bin/env python3
# wow-completionist-data :: tools/contrib.py
# Copyright (c) 2026 Daniel Bates. All rights reserved. PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
# https://batesai.org - help@batesai.org
"""Player contributions: where players stood when they did a step.

The Completionist's Guide addon has a "Contribute" box. While it is ticked the addon notes the player's map position
on quest accept, turn-in, objective progress and the forward arrow, and "/cr contribute export" (or a click on the
word Contribute) gives a text: one line per step,

    <flavor>|<client build>|<key>|<map>,<x>,<y>,<weight>;<map>,<x>,<y>,<weight>;...

    key   A:<quest id>  accept      T:<quest id>  turn-in      C:<quest id>:<objective>  objective
          G:<guide id>#<step key>   a step with no quest
    x, y  position on the map, 0..100, on a 0.2 grid

This tool checks such a text, stores it (one file per contributor, the newest replaces the older), and rebuilds:

    contributions/spots/<flavor>.csv    every cell: key, map, x, y, weight, contributors
    contributions/areas/<flavor>.json   the most likely places per key (centre, radius, weight, contributors, confidence)
    contributions/contributions.sqlite  the same two tables for SQL (tables spots, areas, contributors)

Commands (run from the repository root):
    python3 tools/contrib.py add FILE --who NAME [--trusted] [--source TEXT]
    python3 tools/contrib.py add-saved FILE.lua --who NAME [--trusted]     (a SavedVariables file; needs luajit)
    python3 tools/contrib.py rebuild
    python3 tools/contrib.py check FILE                                    (validate only; prints the report)

NAME is only hashed (the files and tables hold the first 12 hex digits of its SHA-256, never the name).
One contributor counts at most 3 per cell, however often they stood there, so nobody outweighs the crowd.
confidence: "trusted" (a maintainer's own play), "confirmed" (two or more contributors agree), "single".
Stdlib only.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "contributions")
RAW = os.path.join(BASE, "raw")
FLAVORS = ("era", "tbc", "mop", "retail", "forever")
KEY_RE = re.compile(r"^(?:[AT]:\d{1,7}|C:\d{1,7}:\d{1,2}|G:[A-Za-z0-9 _:.\-/'()&,+!?]{1,140}#[A-Za-z0-9:_\-]{1,60})$")
BUILD_RE = re.compile(r"^[0-9A-Za-z.\- ]{0,24}$")
MAX_BYTES = 2_000_000
MAX_LINES = 20_000
MAX_CELLS = 80            # per key and contributor, as in the addon
CAP = 3                   # one contributor's weight per cell
CELL = 0.2
RADIUS = 1.5              # map %, as CompletionRoute/Core/Contribute.lua
MIN_R = 0.3


def who_hash(name):
    return hashlib.sha256(("wow-completionist-data:" + name.strip().lower()).encode()).hexdigest()[:12]


def parse(text):
    """-> (rows, problems).  rows: {(flavor, key): {(map, xq, yq): weight}} with the per-cell cap applied."""
    problems, rows = [], {}
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        return {}, [f"too large (over {MAX_BYTES} bytes)"]
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n")]
    # the issue form adds headings, code fences, its licence tick box and "_No response_": not export lines
    lines = [ln for ln in lines if ln and not ln.startswith(("#", "```", "- [", "_No response_"))]
    if len(lines) > MAX_LINES:
        return {}, [f"too many lines (over {MAX_LINES})"]
    for n, ln in enumerate(lines, 1):
        parts = ln.split("|")
        if len(parts) != 4:
            problems.append(f"line {n}: expected flavor|build|key|cells")
            continue
        flavor, build, key, cells = parts
        if flavor not in FLAVORS:
            problems.append(f"line {n}: unknown flavor")
            continue
        if not BUILD_RE.match(build) or not KEY_RE.match(key):
            problems.append(f"line {n}: bad build or key")
            continue
        out = rows.setdefault((flavor, key), {})
        bad = 0
        for cell in cells.split(";"):
            f = cell.split(",")
            try:
                m, x, y, w = int(f[0]), float(f[1]), float(f[2]), int(f[3])
            except (ValueError, IndexError):
                bad += 1
                continue
            if not (1 <= m <= 99999 and 0 < x < 100 and 0 < y < 100 and 1 <= w <= 100000) or len(f) != 4:
                bad += 1
                continue
            k = (m, round(x / CELL), round(y / CELL))
            out[k] = min(CAP, out.get(k, 0) + w)
        if bad:
            problems.append(f"line {n}: {bad} bad cell(s) dropped")
        if len(out) > MAX_CELLS:
            keep = sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_CELLS]
            rows[(flavor, key)] = dict(keep)
            problems.append(f"line {n}: more than {MAX_CELLS} cells, the lightest dropped")
        if not out:
            del rows[(flavor, key)]
    return rows, problems


def normal_text(rows):
    out = []
    for (flavor, key) in sorted(rows):
        cells = ";".join(f"{m},{xq * CELL:.1f},{yq * CELL:.1f},{w}" for (m, xq, yq), w in sorted(rows[(flavor, key)].items()))
        out.append(f"{flavor}||{key}|{cells}")
    return "\n".join(out) + ("\n" if out else "")


def cluster(cells):
    """cells: {(map, xq, yq): (weight, contributors)} -> areas, heaviest first (the addon's rule, Contribute.Areas)."""
    pts = sorted(({"m": m, "x": xq * CELL, "y": yq * CELL, "w": w, "c": c} for (m, xq, yq), (w, c) in cells.items()),
                 key=lambda p: (p["m"], p["x"], p["y"]))
    total = sum(p["w"] for p in pts)
    out, r2 = [], RADIUS * RADIUS
    while pts and len(out) < 4:
        best, bw = None, None
        for i, p in enumerate(pts):
            w = sum(o["w"] for o in pts if o["m"] == p["m"] and (o["x"] - p["x"]) ** 2 + (o["y"] - p["y"]) ** 2 <= r2)
            if bw is None or w > bw:
                best, bw = i, w
        if out and (bw < 2 or bw < total * 0.15):
            break
        seed = pts[best]
        cx, cy = seed["x"], seed["y"]
        for _ in range(2):
            near = [o for o in pts if o["m"] == seed["m"] and (o["x"] - cx) ** 2 + (o["y"] - cy) ** 2 <= r2]
            sw = sum(o["w"] for o in near)
            if sw > 0:
                cx, cy = sum(o["x"] * o["w"] for o in near) / sw, sum(o["y"] * o["w"] for o in near) / sw
        mine = [o for o in pts if o["m"] == seed["m"] and (o["x"] - cx) ** 2 + (o["y"] - cy) ** 2 <= r2]
        if not mine:
            break
        far = max((o["x"] - cx) ** 2 + (o["y"] - cy) ** 2 for o in mine)
        people = set()
        for o in mine:
            people |= o["c"]
        out.append({"map": seed["m"], "x": round(cx, 2), "y": round(cy, 2), "r": round(max(MIN_R, math.sqrt(far)), 2),
                    "weight": sum(o["w"] for o in mine), "cells": len(mine), "people": people})
        pts = [o for o in pts if o not in mine]
    return out


def rebuild(out=print):
    trusted = set()
    tfile = os.path.join(BASE, "trusted.txt")
    if os.path.exists(tfile):
        trusted = {ln.strip() for ln in open(tfile, encoding="utf-8") if ln.strip() and not ln.startswith("#")}
    merged = {}          # flavor -> key -> cell -> [weight, set(contributors)]
    people = {}
    if os.path.isdir(RAW):
        for name in sorted(os.listdir(RAW)):
            if not name.endswith(".txt"):
                continue
            h = name[:-4]
            rows, _ = parse(open(os.path.join(RAW, name), encoding="utf-8").read())
            people[h] = len(rows)
            for (flavor, key), cells in rows.items():
                dst = merged.setdefault(flavor, {}).setdefault(key, {})
                for cell, w in cells.items():
                    cur = dst.setdefault(cell, [0, set()])
                    cur[0] += w
                    cur[1].add(h)
    for sub in ("spots", "areas"):
        os.makedirs(os.path.join(BASE, sub), exist_ok=True)
    db_path = os.path.join(BASE, "contributions.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    db.executescript("""
        create table spots(flavor text, key text, map integer, x real, y real, weight integer, contributors integer);
        create table areas(flavor text, key text, rank integer, map integer, x real, y real, r real, weight integer,
                           cells integer, contributors integer, confidence text);
        create table contributors(id text primary key, steps integer, trusted integer);
        create index spots_key on spots(flavor, key);
        create index areas_key on areas(flavor, key);
    """)
    counts = {}
    for flavor in FLAVORS:
        keys = merged.get(flavor, {})
        spot_path = os.path.join(BASE, "spots", flavor + ".csv")
        area_path = os.path.join(BASE, "areas", flavor + ".json")
        if not keys:
            for p in (spot_path, area_path):
                if os.path.exists(p):
                    os.remove(p)
            continue
        areas_out = {}
        with open(spot_path, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh, lineterminator="\n")
            wr.writerow(["key", "map", "x", "y", "weight", "contributors"])
            for key in sorted(keys):
                cells = keys[key]
                for (m, xq, yq) in sorted(cells):
                    w, ppl = cells[(m, xq, yq)]
                    wr.writerow([key, m, f"{xq * CELL:.1f}", f"{yq * CELL:.1f}", w, len(ppl)])
                    db.execute("insert into spots values(?,?,?,?,?,?,?)", (flavor, key, m, xq * CELL, yq * CELL, w, len(ppl)))
                found = cluster({c: (v[0], v[1]) for c, v in cells.items()})
                rows = []
                for rank, a in enumerate(found, 1):
                    ppl = a.pop("people")
                    conf = "trusted" if ppl & trusted else ("confirmed" if len(ppl) >= 2 else "single")
                    a["contributors"], a["confidence"] = len(ppl), conf
                    rows.append(a)
                    db.execute("insert into areas values(?,?,?,?,?,?,?,?,?,?,?)",
                               (flavor, key, rank, a["map"], a["x"], a["y"], a["r"], a["weight"], a["cells"], len(ppl), conf))
                if rows:
                    areas_out[key] = rows
        with open(area_path, "w", encoding="utf-8") as fh:
            json.dump({"flavor": flavor, "licence": "CC BY-SA 4.0", "source": "player contributions (Completionist's Guide addon)",
                       "areas": areas_out}, fh, indent=1, sort_keys=True)
            fh.write("\n")
        counts[flavor] = (len(keys), sum(len(v) for v in areas_out.values()))
    for h in sorted(people):
        db.execute("insert into contributors values(?,?,?)", (h, people[h], 1 if h in trusted else 0))
    db.commit()
    db.execute("vacuum")
    db.close()
    for flavor, (k, a) in sorted(counts.items()):
        out(f"{flavor}: {k} steps, {a} areas")
    out(f"contributors: {len(people)} ({len(trusted & set(people))} trusted)")
    return counts


def add(text, who, trusted=False, out=print):
    rows, problems = parse(text)
    for p in problems[:20]:
        out("note: " + p)
    if len(problems) > 20:
        out(f"note: {len(problems) - 20} more problems")
    if not rows:
        out("nothing usable in this contribution")
        return 0
    h = who_hash(who)
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, h + ".txt"), "w", encoding="utf-8") as fh:
        fh.write(normal_text(rows))
    if trusted:
        tfile = os.path.join(BASE, "trusted.txt")
        have = set()
        if os.path.exists(tfile):
            have = {ln.strip() for ln in open(tfile, encoding="utf-8") if ln.strip() and not ln.startswith("#")}
        if h not in have:
            with open(tfile, "a", encoding="utf-8") as fh:
                fh.write(h + "\n")
    per = {}
    for (flavor, _key) in rows:
        per[flavor] = per.get(flavor, 0) + 1
    out("accepted: " + ", ".join(f"{n} steps on {f}" for f, n in sorted(per.items())) + f" (contributor {h})")
    return len(rows)


LUA_DUMP = r'''
local path = arg[1]
local env = {}
local f = assert(loadfile(path))
setfenv(f, env)
f()
local db = env.CompletionRouteDB
local c = db and db.contrib and db.contrib.spots or {}
for flavor, keys in pairs(c) do
  for key, cells in pairs(keys) do
    local parts = {}
    for cell, w in pairs(cells) do
      local m, x, y = cell:match("^(%d+),(%-?%d+),(%-?%d+)$")
      if m then parts[#parts + 1] = ("%d,%.1f,%.1f,%d"):format(m, x * 0.2, y * 0.2, w) end
    end
    if #parts > 0 then io.write(flavor, "||", key, "|", table.concat(parts, ";"), "\n") end
  end
end
'''


def saved_to_text(path):
    lj = shutil.which("luajit") or shutil.which("lua5.1") or shutil.which("lua")
    if not lj:
        raise SystemExit("add-saved needs luajit or lua 5.1 on the PATH")
    r = subprocess.run([lj, "-e", LUA_DUMP.replace("arg[1]", json.dumps(path))], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("could not read the SavedVariables file: " + r.stderr.strip()[:300])
    return r.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("file")
    a.add_argument("--who", required=True)
    a.add_argument("--trusted", action="store_true")
    s = sub.add_parser("add-saved")
    s.add_argument("file")
    s.add_argument("--who", required=True)
    s.add_argument("--trusted", action="store_true")
    sub.add_parser("rebuild")
    c = sub.add_parser("check")
    c.add_argument("file")
    args = ap.parse_args(argv)
    if args.cmd == "rebuild":
        rebuild()
        return 0
    if args.cmd == "check":
        rows, problems = parse(open(args.file, encoding="utf-8", errors="replace").read())
        for p in problems:
            print("note: " + p)
        print(f"{len(rows)} usable steps")
        return 0 if rows else 1
    text = saved_to_text(args.file) if args.cmd == "add-saved" else open(args.file, encoding="utf-8", errors="replace").read()
    n = add(text, args.who, args.trusted)
    if n:
        rebuild()
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
