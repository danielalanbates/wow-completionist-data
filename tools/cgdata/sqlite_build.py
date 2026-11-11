# wow-completionist-data :: tools/cgdata/sqlite_build.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Stage 2 of tools/build_db.py: data/ + corrections/ -> build/completionist.sqlite (and optionally merged JSON).

Needs nothing but this repository.  Records are streamed one bucket file at a time; the corrections overlay is
applied last, record by record, so the SQLite file and the merged JSON always show corrected data.
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from . import common as C
from .schema import SCHEMAS, check

SCHEMA = """
create table meta(key text primary key, value text);
create table maps(flavor text, id int, name text, instance int, top_x real, left_y real, width real, height real,
    parent int, type int, primary key(flavor, id));
create table quests(flavor text, id int, name text, faction text, level int, min_level int, type text, category text,
    zone_map int, classes text, races text, profession text, is_breadcrumb text, auto_accept int, wiki_page text,
    wiki_revid int, db2_build text, variants int, id_conflict text, corrections text, json text,
    primary key(flavor, id));
create table quest_variants(flavor text, quest_id int, variant int, name text, faction text, wiki_page text,
    wiki_revid int, primary key(flavor, quest_id, variant));
create table quest_flavors(quest_id int, flavor text, primary key(quest_id, flavor));
create table quest_endpoints(flavor text, quest_id int, variant int, role text, idx int, kind text, ids text, name text,
    page text, faction text, map int, x real, y real, coord_type text, coord_page text, coord_revid int, coord_via text,
    read_as text, read_by text, check_against text, check_yards int, exact_version int, confidence text);
create table quest_objectives(flavor text, quest_id int, variant int, idx int, kind text, text text, count int,
    optional int, target_kind text, target_ids text, target_name text, map int, x real, y real, coord_type text,
    coord_via text, exact_version int, confidence text);
create table quest_points(flavor text, quest_id int, variant int, role text, idx int, map int, x real, y real);
create table quest_prereqs(flavor text, quest_id int, variant int, prereq_id int, class text, grp int, faction text);
create table quest_next(flavor text, quest_id int, next_id int);
create table npcs(flavor text, key text, kind text, ids text, name text, wiki_page text, wiki_revid int,
    corrections text, json text, primary key(flavor, kind, key));
create table npc_ids(flavor text, kind text, id int, key text);
create table npc_points(flavor text, kind text, key text, map int, x real, y real, exact_version int, via text,
    read_as text, read_by text, check_against text, check_yards int, confidence text);
create table achievements(flavor text, id int, name text, description text, category_id int, category_path text,
    points int, faction text, statistic int, guild int, account_wide int, wiki_page text, wiki_revid int,
    corrections text, json text, primary key(flavor, id));
create table achievement_criteria(flavor text, ach_id int, idx int, origin text, tree int, criteria int, type int,
    type_name text, asset int, amount int, text text, quest_id int, map int, x real, y real, via text, confidence text);
create table missions(flavor text, id int, name text, location text, garrison_type int, garrison_type_name text,
    follower_type int, target_level int, duration_s int, json text, primary key(flavor, id));
create table questv2(flavor text, id int, status text, reason text, primary key(flavor, id));
create table corrections_applied(correction text, flavor text, kind text, key text, status text, message text);
create index i_qe on quest_endpoints(flavor, quest_id);
create index i_qv on quest_variants(flavor, quest_id);
create index i_qo on quest_objectives(flavor, quest_id);
create index i_qp on quest_prereqs(flavor, quest_id);
create index i_qpr on quest_prereqs(flavor, prereq_id);
create index i_npcid on npc_ids(flavor, id);
create index i_ac on achievement_criteria(flavor, ach_id);
"""


def _key(kind, raw):
    if C.KINDS[kind][0] == "id" and isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return raw


def corrected_records(flavor, kind, corrections, data_dir=C.DATA, log=None, strict=True):
    """yield the records of one flavor/kind with the corrections applied (streamed per bucket file)"""
    log = log if log is not None else []
    mine = [(f, i, c) for f, i, c in C.corrections_for(flavor, kind, corrections)]
    for f, i, c in mine:
        c["key"] = _key(kind, c.get("key"))
    by_key = defaultdict(list)
    adds = []
    for f, i, c in mine:
        if c.get("path", "") == "" and c.get("op") == "add":
            adds.append((f, i, c))
        else:
            by_key[c.get("key")].append((f, i, c))
    seen = set()
    for p in C.bucket_files(flavor, kind, data_dir):
        doc = C.load_json(p)
        rows = doc.get("records", [])
        first = {}
        for r in rows:
            first.setdefault(C.record_key(kind, r), r)
        seen.update(k for k in by_key if k in first)
        view = dict(first)
        sub = sorted((x for k in first if k in by_key for x in by_key[k]), key=lambda x: (x[0], x[1]))
        if sub:
            log += [(cid, flavor, kind, k, st, msg) for cid, k, st, msg in
                    C.apply_corrections(flavor, kind, view, sub, strict=strict)]
        # file order is kept, and a duplicate key is passed through untouched so validation can report it
        for r in rows:
            k = C.record_key(kind, r)
            if first[k] is r:
                if k in view:
                    yield view[k]
            else:
                yield r
    for k, items in sorted(by_key.items(), key=lambda kv: str(kv[0])):
        if k in seen:
            continue
        for f, i, c in items:
            msg = f"no {kind} record {k!r} on {flavor}"
            if c.get("flavor") == "all":
                log.append((c.get("id"), flavor, kind, k, "skipped", msg))
            elif strict:
                raise ValueError(f"correction {c.get('id')} ({f}): {msg}")
            else:
                log.append((c.get("id"), flavor, kind, k, "error", msg))
    if adds:
        newrecs = {}
        res = C.apply_corrections(flavor, kind, newrecs, sorted(adds, key=lambda x: (x[0], x[1])), strict=strict)
        log += [(cid, flavor, kind, k, st, msg) for cid, k, st, msg in res]
        for r in newrecs.values():
            if C.record_key(kind, r) in seen:
                raise ValueError(f"correction adds {kind} {C.record_key(kind, r)!r} that already exists")
            yield r


def _first(coords):
    return (coords[0]["map"], coords[0]["x"], coords[0]["y"]) if coords else (None, None, None)


def _src(cs):
    cs = cs or {}
    return cs.get("type"), cs.get("page"), cs.get("revid"), cs.get("via")


def _chk(cs):
    ch = (cs or {}).get("check") or {}
    return (cs or {}).get("read_as"), (cs or {}).get("read_by"), ch.get("against"), ch.get("yards")


def _flag(v):
    return None if v is None else int(bool(v))


def record_problems(kind, rec, maps):
    """the record schema plus "every point is on a known map, 0-100" (the build refuses records that fail; the
    full cross-record validation is tools/validate.py)"""
    probs = check(rec, SCHEMAS[kind])
    pts = []

    def walk(v):
        if isinstance(v, dict):
            if "map" in v and "x" in v and "y" in v and not isinstance(v.get("map"), dict):
                pts.append(v)
            for k, x in v.items():
                if k != "replaces":
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(rec)
    for p in pts:
        if p.get("map") not in maps:
            probs.append(f"point on map {p.get('map')!r}, not in maps.json")
        for a in ("x", "y"):
            if not isinstance(p.get(a), (int, float)) or isinstance(p.get(a), bool) or not 0 <= p[a] <= 100:
                probs.append(f"{a}={p.get(a)!r} outside 0-100")
    return probs


def build_sqlite(out_path, data_dir=C.DATA, corr_dir=C.CORRECTIONS, json_dir=None, strict=True, flavors=C.FLAVORS):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    corrections = C.load_corrections(corr_dir)
    meta = C.load_json(Path(data_dir) / "meta.json") if (Path(data_dir) / "meta.json").exists() else {}
    db.executemany("insert into meta values (?,?)",
                   [("schema_version", str(C.SCHEMA_VERSION)), ("sources", json.dumps(meta.get("sources", {}))),
                    ("corrections_files", json.dumps(sorted({f for f, _i, _c in corrections})))])
    log = []
    counts = {}
    for fl in flavors:
        counts[fl] = {}
        mp = Path(data_dir) / fl / "maps.json"
        if mp.exists():
            for row in C.load_json(mp)["maps"]:
                db.execute("insert into maps values (?,?,?,?,?,?,?,?,?,?)", [fl] + row)
        qp = Path(data_dir) / fl / "questv2.json"
        if qp.exists():
            q2 = C.load_json(qp)
            exc = {e["id"]: e["reason"] for e in q2.get("excluded", [])}
            status = {i: ("excluded", exc[i]) if i in exc else ("no_wiki_page", None) for i in q2["ids"]}
        else:
            status = {}
        jfiles = {}
        if json_dir:
            for kind in C.KINDS:
                p = Path(json_dir) / fl / f"{kind}.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                jfiles[kind] = [p, open(p, "w", encoding="utf-8"), 0]
                jfiles[kind][1].write("[\n")

        def jwrite(kind, rec):
            if jfiles:
                f = jfiles[kind]
                f[1].write(("," if f[2] else "") + C.dumps_record(rec) + "\n")
                f[2] += 1
        maps = {row[1] for row in db.execute("select flavor, id from maps where flavor=?", (fl,))}

        def checked(kind, rec):
            probs = record_problems(kind, rec, maps)
            if probs:
                msg = f"{fl} {kind} {C.record_key(kind, rec)!r}: " + "; ".join(probs[:3])
                if strict:
                    raise ValueError(msg + " (python3 tools/validate.py lists every problem)")
                log.append((None, fl, kind, str(C.record_key(kind, rec)), "error", msg))
            return rec
        n = 0
        for q in corrected_records(fl, "quests", corrections, data_dir, log, strict):
            checked("quests", q)
            n += 1
            qid = q["id"]
            if qid in status:
                status[qid] = ("wiki", None)
            src = q.get("source", {})
            db.execute("insert into quests values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                fl, qid, q["name"], q["faction"], q["level"], q["min_level"], q["type"], q["category"], q["zone_map"],
                ",".join(q["classes"]), ",".join(q["races"]), q["profession"], q["is_breadcrumb"],
                int(bool(q["auto_accept"])), src.get("wiki", {}).get("page"), src.get("wiki", {}).get("revid"),
                src.get("db2", {}).get("build"), len(q.get("variants", [])),
                ",".join(c["page"] for c in q.get("id_conflict", [])) or None,
                ",".join(q.get("corrections", [])) or None, C.dumps_record(q)))
            for f2 in q.get("flavors", []):
                db.execute("insert or ignore into quest_flavors values (?,?)", (qid, f2))
            for vi, v in enumerate([q] + q.get("variants", [])):
                if vi:
                    w = v["source"]["wiki"]
                    db.execute("insert into quest_variants values (?,?,?,?,?,?,?)",
                               (fl, qid, vi, v["name"], v["faction"], w.get("page"), w.get("revid")))
                for role in ("start", "end"):
                    for i, e in enumerate(v[role]):
                        m, x, y = _first(e["coords"])
                        t, pg, rv, via = _src(e.get("coord_source"))
                        ra, rb, ca, cy = _chk(e.get("coord_source"))
                        db.execute("insert into quest_endpoints values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (fl, qid, vi, role, i, e["kind"], ",".join(map(str, e["ids"])), e["name"],
                                    e["page"], e["faction"], m, x, y, t, pg, rv, via, ra, rb, ca, cy,
                                    _flag(e.get("exact_version")), e.get("confidence")))
                        for c in e["coords"]:
                            db.execute("insert into quest_points values (?,?,?,?,?,?,?,?)",
                                       (fl, qid, vi, role, i, c["map"], c["x"], c["y"]))
                for o in v["objectives"]:
                    m, x, y = _first(o["coords"])
                    t, _pg, _rv, via = _src(o.get("coord_source"))
                    tg = o.get("target") or {}
                    db.execute("insert into quest_objectives values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                        fl, qid, vi, o["index"], o["kind"], o["text"], o["count"], int(bool(o["optional"])),
                        tg.get("kind"), ",".join(map(str, tg.get("ids") or [])) or None, tg.get("name"), m, x, y, t,
                        via, _flag(o.get("exact_version")), o.get("confidence")))
                    for c in o["coords"]:
                        db.execute("insert into quest_points values (?,?,?,?,?,?,?,?)",
                                   (fl, qid, vi, "objective", o["index"], c["map"], c["x"], c["y"]))
                pr = v["prerequisites"]
                fac = pr.get("faction", {})
                for gi, grp in enumerate(pr["required"]):
                    for pid in grp:
                        db.execute("insert into quest_prereqs values (?,?,?,?,?,?,?)",
                                   (fl, qid, vi, pid, "required", gi, fac.get(str(pid))))
                for cls in ("breadcrumb", "optional", "in_progress", "inferred_from_next"):
                    for pid in pr.get(cls, []):
                        db.execute("insert into quest_prereqs values (?,?,?,?,?,?,?)",
                                   (fl, qid, vi, pid, cls, None, fac.get(str(pid))))
            for nx in q["next"]:
                db.execute("insert into quest_next values (?,?,?)", (fl, qid, nx))
            jwrite("quests", q)
        counts[fl]["quests"] = n
        for kind in ("npcs", "objects"):
            n = 0
            for r in corrected_records(fl, kind, corrections, data_dir, log, strict):
                checked(kind, r)
                n += 1
                w = r.get("source", {}).get("wiki", {})
                db.execute("insert into npcs values (?,?,?,?,?,?,?,?,?)", (
                    fl, r["key"], r["kind"], ",".join(map(str, r["ids"])), r["name"], w.get("page"), w.get("revid"),
                    ",".join(r.get("corrections", [])) or None, C.dumps_record(r)))
                for i in r["ids"]:
                    db.execute("insert into npc_ids values (?,?,?,?)", (fl, r["kind"], i, r["key"]))
                for c in r["coords"]:
                    ch = c.get("check") or {}
                    db.execute("insert into npc_points values (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                        fl, r["kind"], r["key"], c["map"], c["x"], c["y"], int(bool(c.get("exact_version"))),
                        c.get("via"), c.get("read_as"), c.get("read_by"), ch.get("against"), ch.get("yards"),
                        c.get("confidence")))
                jwrite(kind, r)
            counts[fl][kind] = n
        n = 0
        for a in corrected_records(fl, "achievements", corrections, data_dir, log, strict):
            checked("achievements", a)
            n += 1
            w = a.get("wiki") or {}
            db.execute("insert into achievements values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                fl, a["id"], a["name"], a["description"], a["category"]["id"], " > ".join(a["category"]["path"]),
                a["points"], a["faction"], int(a["statistic"]), int(a["guild"]), int(a["account_wide"]),
                w.get("page"), w.get("revid"), ",".join(a.get("corrections", [])) or None, C.dumps_record(a)))
            for i, c in enumerate(a["criteria"]):
                loc = c.get("location") or {}
                db.execute("insert into achievement_criteria values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    fl, a["id"], i, "db2", c["tree"], c["criteria"], c["type"], c["type_name"], c["asset"],
                    c["amount"], c["text"], c["asset"] if c["type"] == 27 else None, loc.get("map"), loc.get("x"),
                    loc.get("y"), loc.get("via"), loc.get("confidence")))
            for i, c in enumerate(w.get("criteria", [])):
                loc = c.get("location") or {}
                db.execute("insert into achievement_criteria values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    fl, a["id"], i, "wiki", None, None, None, None, None, None, c["text"], c["quest"], loc.get("map"),
                    loc.get("x"), loc.get("y"), loc.get("via"), loc.get("confidence")))
            jwrite("achievements", a)
        counts[fl]["achievements"] = n
        n = 0
        for m in corrected_records(fl, "missions", corrections, data_dir, log, strict):
            checked("missions", m)
            n += 1
            db.execute("insert into missions values (?,?,?,?,?,?,?,?,?,?)", (
                fl, m["id"], m["name"], m["location"], m["garrison_type"], m["garrison_type_name"], m["follower_type"],
                m["target_level"], m["duration_s"], C.dumps_record(m)))
            jwrite("missions", m)
        counts[fl]["missions"] = n
        db.executemany("insert into questv2 values (?,?,?,?)",
                       [(fl, i, s, why) for i, (s, why) in sorted(status.items())])
        for kind, f in jfiles.items():
            f[1].write("]\n")
            f[1].close()
            if f[2] == 0:
                f[0].unlink()
    db.executemany("insert into corrections_applied values (?,?,?,?,?,?)",
                   [(cid, fl, kind, None if key is None else str(key), st, msg) for cid, fl, kind, key, st, msg in log])
    db.execute("insert into meta values ('counts', ?)", (json.dumps(counts, sort_keys=True),))
    db.commit()
    db.execute("vacuum")
    db.close()
    tmp.replace(out_path)
    return counts, log
