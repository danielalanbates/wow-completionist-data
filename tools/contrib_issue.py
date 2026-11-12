#!/usr/bin/env python3
# wow-completionist-data :: tools/contrib_issue.py
# Copyright (c) 2026 Daniel Bates. All rights reserved. PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE).
# https://batesai.org - help@batesai.org
"""Run by .github/workflows/contributions.yml: merge the contribution in an issue.

Reads the issue from the environment (BODY, WHO, ASSOC), never from the command line, so nothing a submitter writes
is ever part of a shell command. A long export can be attached as a .txt file: only links to GitHub's own issue
attachments are followed, at most three, each at most 2 MB. Prints the report that is posted back on the issue.
"""
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contrib  # noqa: E402

ATTACH = re.compile(r"https://github\.com/(?:user-attachments/files/\d+/[\w.\-]+\.txt|[\w.\-]+/[\w.\-]+/files/\d+/[\w.\-]+\.txt)")


def main():
    body = os.environ.get("BODY", "")
    who = os.environ.get("WHO", "").strip()
    trusted = os.environ.get("ASSOC", "") in ("OWNER", "MEMBER", "COLLABORATOR")
    if not who:
        print("No author on this issue; nothing merged.")
        return 1
    text = body
    for url in ATTACH.findall(body)[:3]:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "wow-completionist-data"}), timeout=30) as r:
                text += "\n" + r.read(contrib.MAX_BYTES + 1).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print(f"note: could not read an attached file ({type(e).__name__})")
    lines = []
    n = contrib.add(text, who, trusted, out=lines.append)
    if n:
        contrib.rebuild(out=lines.append)
        print("Thank you. Your contribution was merged.\n")
    else:
        print("Nothing in this issue could be merged. Paste the text from the addon's Contribute export, or attach it as a .txt file.\n")
    shown = [ln for ln in lines if not ln.startswith("note: line")]
    notes = len(lines) - len(shown)
    print("```")
    print("\n".join(shown))
    if notes:
        print(f"{notes} line(s) were not in the export format and were skipped")
    print("```")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
