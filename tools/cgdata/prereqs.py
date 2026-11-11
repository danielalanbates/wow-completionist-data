# wow-completionist-data :: tools/cgdata/prereqs.py
# Copyright (c) 2026 Daniel Bates. All rights reserved.
# Code licence: PolyForm Noncommercial 1.0.0 + commercial rider (see LICENSE). Data licence: see LICENSE-DATA.
"""Split a Warcraft Wiki {{Questbox}} `previous` field into required / any-of / breadcrumb / optional prerequisites,
and detect a quest page that calls itself a breadcrumb.

The wiki has no structured prerequisite field: `previous` is free wikitext.  What the text supports (measured over
21,252 quest pages with a `previous` field, 2026-11-10):

* 18,772 list one quest.  2,480 list several, joined by ", " / " and " / "&" (all of them), " or " / " / " /
  "one of" / a {{Alliance}} vs {{Horde}} pair (any one of them), or only by line breaks (ambiguous: read as
  all of them, and the record says basis "list").
* A parenthesis right after a link qualifies it: "(optional)" 173 pages, "(breadcrumb)" / "(optional breadcrumb)",
  "(required)", "(in-progress)" (the quest only has to be in your log).  "(both optional)" or a plural
  ("optional breadcrumbs") covers every link it follows.
* 168 quest pages say in their lead sentence that the quest is a breadcrumb ("'''X''' is an optional breadcrumb
  to ...").  A prerequisite that is such a page is a breadcrumb, not a requirement: in the game a breadcrumb only
  points you to the next quest and is not needed for it.

Link titles are normalised the way the addon's tools/wiki/wikitext.py does (same author, same rules).
"""
import html
import re

RE_LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
NON_ARTICLE = ("file:", "image:", "category:", "media:", "wikipedia:", "wowpedia:", "user:", "template:", "special:",
               "help:", "warcraft wiki:", "w:", "wp:")
LANG = re.compile(r"^[a-z]{2}(?:-[a-z]+)?:")
LIST_TEMPLATES = re.compile(r"^\s*(plainlist|ubl|unbulleted list|flatlist)\s*(\||$)", re.I)
QUAL = re.compile(r"^\s*(?:'{2,3}\s*)?\(([^()]*)\)\s*(?:'{2,3})?")


def norm_title(t):
    t = html.unescape(t or "").replace("_", " ").split("#", 1)[0].strip()
    t = re.sub(r"\s+", " ", t)
    if t.startswith(":"):
        t = t[1:].strip()
    return t[:1].upper() + t[1:] if t else t


def _templates(text):
    """yield (start, end, inner) of top-level balanced {{...}}"""
    i, n = 0, len(text)
    while True:
        i = text.find("{{", i)
        if i < 0:
            return
        j, depth = i, 0
        while j < n - 1:
            two = text[j:j + 2]
            if two == "{{":
                depth += 1
                j += 2
            elif two == "}}":
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        if depth != 0:
            return
        yield i, j, text[i + 2:j - 2]
        i = j


def _split_top(inner):
    parts, buf, dt, dl, k = [], [], 0, 0, 0
    while k < len(inner):
        two = inner[k:k + 2]
        if two in ("{{", "}}", "[[", "]]"):
            dt += {"{{": 1, "}}": -1}.get(two, 0)
            dl += {"[[": 1, "]]": -1}.get(two, 0)
            buf.append(two)
            k += 2
            continue
        if inner[k] == "|" and dt == 0 and dl == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(inner[k])
        k += 1
    parts.append("".join(buf))
    return parts


def _prepare(field):
    """list templates -> their items on separate lines; {{Alliance}}/{{Horde}} -> markers; NPC-style link templates
    -> links; every other template dropped (badges such as {{Forever-inline}}, {{rep|...}})"""
    f = re.sub(r"<!--.*?-->", "", field or "", flags=re.S)
    f = re.sub(r"<br\s*/?>", "\n", f, flags=re.I)
    out, pos = [], 0
    for s, e, inner in list(_templates(f)):
        out.append(f[pos:s])
        name = re.split(r"[|\n]", inner, maxsplit=1)[0].strip().lower()
        if LIST_TEMPLATES.match(inner):
            items = [p.strip() for p in _split_top(inner)[1:] if "=" not in p.split("[[")[0]]
            out.append("\n" + "\n".join(_prepare(p) for p in items) + "\n")
        elif name in ("alliance", "alliance-inline", "alliance icon"):
            out.append(" \x01A ")
        elif name in ("horde", "horde-inline", "horde icon"):
            out.append(" \x01H ")
        elif name in ("npc", "au", "quest", "questlong"):
            vals = [p.strip() for p in _split_top(inner)[1:] if p.strip() and "=" not in p]
            out.append(f"[[{vals[-1]}]]" if vals else "")
        else:
            out.append(" ")
        pos = e
    out.append(f[pos:])
    return "".join(out)


def _class_of(q):
    q = (q or "").lower()
    if "breadcrumb" in q:
        return "breadcrumb"
    if "optional" in q:
        return "optional"
    if "in-progress" in q or "in progress" in q or "active" in q:
        return "in_progress"
    if "required" in q:
        return "required"
    return None


def parse_previous(field):
    """-> {"groups": [{"titles": [(title, faction)], "class": str}], "basis": str, "text": str}
    groups are ANDed; the titles inside one group are alternatives (any one of them).  class is one of
    required / breadcrumb / optional / in_progress.  basis: none / single / explicit / list."""
    f = _prepare(field)
    links, seps, pos = [], [], 0
    for m in RE_LINK.finditer(f):
        tgt = m.group(1).strip()
        low = tgt.lower().lstrip(":")
        if low.startswith(NON_ARTICLE) or LANG.match(low):
            continue
        seps.append(f[pos:m.start()])
        links.append(norm_title(tgt))
        pos = m.end()
    seps.append(f[pos:])
    plain = re.sub(r"\s+", " ", re.sub(r"\x01[AH]|<[^>]+>|'{2,}|\[\[|\]\]", " ", f.replace("|", " "))).strip()
    if not links:
        return {"groups": [], "basis": "none", "text": plain}
    # faction marker and qualifier per link
    fac, qual, cur = [], [], ""
    for i, t in enumerate(links):
        before = seps[i]
        if re.search(r"<br\s*/?>|\n", before, re.I):
            cur = ""
        mk = re.findall(r"\x01([AH])", before)
        if mk:
            cur = "Alliance" if mk[-1] == "A" else "Horde"
        fac.append(cur)
        m = QUAL.match(seps[i + 1])
        qual.append(m.group(1).strip() if m else "")
    # separators between consecutive links, qualifiers removed
    kinds, outside = [], []
    for i in range(1, len(links)):
        s = QUAL.sub("", seps[i], count=1)
        outside.append(s)
        low = s.lower()
        if re.search(r"\bor\b|/", low) or (fac[i - 1] and fac[i] and fac[i - 1] != fac[i]):
            kinds.append("or")
        elif re.search(r",|\band\b|&", low):
            kinds.append("and")
        else:
            kinds.append("list")
    all_text = " ".join([seps[0]] + outside + [QUAL.sub("", seps[-1], count=1)]).lower()
    if re.search(r"\b(one of|either|any of)\b", all_text) or (
            re.search(r"\bor\b", all_text) and not re.search(r"\band\b|&", all_text)):
        kinds = ["or" if k in ("and", "list") else k for k in kinds]
    # groups: runs joined by "or"
    groups, cur_g = [], [0]
    for i, k in enumerate(kinds, 1):
        if k == "or":
            cur_g.append(i)
        else:
            groups.append(cur_g)
            cur_g = [i]
    groups.append(cur_g)
    cls = [_class_of(q) for q in qual]
    # a qualifier that names several links ("both optional", "optional breadcrumbs") covers all unqualified links;
    # a qualifier on the last link of an "or" group covers that group
    for i, q in enumerate(qual):
        ql = q.lower()
        if cls[i] and re.search(r"\b(both|all)\b|breadcrumbs|optionals", ql):
            for j in range(len(links)):
                if cls[j] is None:
                    cls[j] = cls[i]
    for g in groups:
        last = cls[g[-1]]
        if last and len(g) > 1:
            for j in g:
                if cls[j] is None:
                    cls[j] = last
    out = []
    for g in groups:
        by_cls = {}
        for j in g:
            by_cls.setdefault(cls[j] or "required", []).append((links[j], fac[j]))
        for c, titles in by_cls.items():
            out.append({"titles": titles, "class": c})
    basis = "single" if len(links) == 1 else ("list" if "list" in kinds else "explicit")
    return {"groups": out, "basis": basis, "text": plain}


RE_FILE = re.compile(r"\[\[(?:File|Image):(?:[^\[\]]|\[\[[^\[\]]*\]\])*\]\]", re.I)
RE_SELF_BREADCRUMB = re.compile(
    r"'''[^']+(?:'[^']+)*'''\s*(?:\([^)]*\)\s*)?(?:is|was)\s+(?:(?:a|an|the)\s+)?((?:[\w'\"-]+\s+){0,5}?)"
    r"\[{0,2}breadcrumb", re.I)


def lead_breadcrumb(lead):
    """the page's lead text (after the questbox, before the first heading) -> "optional" / "yes" / None"""
    t = re.sub(r"<!--.*?-->", "", lead or "", flags=re.S)
    t = RE_FILE.sub(" ", t)
    for _ in range(4):
        t = re.sub(r"\{\{[^{}]*\}\}", " ", t)
    t = re.sub(r"\s+", " ", t).strip()[:700]
    m = RE_SELF_BREADCRUMB.search(t)
    if not m:
        return None
    return "optional" if "optional" in (m.group(1) or "").lower() else "yes"
