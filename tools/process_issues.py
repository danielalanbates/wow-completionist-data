#!/usr/bin/env python3
# wow-completionist-data :: tools/process_issues.py
# Copyright (c) 2026 Daniel Bates. All rights reserved. PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
# https://batesai.org - help@batesai.org
"""Merge open Location contribution issues on the maintainer's own machine (the project uses no GitHub compute).

    python3 tools/process_issues.py            # list the open contribution issues, change nothing
    python3 tools/process_issues.py --apply    # merge each one, commit, push, post the report, close the issue

Each issue goes through tools/contrib_issue.py exactly as before: the issue text reaches it through the environment
(BODY, WHO, ASSOC), never through a command line. One commit per issue, "Contributions: issue #N". Needs `gh` logged
in with write access, and a clean `contributions/` tree. Run it by hand; it is not meant for a schedule.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "danielalanbates/wow-completionist-data"


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=True, **kw).stdout


def open_issues():
    out = run(["gh", "api", "--paginate", f"repos/{REPO}/issues?labels=contribution&state=open&per_page=100"])
    issues = []
    for chunk in out.replace("][", "]\n[").splitlines():
        if chunk.strip():
            issues += [i for i in json.loads(chunk) if "pull_request" not in i]
    return issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="merge, commit, push, comment and close")
    ap.add_argument("--no-push", action="store_true", help="with --apply: commit locally, do not push, comment or close")
    a = ap.parse_args()
    issues = open_issues()
    if not issues:
        print("No open contribution issues.")
        return 0
    for i in issues:
        print(f"#{i['number']}  {i['user']['login']} ({i['author_association']})  {i['title']}")
    if not a.apply:
        print(f"\n{len(issues)} open. Re-run with --apply to merge them.")
        return 0
    if run(["git", "status", "--porcelain", "--", "contributions"]).strip():
        print("contributions/ has uncommitted changes; commit or discard them first.")
        return 1
    for i in issues:
        n = i["number"]
        env = dict(os.environ, BODY=i.get("body") or "", WHO=i["user"]["login"], ASSOC=i["author_association"])
        r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "contrib_issue.py")], cwd=ROOT, env=env,
                           text=True, capture_output=True)
        report = (r.stdout + r.stderr).strip() or "Nothing to merge."
        print(f"\n== #{n}\n{report}")
        run(["git", "add", "contributions"])
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
            run(["git", "commit", "-m", f"Contributions: issue #{n}"])
        if a.no_push:
            continue
        run(["git", "push"])
        run(["gh", "issue", "comment", str(n), "--repo", REPO, "--body-file", "-"], input=report)
        run(["gh", "issue", "close", str(n), "--repo", REPO])
    return 0


if __name__ == "__main__":
    sys.exit(main())
