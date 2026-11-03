"""Minimal BibTeX helpers: locate an entry in a page, read one field verbatim."""
from __future__ import annotations

import re

ENTRY_TYPES = ("article", "inproceedings", "conference", "misc", "book", "booklet", "inbook", "incollection", "techreport", "report",
               "online", "electronic", "www", "phdthesis", "mastersthesis", "thesis", "unpublished", "manual", "dataset", "software",
               "proceedings")
# '@type{' followed by a (possibly empty) citation key and a comma; avoids CSS rules such as '@media {' in web pages
ENTRY_RE = re.compile(r"@(" + "|".join(ENTRY_TYPES) + r")\s*\{\s*[^\s,{}]*\s*,", re.I)


def first_bib(text: str) -> str:
    """The first @type{...} entry in `text`, with balanced braces. Raises ValueError if there is none."""
    m = ENTRY_RE.search(text)
    if not m:
        raise ValueError("no BibTeX entry found")
    depth = 0
    for k in range(text.index("{", m.start()), len(text)):
        c = text[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():k + 1]
    raise ValueError("BibTeX entry has unbalanced braces")


def bibfield(bib: str, name: str) -> str | None:
    """Raw value of field `name` (without outer braces/quotes), or None."""
    m = re.search(rf"[\n,{{]\s*{re.escape(name)}\s*=\s*", bib, re.I)
    if not m or m.end() >= len(bib):
        return None
    k = m.end()
    q = bib[k]
    if q == '"':
        end = bib.find('"', k + 1)
        return bib[k + 1:end] if end != -1 else None
    if q != "{":
        v = re.match(r"[^,\n}]+", bib[k:])
        return v.group(0).strip() if v else None
    depth = 0
    for t in range(k, len(bib)):
        if bib[t] == "{":
            depth += 1
        elif bib[t] == "}":
            depth -= 1
            if depth == 0:
                return bib[k + 1:t]
    return None
