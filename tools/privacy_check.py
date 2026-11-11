#!/usr/bin/env python3
# wow-completionist-data :: tools/privacy_check.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Pre-commit safety gate for every tracked file (or every file, before the first commit).

    python3 tools/privacy_check.py          # exit 1 and list the hits when anything is found

Fails on: e-mail addresses other than the project's own help address; absolute home-directory paths; strings
shaped like credentials (API keys, tokens, private keys); and words on a private deny list (personal account /
character names and the name of a product this project must not reference).  The deny list is stored as
SHA-256 hashes of lower-case words so this file does not spell the words out.
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOWED_EMAILS = {"help@batesai.org"}
DENY_HASHES = {
    "ec9eefd3b3811601e900635d5b02d34c6f13aed885de2fe3a748f6d497354b1a",
    "49f436494c88dfafb93cc5552b3f2d727df6588c8e4d669abf2b7353cd0ac04f",
}
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_U = "Us" + "ers"   # split so this file does not match its own pattern
RE_HOME = re.compile(r"(?:/" + _U + r"/|/home/[a-z]|[A-Za-z]:\\" + _U + r"\\)")
RE_SECRET = re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|"
                       r"xox[abpr]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AIza[0-9A-Za-z_-]{30,}|"
                       r"(?i:(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]))")
RE_WORD = re.compile(r"[a-z0-9]+")
SKIP_SUFFIX = {".sqlite", ".png", ".jpg", ".gif", ".zip"}


def files():
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout.splitlines()
        return [REPO / p for p in out if p]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts and "build" not in p.parts]


def scan(paths):
    hits = []
    for p in paths:
        if p.suffix in SKIP_SUFFIX or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(REPO)
        for m in RE_EMAIL.finditer(text):
            if m.group(0).lower() not in ALLOWED_EMAILS:
                hits.append(f"{rel}: e-mail address {m.group(0)!r}")
        for m in RE_HOME.finditer(text):
            hits.append(f"{rel}: home-directory path near {text[max(0, m.start() - 20):m.end() + 20]!r}")
        for m in RE_SECRET.finditer(text):
            hits.append(f"{rel}: credential-shaped string {m.group(0)[:12]!r}...")
        words = set(RE_WORD.findall(text.lower()))
        for w in words:
            if hashlib.sha256(w.encode()).hexdigest() in DENY_HASHES:
                hits.append(f"{rel}: a word on the private deny list")
                break
    return hits


def main():
    paths = files()
    hits = scan(paths)
    for h in hits:
        print("FAIL", h)
    print(f"privacy check: {len(paths)} files, {len(hits)} problems")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
