#!/usr/bin/env python3
# wow-completionist-data :: tools/validate.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Validate data/ (with the corrections overlay applied) and write the coverage report.

    python3 tools/validate.py                 # check everything; exit 1 on any error
    python3 tools/validate.py --coverage      # ... and rewrite docs/COVERAGE.md + docs/coverage.csv
    python3 tools/validate.py --no-corrections era retail

Checks (errors unless marked):
  * every bucket file: header matches its folder, every record sits in the right bucket
  * schema of every record (tools/cgdata/schema.py; docs/SCHEMA.md)
  * ids unique per flavor and kind (npc/object page keys unique; a game id on two pages is a warning)
  * every coordinate is on a map listed in data/<flavor>/maps.json, with 0 <= x, y <= 100, and says where it came from
  * every quest: its id is in the client's QuestV2 (data/<flavor>/questv2.json), not also listed as excluded, its
    `flavors` include this flavor, prerequisites and `next` resolve to quests of the same flavor
  * prerequisites some player can meet: after the documented faction filter, every required group must keep a quest
    that the player's faction can take (an Alliance quest that needs a Horde-only quest, or a quest both factions take
    that needs one Alliance-only and one Horde-only quest, is an error)
  * warnings: a wiki point more than 50 yd from Blizzard's position for the same NPC (coord_source.check), an id
    that other wiki pages give to a differently named quest (id_conflict)
  * provenance: wiki page + revision id, or DB2 table + build, on every record
  * corrections: well-formed, unique ids, and each one applies (a correction that matches nothing is an error)
Streams one bucket file at a time.
"""
import argparse
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cgdata import common as C  # noqa: E402
from cgdata.schema import SCHEMAS, check  # noqa: E402
from cgdata.sqlite_build import corrected_records  # noqa: E402


class Report:
    def __init__(self, max_per_kind=15):
        self.errors, self.warnings = [], []
        self.count = Counter()
        self.max = max_per_kind

    def err(self, kind, msg):
        self.count[("error", kind)] += 1
        if self.count[("error", kind)] <= self.max:
            self.errors.append(f"[{kind}] {msg}")

    def warn(self, kind, msg):
        self.count[("warning", kind)] += 1
        if self.count[("warning", kind)] <= self.max:
            self.warnings.append(f"[{kind}] {msg}")

    def n_errors(self):
        return sum(v for (lvl, _k), v in self.count.items() if lvl == "error")


def check_files(fl, kind, rep, data_dir):
    for p in C.bucket_files(fl, kind, data_dir):
        try:
            doc = C.load_json(p)
        except json.JSONDecodeError as e:
            rep.err("json", f"{p.relative_to(data_dir)}: {e}")
            continue
        if doc.get("flavor") != fl or doc.get("kind") != kind or doc.get("bucket") != p.stem:
            rep.err("bucket", f"{p.relative_to(data_dir)}: header says {doc.get('flavor')}/{doc.get('kind')}/"
                              f"{doc.get('bucket')}")
        recs = doc.get("records", [])
        if doc.get("count") != len(recs):
            rep.err("bucket", f"{p.relative_to(data_dir)}: count {doc.get('count')} but {len(recs)} records")
        for r in recs:
            try:
                b = C.bucket_of(kind, r)
            except (KeyError, TypeError, ValueError):
                continue  # the schema check reports it
            if b != p.stem:
                rep.err("bucket", f"{fl}/{kind} {C.record_key(kind, r)!r} is in {p.stem}, belongs in {b}")


def coord_ok(c, maps, rep, where):
    ok = True
    if c.get("map") not in maps:
        rep.err("coords", f"{where}: map {c.get('map')} is not in maps.json")
        ok = False
    for a in ("x", "y"):
        v = c.get(a)
        if not isinstance(v, (int, float)) or not 0 <= v <= 100:
            rep.err("coords", f"{where}: {a}={v!r} outside 0-100")
            ok = False
    return ok


TOL = 50


def located(points_holder, maps, rep, where, cv=None, role=None):
    """check a dict with coords/coord_source/exact_version/confidence; -> source type or None"""
    cs = points_holder.get("coords") or []
    for c in cs:
        coord_ok(c, maps, rep, where)
    if cs:
        src = points_holder.get("coord_source")
        if not src:
            rep.err("provenance", f"{where}: coordinates without coord_source")
            return None
        if src.get("type") == "wiki" and not src.get("revid"):
            rep.warn("provenance", f"{where}: wiki coordinate page {src.get('page')!r} has no revision id")
        if not isinstance(points_holder.get("exact_version"), bool):
            rep.err("schema", f"{where}: exact_version must be true/false when coordinates are given")
        if points_holder.get("confidence") not in ("high", "medium", "low"):
            rep.err("schema", f"{where}: confidence must be high/medium/low when coordinates are given")
        chk = src.get("check")
        if chk and chk.get("yards", 0) > TOL:
            rep.warn("check", f"{where}: wiki point is {chk['yards']} yd from Blizzard's {chk['against']} "
                              f"{chk['id']} for the same NPC (confidence {points_holder.get('confidence')})")
        if cv is not None and role:
            cv[f"{role}_confidence_{points_holder.get('confidence')}"] += 1
            if chk:
                cv[f"{role}_checked"] += 1
                cv[f"{role}_checked_within_{TOL}yd"] += chk["yards"] <= TOL
            if (src.get("replaces") or {}).get("yards") is not None:
                cv[f"{role}_wiki_point_replaced_by_pin"] += 1
        return src.get("type")
    elif points_holder.get("confidence") is not None:
        rep.err("schema", f"{where}: confidence without coordinates")
    return None


def sides_of(rec):
    """the factions that can take a quest record (with its faction variants)"""
    out = set()
    for h in [rec] + rec.get("variants", []):
        f = h.get("faction")
        out |= {f} if f in ("Alliance", "Horde") else {"Alliance", "Horde"}
    return out


def unmeetable(holder, avail):
    """-> [(faction, group)] required groups that no player of that faction can complete, after the documented
    faction filter (drop ids tagged with the other faction, then empty groups)"""
    pr = holder["prerequisites"]
    tags = pr.get("faction", {})
    f = holder.get("faction")
    bad = []
    for side in ([f] if f in ("Alliance", "Horde") else ["Alliance", "Horde"]):
        for grp in pr["required"]:
            keep = [i for i in grp if tags.get(str(i)) in (None, side)]
            if keep and not any(side in avail.get(i, ()) for i in keep):
                bad.append((side, keep))
    return bad


def validate_flavor(fl, rep, cov, corrections, data_dir):
    d = Path(data_dir) / fl
    maps = {}
    if (d / "maps.json").exists():
        maps = {row[0]: row for row in C.load_json(d / "maps.json")["maps"]}
    else:
        rep.err("files", f"{fl}: maps.json missing")
    q2_ids, q2_exc = set(), set()
    if (d / "questv2.json").exists():
        q2 = C.load_json(d / "questv2.json")
        q2_ids = set(q2["ids"])
        q2_exc = {e["id"] for e in q2.get("excluded", [])}
        if q2.get("count") != len(q2["ids"]) or len(q2_ids) != len(q2["ids"]):
            rep.err("questv2", f"{fl}: questv2.json count/ids mismatch or duplicate ids")
        if not q2_exc <= q2_ids:
            rep.err("questv2", f"{fl}: {len(q2_exc - q2_ids)} excluded ids are not in QuestV2")
        if not q2.get("build"):
            rep.err("provenance", f"{fl}: questv2.json has no build")
    else:
        rep.err("files", f"{fl}: questv2.json missing")
    cv = cov[fl]
    cv["questv2_ids"] = len(q2_ids)
    cv["questv2_excluded_by_wiki_rules"] = len(q2_exc)
    log = []
    for kind in C.KINDS:
        check_files(fl, kind, rep, data_dir)
    # ---- quests ----
    quest_ids, refs, avail, holders = set(), [], {}, []
    for q in corrected_records(fl, "quests", corrections, data_dir, log, strict=False):
        where = f"{fl} quest {q.get('id')}"
        probs = check(q, SCHEMAS["quests"])
        if probs:
            for pmsg in probs[:3]:
                rep.err("schema", f"{where}: {pmsg}")
            continue
        qid = q["id"]
        if qid in quest_ids:
            rep.err("unique", f"{where}: duplicate quest id")
        quest_ids.add(qid)
        if qid not in q2_ids:
            rep.err("questv2", f"{where}: not in the client's QuestV2")
        if qid in q2_exc:
            rep.err("questv2", f"{where}: also listed as excluded in questv2.json")
        if fl not in q["flavors"]:
            rep.err("schema", f"{where}: flavors {q['flavors']} do not include {fl}")
        if q["zone_map"] is not None and q["zone_map"] not in maps:
            rep.err("coords", f"{where}: zone_map {q['zone_map']} is not in maps.json")
        w = q["source"]["wiki"]
        if not w.get("revid"):
            rep.warn("provenance", f"{where}: wiki page {w.get('page')!r} has no revision id")
        avail[qid] = sides_of(q)
        for vi, h in enumerate([q] + q.get("variants", [])):
            pr = h["prerequisites"]
            for grp in pr["required"]:
                if not grp:
                    rep.err("prereq", f"{where}: empty required group")
                refs += [(qid, p, "required") for p in grp]
            for cls in ("breadcrumb", "optional", "in_progress", "inferred_from_next"):
                refs += [(qid, p, cls) for p in pr[cls]]
            refs += [(qid, n, "next") for n in h["next"]]
            holders.append((qid, vi, {"faction": h["faction"], "prerequisites": pr}))
            if vi:
                for role in ("start", "end"):
                    for i, e in enumerate(h[role]):
                        located(e, maps, rep, f"{where} variant {vi} {role}[{i}]")
                for o in h["objectives"]:
                    located(o, maps, rep, f"{where} variant {vi} objective {o.get('index')}")
        if q.get("variants"):
            cv["quests_with_faction_variants"] += 1
        if q.get("id_conflict"):
            cv["quests_with_id_conflict"] += 1
            rep.warn("id-conflict", f"{where}: the wiki also gives this id to "
                                    + ", ".join(repr(c["page"]) for c in q["id_conflict"][:3]))
        pr = q["prerequisites"]
        cv["quests"] += 1
        st = [located(e, maps, rep, f"{where} start[{i}]", cv, "start") for i, e in enumerate(q["start"])]
        en = [located(e, maps, rep, f"{where} end[{i}]", cv, "end") for i, e in enumerate(q["end"])]
        s_any, e_any = any(st), any(en)
        cv["quests_start_located"] += s_any
        cv["quests_end_located"] += e_any
        cv["quests_start_and_end_located"] += s_any and e_any
        cv["quests_start_located_exact_version"] += any(e["coords"] and e["exact_version"] for e in q["start"])
        cv["quests_end_located_exact_version"] += any(e["coords"] and e["exact_version"] for e in q["end"])
        first_s = next((t for t in st if t), None)
        first_e = next((t for t in en if t), None)
        if first_s:
            cv[f"quests_start_located_from_{first_s}"] += 1
        if first_e:
            cv[f"quests_end_located_from_{first_e}"] += 1
        cv["quests_with_objectives"] += bool(q["objectives"])
        cv["quests_start_located_confidence_high"] += any(e["coords"] and e["confidence"] == "high" for e in q["start"])
        cv["quests_start_located_confidence_high_or_medium"] += any(
            e["coords"] and e["confidence"] in ("high", "medium") for e in q["start"])
        cv["quests_end_located_confidence_high_or_medium"] += any(
            e["coords"] and e["confidence"] in ("high", "medium") for e in q["end"])
        for i, o in enumerate(q["objectives"]):
            t = located(o, maps, rep, f"{where} objective {o.get('index')}", cv, "objective")
            if o["kind"] != "provided":
                cv["objectives"] += 1
                if t:
                    cv["objectives_located"] += 1
                    cv[f"objectives_located_from_{t}"] += 1
        has_pre = pr["required"] or pr["breadcrumb"] or pr["optional"] or pr["in_progress"] or pr["inferred_from_next"]
        cv["quests_with_prerequisites"] += bool(has_pre)
        cv["quests_with_required_prerequisites"] += bool(pr["required"])
        cv["quests_with_any_of_group"] += any(len(g) > 1 for g in pr["required"])
        cv["quests_with_breadcrumb_prerequisites"] += bool(pr["breadcrumb"])
        cv["quests_with_optional_prerequisites"] += bool(pr["optional"])
        cv["quests_with_prerequisites_inferred_from_next"] += bool(pr["inferred_from_next"])
        cv["quests_prerequisite_basis_list_ambiguous"] += pr["basis"] == "list"
        cv["quests_flagged_breadcrumb"] += bool(q["is_breadcrumb"])
        cv["quests_corrected"] += bool(q.get("corrections"))
    for qid, p, cls in refs:
        if p not in quest_ids:
            rep.err("prereq", f"{fl} quest {qid}: {cls} quest {p} is not a {fl} quest")
    for qid, vi, h in holders:
        for side, grp in unmeetable(h, avail):
            cv["prerequisite_groups_no_player_can_meet"] += 1
            rep.err("prereq-faction", f"{fl} quest {qid}{f' variant {vi}' if vi else ''}: no {side} player can "
                                      f"complete any of the required quests {grp}")
    cv["questv2_ids_without_wiki_page"] = len(q2_ids - quest_ids - q2_exc)
    # ---- npcs / objects ----
    for kind in ("npcs", "objects"):
        keys, by_id = set(), defaultdict(list)
        for r in corrected_records(fl, kind, corrections, data_dir, log, strict=False):
            where = f"{fl} {kind[:-1]} {r.get('key')!r}"
            probs = check(r, SCHEMAS[kind])
            if probs:
                for pmsg in probs[:3]:
                    rep.err("schema", f"{where}: {pmsg}")
                continue
            if r["key"] in keys:
                rep.err("unique", f"{where}: duplicate key")
            keys.add(r["key"])
            for i in r["ids"]:
                by_id[i].append(r["key"])
            if not r["source"]["wiki"].get("revid"):
                rep.warn("provenance", f"{where}: no wiki revision id")
            for c in r["coords"]:
                coord_ok(c, maps, rep, where)
                cv[f"{kind}_points_confidence_{c['confidence']}"] += 1
            cv[kind] += 1
            cv[f"{kind}_located"] += bool(r["coords"])
            cv[f"{kind}_located_exact_version"] += any(c["exact_version"] for c in r["coords"])
        dup = {i: ks for i, ks in by_id.items() if len(ks) > 1}
        cv[f"{kind}_ids_on_several_pages"] = len(dup)
        for i, ks in sorted(dup.items())[:3]:
            rep.warn("unique", f"{fl} {kind}: id {i} is on {len(ks)} wiki pages {ks[:3]}")
    # ---- achievements ----
    ach_ids = set()
    for a in corrected_records(fl, "achievements", corrections, data_dir, log, strict=False):
        where = f"{fl} achievement {a.get('id')}"
        probs = check(a, SCHEMAS["achievements"])
        if probs:
            for pmsg in probs[:3]:
                rep.err("schema", f"{where}: {pmsg}")
            continue
        if a["id"] in ach_ids:
            rep.err("unique", f"{where}: duplicate id")
        ach_ids.add(a["id"])
        if not a["source"]["db2"].get("build"):
            rep.err("provenance", f"{where}: no DB2 build")
        locs = [c["location"] for c in a["criteria"] if c["location"]]
        locs += [c["location"] for c in (a["wiki"] or {}).get("criteria", []) if c["location"]]
        for loc in locs:
            coord_ok(loc, maps, rep, where)
        cv["achievements"] += 1
        cv["achievements_not_statistics"] += not a["statistic"]
        cv["achievements_with_wiki_page"] += bool(a["wiki"])
        cv["achievements_located"] += bool(locs)
        cv["achievements_not_statistics_located"] += bool(locs) and not a["statistic"]
        cv["achievement_criteria"] += len(a["criteria"])
        cv["achievement_criteria_located"] += sum(1 for c in a["criteria"] if c["location"])
    # ---- missions ----
    mis = set()
    for m in corrected_records(fl, "missions", corrections, data_dir, log, strict=False):
        probs = check(m, SCHEMAS["missions"])
        if probs:
            for pmsg in probs[:3]:
                rep.err("schema", f"{fl} mission {m.get('id')}: {pmsg}")
            continue
        if m["id"] in mis:
            rep.err("unique", f"{fl} mission {m['id']}: duplicate id")
        mis.add(m["id"])
        cv["missions"] += 1
    for cid, _fl, kind, key, status, msg in log:
        if status == "error":
            rep.err("correction", f"{cid} ({fl} {kind} {key}): {msg}")
        elif status == "applied":
            cv["corrections_applied"] += 1


def validate_corrections(corrections, rep):
    seen = set()
    for fname, idx, c in corrections:
        for pmsg in C.correction_problems(c):
            rep.err("correction", f"{fname}#{idx}: {pmsg}")
        cid = c.get("id")
        if cid in seen:
            rep.err("correction", f"{fname}#{idx}: duplicate id {cid!r}")
        seen.add(cid)
        if not str(c.get("evidence", "")).strip():
            rep.warn("correction", f"{fname}#{idx} {cid}: no evidence given")


PCT = [("quests_start_located", "quests"), ("quests_end_located", "quests"), ("quests_start_and_end_located", "quests"),
       ("quests_start_located_exact_version", "quests"), ("objectives_located", "objectives"),
       ("quests_with_prerequisites", "quests"), ("npcs_located", "npcs"), ("objects_located", "objects"),
       ("achievements_located", "achievements"), ("achievements_not_statistics_located", "achievements_not_statistics"),
       ("achievement_criteria_located", "achievement_criteria")]


def write_coverage(cov, meta, flavors):
    rows = []
    for fl in flavors:
        for k, v in sorted(cov[fl].items()):
            rows.append((fl, k, v))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["flavor", "metric", "value"])
    w.writerows(rows)
    C.write_if_changed(C.REPO / "docs" / "coverage.csv", buf.getvalue())

    def pct(fl, a, b):
        n, d = cov[fl].get(a, 0), cov[fl].get(b, 0)
        return f"{n:,} / {d:,} ({100.0 * n / d:.1f}%)" if d else "n/a"
    src = meta.get("sources", {})
    wiki = src.get("wiki", {})
    lines = [
        "# Coverage",
        "",
        "Generated by `python3 tools/validate.py --coverage` from `data/` with `corrections/` applied. Every number "
        "below is counted from the records themselves; nothing is estimated. The same numbers are in "
        "[coverage.csv](coverage.csv).",
        "",
        f"Inputs: Warcraft Wiki revisions from {(wiki.get('oldest_revision') or '?')[:10]} to "
        f"{(wiki.get('newest_revision') or '?')[:10]} ({wiki.get('pages_used', 0):,} pages used); Blizzard DB2 builds "
        + ", ".join(f"{fl} `{src.get('db2', {}).get(fl, {}).get('build')}`" for fl in flavors) + ".",
        "",
        "## Quests",
        "",
        "| | " + " | ".join(flavors) + " |",
        "|---|" + "---:|" * len(flavors),
    ]

    def row(label, f):
        lines.append(f"| {label} | " + " | ".join(f(fl) for fl in flavors) + " |")

    row("QuestV2 ids in the client", lambda fl: f"{cov[fl].get('questv2_ids', 0):,}")
    row("quests in this dataset (wiki page, membership rules pass)", lambda fl: f"{cov[fl].get('quests', 0):,}")
    row("QuestV2 ids the wiki rules exclude (removed, other version, ambiguous id...)",
        lambda fl: f"{cov[fl].get('questv2_excluded_by_wiki_rules', 0):,}")
    row("QuestV2 ids with no wiki quest page", lambda fl: f"{cov[fl].get('questv2_ids_without_wiki_page', 0):,}")
    row("QuestV2 ids left out as ambiguous (3+ differently named wiki pages)",
        lambda fl: f"{meta.get('counts', {}).get(fl, {}).get('questv2_excluded_ambiguous_id', 0):,}")
    row("quests with a faction twin in `variants`", lambda fl: f"{cov[fl].get('quests_with_faction_variants', 0):,}")
    row("quests whose id another wiki page also claims (`id_conflict`)",
        lambda fl: f"{cov[fl].get('quests_with_id_conflict', 0):,}")
    row("start located", lambda fl: pct(fl, "quests_start_located", "quests"))
    row("... written for this game version", lambda fl: pct(fl, "quests_start_located_exact_version", "quests"))
    row("... confidence high (agrees with a Blizzard position)",
        lambda fl: pct(fl, "quests_start_located_confidence_high", "quests"))
    row("... confidence high or medium", lambda fl: pct(fl, "quests_start_located_confidence_high_or_medium", "quests"))
    row("end located", lambda fl: pct(fl, "quests_end_located", "quests"))
    row("... from the wiki", lambda fl: pct(fl, "quests_end_located_from_wiki", "quests"))
    row("... from DB2 turn-in pins (retail)", lambda fl: pct(fl, "quests_end_located_from_db2", "quests"))
    row("... confidence high or medium", lambda fl: pct(fl, "quests_end_located_confidence_high_or_medium", "quests"))
    row("start and end located", lambda fl: pct(fl, "quests_start_and_end_located", "quests"))
    row("objectives located", lambda fl: pct(fl, "objectives_located", "objectives"))
    row("... from DB2 objective areas (retail)", lambda fl: pct(fl, "objectives_located_from_db2", "objectives"))
    lines += ["", "### Confidence of located points", "",
              "Every located endpoint, objective and NPC point says how far to trust it (`confidence`, "
              "docs/SCHEMA.md#coordinates). Counts are points, not quests.", "",
              "| | " + " | ".join(flavors) + " |", "|---|" + "---:|" * len(flavors)]
    for role, label in (("start", "start points"), ("end", "end points"), ("objective", "objective points")):
        for lvl in ("high", "medium", "low"):
            row(f"{label}: {lvl}", lambda fl, k=f"{role}_confidence_{lvl}": f"{cov[fl].get(k, 0):,}")
        row(f"{label}: checked against a Blizzard position / within 50 yd of it",
            lambda fl, r=role: f"{cov[fl].get(f'{r}_checked', 0):,} / {cov[fl].get(f'{r}_checked_within_50yd', 0):,}")
    row("end points: wiki point replaced by the turn-in pin (more than 50 yd off)",
        lambda fl: f"{cov[fl].get('end_wiki_point_replaced_by_pin', 0):,}")
    for lvl in ("high", "medium", "low"):
        row(f"NPC points: {lvl}", lambda fl, k=f"npcs_points_confidence_{lvl}": f"{cov[fl].get(k, 0):,}")
    lines += ["", "### Quest structure", "", "| | " + " | ".join(flavors) + " |", "|---|" + "---:|" * len(flavors)]
    row("quests with prerequisites", lambda fl: pct(fl, "quests_with_prerequisites", "quests"))
    row("... with an any-of group", lambda fl: f"{cov[fl].get('quests_with_any_of_group', 0):,}")
    row("... with breadcrumb prerequisites", lambda fl: f"{cov[fl].get('quests_with_breadcrumb_prerequisites', 0):,}")
    row("... with optional prerequisites", lambda fl: f"{cov[fl].get('quests_with_optional_prerequisites', 0):,}")
    row("... only inferred from another quest's `next`",
        lambda fl: f"{cov[fl].get('quests_with_prerequisites_inferred_from_next', 0):,}")
    row("... several links separated only by line breaks (read as all-of, ambiguous)",
        lambda fl: f"{cov[fl].get('quests_prerequisite_basis_list_ambiguous', 0):,}")
    row("quests whose own page calls them a breadcrumb", lambda fl: f"{cov[fl].get('quests_flagged_breadcrumb', 0):,}")
    lines += ["", "## NPCs, objects, achievements, missions", "",
              "| | " + " | ".join(flavors) + " |", "|---|" + "---:|" * len(flavors)]
    row("NPCs referenced by this flavor's records", lambda fl: f"{cov[fl].get('npcs', 0):,}")
    row("... located", lambda fl: pct(fl, "npcs_located", "npcs"))
    row("objects referenced", lambda fl: f"{cov[fl].get('objects', 0):,}")
    row("... located", lambda fl: pct(fl, "objects_located", "objects"))
    row("achievements (client DB2)", lambda fl: f"{cov[fl].get('achievements', 0):,}" if cov[fl].get('achievements') else "none in this version")
    row("... with a wiki page", lambda fl: pct(fl, "achievements_with_wiki_page", "achievements"))
    row("... located (at least one criterion has a map point)", lambda fl: pct(fl, "achievements_located", "achievements"))
    row("... of the non-statistics, located",
        lambda fl: pct(fl, "achievements_not_statistics_located", "achievements_not_statistics"))
    row("achievement criteria located", lambda fl: pct(fl, "achievement_criteria_located", "achievement_criteria"))
    row("missions (GarrMission)", lambda fl: f"{cov[fl].get('missions', 0):,}" if cov[fl].get('missions') else "none")
    row("corrections applied", lambda fl: f"{cov[fl].get('corrections_applied', 0):,}")
    counts = meta.get("counts", {})
    rt = counts.get("retail", {}).get("retail_turnin_check")
    cr = meta.get("coordinate_reading", {})
    lines += ["", "## Cross-checks", ""]
    if rt and rt.get("compared"):
        n = rt.get("over_50_yd_replaced_by_pin", rt.get("over_50_yd", 0))
        lines.append(f"* Retail: where the wiki gives an end point and Blizzard's turn-in pin is a single point "
                     f"(QuestPOIBlob with one QuestPOIPoint: the client's own turn-in marker, not an area), the two "
                     f"were compared in world coordinates for {rt['compared']:,} quest records (faction variants "
                     f"included); {n:,} "
                     f"({100.0 * n / rt['compared']:.1f}%) were more than 50 yd apart, and for those the pin is shipped "
                     "and the wiki point is kept under `coord_source.replaces`. Whole zones can be off (The Ringing "
                     "Deeps: most wiki points sit about 4 map units east of the pins while the map itself is unchanged "
                     "between builds 12.1.0 and 12.1.5), so a stale wiki number is the usual cause.")
    for kind, label in (("npc_page_rows", "NPC / object page rows"), ("quest_page_rows", "quest page {{co}} rows")):
        e = cr.get(kind)
        if e:
            v = e.get("verdicts", {})
            lines.append(f"* Coordinate reading, {label} with a Blizzard position to compare (retail turn-in pins, "
                         f"flight points): {e['untagged_rows_with_evidence']:,} untagged rows; retail-map numbers "
                         f"{v.get('retail', 0):,}, Classic-map numbers {v.get('classic', 0):,}, either (the maps agree "
                         f"there) {v.get('either', 0):,}, more than 50 yd off both ways {v.get('conflict', 0):,}, no "
                         f"position inside the row's zone {v.get('no-evidence', 0):,}. Zones whose unchecked rows are "
                         f"read as Classic numbers: {', '.join(e['zones_read_as_classic']) or 'none'}.")
    for fl in flavors:
        ac = counts.get(fl, {}).get("addon_crosscheck")
        ps = counts.get(fl, {}).get("prerequisite_split", {})
        if ac:
            amb = ac.get("addon_only_ambiguous", 0)
            lines.append(f"* {fl}: the addon's own generator assigned {ac['addon_flavor_quests']:,} quests to this client; "
                         f"this dataset has all but {ac['addon_only']} of them ({amb} left out here as ambiguous ids), "
                         f"{ac['data_only']} extra apart from the world quests / callings / emissary quests the addon "
                         f"leaves out on purpose. Prerequisite ids match the addon's chain for "
                         f"{ac['prereq_same_ids_as_addon']:,} of {ac['prereq_quests']:,} quests that have one. The "
                         f"others differ for reasons checked by hand: this dataset applies an \"(optional)\" qualifier "
                         f"to every link it covers (\"A or B (both optional)\"); it reads {{{{quest|...}}}} links the "
                         f"addon's parser does not see; it does not follow a link to a page that lost its id to another "
                         f"page when the shipped quest is not open to the linking quest's faction "
                         f"({ps.get('prereq_link_to_other_page_of_id', 0)}); and a one-faction quest linking the other "
                         f"faction's quest is pointed at the same-named quest of its own faction "
                         f"({ps.get('prereq_other_faction_to_own_faction_page', 0)}) or, with none, left unresolved "
                         f"({ps.get('prereq_other_faction_dropped', 0)}). "
                         f"{ps.get('prereq_faction_merged', 0)} quests both factions take had one Alliance-only and one "
                         f"Horde-only prerequisite listed as if both were needed; they are one any-of group now.")
    lines += ["", "## What the gaps mean", "",
              "* The Warcraft Wiki is retail-first, and many pages still carry numbers read off the pre-Cataclysm map. "
              "Each untagged row is read on the map a Blizzard position for the same NPC agrees with; without one, "
              "by its zone's evidence (`read_by` `zone-default`), and the point is `confidence` low. On Classic "
              "clients a point carried over from a retail page is right only if the NPC did not move in Cataclysm or "
              "later; nothing shippable says which NPCs moved, so those points are medium at best. Era, TBC and "
              "Forever have no Blizzard quest coordinates to fall back on, so their located share is what the wiki "
              "gives.",
              "* Retail ends and objectives fall back to Blizzard's quest POI (QuestPOIBlob) when the wiki has no point. "
              "Retail starts never use the POI: the turn-in pin is not the quest giver.",
              "* MoP Classic's QuestPOIBlob carries no quest rows, so MoP has no DB2 fallback either.",
              "* `QuestV2 ids with no wiki quest page` are mostly hidden tracking quests; the rest are real quests "
              "nobody has written a wiki page for yet. A wiki page (or a correction here) adds them.",
              ""]
    C.write_if_changed(C.REPO / "docs" / "COVERAGE.md", "\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--no-corrections", action="store_true")
    ap.add_argument("--data", default=str(C.DATA))
    ap.add_argument("--corrections", default=str(C.CORRECTIONS))
    ap.add_argument("flavors", nargs="*")
    args = ap.parse_args()
    flavors = args.flavors or list(C.FLAVORS)
    bad = [f for f in flavors if f not in C.FLAVORS]
    if bad:
        sys.exit(f"unknown flavor(s) {bad}")
    rep = Report()
    corrections = [] if args.no_corrections else C.load_corrections(args.corrections)
    validate_corrections(corrections, rep)
    cov = {fl: Counter() for fl in flavors}
    for fl in flavors:
        validate_flavor(fl, rep, cov, corrections, args.data)
    meta_p = Path(args.data) / "meta.json"
    meta = C.load_json(meta_p) if meta_p.exists() else {}
    if not meta:
        rep.err("files", "data/meta.json missing")
    for fl in flavors:
        print(f"{fl:7} quests {cov[fl]['quests']:6,}  start located {cov[fl]['quests_start_located']:6,}  "
              f"end located {cov[fl]['quests_end_located']:6,}  npcs {cov[fl]['npcs']:6,}  "
              f"achievements {cov[fl]['achievements']:6,}  missions {cov[fl]['missions']:5,}")
    for w in rep.warnings:
        print("warning:", w)
    for e in rep.errors:
        print("ERROR:", e)
    summary = ", ".join(f"{lvl} {k}: {v}" for (lvl, k), v in sorted(rep.count.items()))
    print(f"{rep.n_errors()} errors; {summary or 'nothing to report'}")
    if args.coverage:
        if set(flavors) != set(C.FLAVORS):
            sys.exit("--coverage needs all flavors")
        write_coverage(cov, meta, flavors)
        print("wrote docs/COVERAGE.md and docs/coverage.csv")
    return 1 if rep.n_errors() else 0


if __name__ == "__main__":
    sys.exit(main())
