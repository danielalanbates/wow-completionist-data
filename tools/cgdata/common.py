# wow-completionist-data :: tools/cgdata/common.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Paths, the bucketed JSON file format, JSON Pointer helpers and the corrections overlay.

Bucket files (data/<flavor>/<kind>/<bucket>.json) hold one record per line inside a normal JSON document, so a
change to one record is a one-line diff and any JSON parser can read the file:

    {
     "flavor": "era",
     "kind": "quests",
     "bucket": "000000-000999",
     "count": 2,
     "records": [
    {"id":1,...},
    {"id":2,...}
     ]
    }
"""
import copy
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
CORRECTIONS = REPO / "corrections"
BUILD = REPO / "build"
# extra Blizzard DB2 tables fetched by tools/fetch_db2.py (gitignored)
CACHE_DB2 = REPO / "cache" / "db2"
FLAVORS = ("era", "tbc", "mop", "retail", "forever")
FLAVOR_NAMES = {
    "era": "Classic Era (1.15.x)",
    "tbc": "Burning Crusade Anniversary (2.5.x)",
    "mop": "Mists of Pandaria Classic (5.5.x)",
    "retail": "Retail (12.x)",
    "forever": "WoW Forever (1.60.x)",
}
# kind -> (key field, bucket width, digits).  npcs/objects are keyed by their wiki page title ("key") and bucketed by
# their first in-game id; records without an id go to "no-id".
KINDS = {
    "quests": ("id", 1000, 6),
    "achievements": ("id", 1000, 6),
    "missions": ("id", 1000, 6),
    "npcs": ("key", 10000, 7),
    "objects": ("key", 10000, 7),
}
# the singular names used in corrections files
KIND_ALIASES = {"quest": "quests", "achievement": "achievements", "mission": "missions", "npc": "npcs",
                "object": "objects"}
SCHEMA_VERSION = 2


def bucket_of(kind, rec):
    _key, width, digits = KINDS[kind]
    if kind in ("npcs", "objects"):
        ids = rec.get("ids") or []
        if not ids:
            return "no-id"
        n = int(ids[0])
    else:
        n = int(rec["id"])
    lo = n // width * width
    return f"{lo:0{digits}d}-{lo + width - 1:0{digits}d}"


def record_key(kind, rec):
    return rec[KINDS[kind][0]]


def sort_key(kind, rec):
    if kind in ("npcs", "objects"):
        ids = rec.get("ids") or []
        return (0 if ids else 1, int(ids[0]) if ids else 0, rec["key"])
    return (int(rec["id"]),)


def dumps_record(rec):
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))


def render_bucket(flavor, kind, bucket, records):
    lines = ["{", f' "flavor": {json.dumps(flavor)},', f' "kind": {json.dumps(kind)},',
             f' "bucket": {json.dumps(bucket)},', f' "count": {len(records)},', ' "records": [']
    for i, r in enumerate(records):
        lines.append(dumps_record(r) + ("," if i < len(records) - 1 else ""))
    lines += [" ]", "}"]
    return "\n".join(lines) + "\n"


def write_if_changed(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def write_kind(flavor, kind, records, data_dir=DATA):
    """write all records of one kind for one flavor into bucket files; remove buckets that are no longer used.
    Returns {bucket: count}."""
    out_dir = Path(data_dir) / flavor / kind
    buckets = {}
    for r in records:
        buckets.setdefault(bucket_of(kind, r), []).append(r)
    for b in buckets:
        buckets[b].sort(key=lambda r: sort_key(kind, r))
        write_if_changed(out_dir / f"{b}.json", render_bucket(flavor, kind, b, buckets[b]))
    if out_dir.exists():
        for p in out_dir.glob("*.json"):
            if p.stem not in buckets:
                p.unlink()
    return {b: len(v) for b, v in sorted(buckets.items())}


def bucket_files(flavor, kind, data_dir=DATA):
    d = Path(data_dir) / flavor / kind
    return sorted(d.glob("*.json")) if d.exists() else []


def iter_records(flavor, kind, data_dir=DATA):
    """yield (path, record) one bucket file at a time (keeps memory flat)"""
    for p in bucket_files(flavor, kind, data_dir):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for r in doc.get("records", []):
            yield p, r


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(obj):
    """stable, readable JSON for small files (meta, maps, db2 lists)"""
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def render_id_list(header, ids, per_line=20):
    """a JSON document with a long integer list wrapped `per_line` ids per line (diff-friendly)"""
    lines = ["{"]
    for k, v in header.items():
        lines.append(f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)},")
    lines.append(' "ids": [')
    chunks = [ids[i:i + per_line] for i in range(0, len(ids), per_line)]
    for i, ch in enumerate(chunks):
        lines.append("  " + ",".join(str(x) for x in ch) + ("," if i < len(chunks) - 1 else ""))
    lines += [" ]", "}"]
    return "\n".join(lines) + "\n"


# ---- JSON Pointer (RFC 6901) ----------------------------------------------------------------------------
def pointer_parts(ptr):
    if ptr in ("", None):
        return []
    if not ptr.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/': {ptr!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in ptr[1:].split("/")]


def _step(node, part, ptr):
    if isinstance(node, list):
        if not re.fullmatch(r"0|[1-9]\d*", part) or int(part) >= len(node):
            raise KeyError(f"{ptr}: no array index {part!r}")
        return node[int(part)]
    if isinstance(node, dict):
        if part not in node:
            raise KeyError(f"{ptr}: no member {part!r}")
        return node[part]
    raise KeyError(f"{ptr}: cannot descend into a {type(node).__name__}")


def pointer_get(doc, ptr):
    node = doc
    for part in pointer_parts(ptr):
        node = _step(node, part, ptr)
    return node


def pointer_apply(doc, op, ptr, value=None):
    """apply one operation in place.  op: "set" (replace an existing member/element, or create a member of an
    existing object), "add" (RFC 6902 add: insert into an array at an index or '-' = append, or add an object
    member), "remove".  Returns the parent container and the final key (for callers that annotate siblings)."""
    parts = pointer_parts(ptr)
    if not parts:
        raise ValueError("the whole record cannot be patched in place; use an empty path at the record level")
    parent = doc
    for part in parts[:-1]:
        parent = _step(parent, part, ptr)
    last = parts[-1]
    if isinstance(parent, list):
        if op == "add":
            if last == "-":
                parent.append(copy.deepcopy(value))
                return parent, len(parent) - 1
            if not re.fullmatch(r"0|[1-9]\d*", last) or int(last) > len(parent):
                raise KeyError(f"{ptr}: bad array index {last!r}")
            parent.insert(int(last), copy.deepcopy(value))
            return parent, int(last)
        if not re.fullmatch(r"0|[1-9]\d*", last) or int(last) >= len(parent):
            raise KeyError(f"{ptr}: no array index {last!r}")
        if op == "set":
            parent[int(last)] = copy.deepcopy(value)
        elif op == "remove":
            parent.pop(int(last))
        else:
            raise ValueError(f"unknown op {op!r}")
        return parent, int(last)
    if isinstance(parent, dict):
        if op in ("set", "add"):
            parent[last] = copy.deepcopy(value)
        elif op == "remove":
            if last not in parent:
                raise KeyError(f"{ptr}: no member {last!r}")
            del parent[last]
        else:
            raise ValueError(f"unknown op {op!r}")
        return parent, last
    raise KeyError(f"{ptr}: parent is a {type(parent).__name__}")


# ---- corrections overlay ---------------------------------------------------------------------------------
CORRECTION_FIELDS = {"id", "flavor", "kind", "key", "op", "path", "value", "reason", "evidence"}


def load_corrections(corr_dir=CORRECTIONS):
    """[(file name, index, correction dict)] in file-name order, then file order.  Files whose name starts with
    '_' (examples, drafts) are skipped."""
    out = []
    d = Path(corr_dir)
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("_"):
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        for i, c in enumerate(doc.get("corrections", [])):
            out.append((p.name, i, c))
    return out


def correction_problems(c):
    """static checks of one correction (before it meets the data) -> [message]"""
    probs = []
    extra = set(c) - CORRECTION_FIELDS
    if extra:
        probs.append(f"unknown fields {sorted(extra)}")
    for f in ("id", "flavor", "kind", "key", "op", "reason"):
        if c.get(f) in (None, ""):
            probs.append(f"missing {f!r}")
    if c.get("flavor") not in FLAVORS + ("all",):
        probs.append(f"flavor must be one of {list(FLAVORS) + ['all']}")
    if KIND_ALIASES.get(c.get("kind"), c.get("kind")) not in KINDS:
        probs.append(f"kind must be one of {sorted(KIND_ALIASES)}")
    if c.get("op") not in ("set", "add", "remove"):
        probs.append("op must be set, add or remove")
    if c.get("op") in ("set", "add") and "value" not in c:
        probs.append("set/add need a value")
    try:
        pointer_parts(c.get("path", ""))
    except ValueError as e:
        probs.append(str(e))
    return probs


def corrections_for(flavor, kind, corrections):
    for fname, idx, c in corrections:
        if c.get("flavor") not in (flavor, "all"):
            continue
        if KIND_ALIASES.get(c.get("kind"), c.get("kind")) != kind:
            continue
        yield fname, idx, c


def apply_corrections(flavor, kind, records, corrections, strict=True):
    """records: {key: record} for one flavor/kind, changed in place.  Returns [(correction id, key, status,
    message)].  A correction with an empty path adds (op add) or deletes (op remove) a whole record.  Every touched
    record lists the correction ids it received in record["corrections"].  A correction that sets an endpoint's or
    objective's coordinates ("…/coords") marks the sibling coord_source as {"type": "correction", ...},
    exact_version true and confidence "high"; on an NPC or object record each new point gets exact_version true,
    via "correction", confidence "high" and correction <id> unless the correction gives them."""
    log = []
    for fname, idx, c in corrections_for(flavor, kind, corrections):
        cid = c.get("id") or f"{fname}#{idx}"
        key = c.get("key")
        path = c.get("path", "")
        try:
            probs = correction_problems(c)
            if probs:
                raise ValueError("; ".join(probs))
            if path == "":
                if c["op"] == "add":
                    rec = copy.deepcopy(c["value"])
                    if record_key(kind, rec) != key:
                        raise ValueError("the new record's key does not match 'key'")
                    if key in records:
                        if c.get("flavor") == "all":
                            log.append((cid, key, "skipped", f"{flavor}: record {key!r} already exists"))
                            continue
                        raise ValueError("record already exists")
                    rec.setdefault("corrections", []).append(cid)
                    records[key] = rec
                elif c["op"] == "remove":
                    if key not in records:
                        raise KeyError(f"no {kind} record {key!r}")
                    del records[key]
                else:
                    raise ValueError("a whole record can only be added or removed")
                log.append((cid, key, "applied", ""))
                continue
            if key not in records:
                if c.get("flavor") == "all":
                    log.append((cid, key, "skipped", f"{flavor}: no record {key!r}"))
                    continue
                raise KeyError(f"no {kind} record {key!r}")
            rec = records[key]
            trial = copy.deepcopy(rec)
            before = [json.dumps(p, sort_keys=True) for p in rec.get("coords", [])] \
                if kind in ("npcs", "objects") else []
            parent, last = pointer_apply(trial, c["op"], path, c.get("value"))
            if kind in ("npcs", "objects"):
                if pointer_parts(path)[:1] == ["coords"] and c["op"] in ("set", "add"):
                    for pt in trial.get("coords", []):
                        if isinstance(pt, dict) and json.dumps(pt, sort_keys=True) not in before:
                            pt.setdefault("exact_version", True)
                            pt.setdefault("via", "correction")
                            pt.setdefault("confidence", "high")
                            pt.setdefault("correction", cid)
            elif last == "coords" and isinstance(parent, dict) and c["op"] in ("set", "add"):
                parent["coord_source"] = {"type": "correction", "correction": cid}
                parent["exact_version"] = True
                parent["confidence"] = "high"
            trial.setdefault("corrections", [])
            if cid not in trial["corrections"]:
                trial["corrections"].append(cid)
            records[key] = trial
            log.append((cid, key, "applied", ""))
        except (KeyError, ValueError, TypeError) as e:
            if strict:
                raise ValueError(f"correction {cid} ({fname}): {e}") from None
            log.append((cid, key, "error", str(e)))
    return log
