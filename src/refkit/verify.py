"""Verification sheet: every rendered reference (in the style's order) next to the official record it was built from -> VERIFY.md"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from . import pandoc
from .errors import RefkitError
from .library import md_cell
from .project import Project


class _Entries(HTMLParser):
    """Collects the text of each <div id="ref-KEY" class="csl-entry"> in pandoc's HTML output."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries, self._key, self._depth, self._buf = [], None, 0, []

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        a = dict(attrs)
        if self._key is None and (a.get("id") or "").startswith("ref-") and "csl-entry" in (a.get("class") or "").split():
            self._key, self._depth, self._buf = a["id"][4:], 1, []
        elif self._key is not None:
            self._depth += 1
            self._buf.append(" ")

    def handle_endtag(self, tag):
        if tag == "div" and self._key is not None:
            self._depth -= 1
            if self._depth == 0:
                self.entries.append((self._key, re.sub(r"\s+", " ", "".join(self._buf)).strip()))
                self._key = None

    def handle_data(self, data):
        if self._key is not None:
            self._buf.append(data)


def rendered_entries(manuscript: Path, references: Path, csl: Path) -> list:
    out = pandoc.run([manuscript, "--citeproc", "--bibliography", references, "--csl", csl, "-t", "html", "--wrap=none"])
    parser = _Entries()
    parser.feed(out)
    return parser.entries


def pick_csl(p: Project) -> Path:
    if p.csl:
        return p.require(p.csl, "pass an existing style with --csl")
    styles = sorted((p.root / "styles").glob("*.csl"))
    if len(styles) == 1:
        return styles[0]
    choices = ", ".join(str(s.relative_to(p.root)) for s in styles) or "none found in styles/"
    raise RefkitError(f"choose a citation style with --csl (or REFKIT_CSL); available: {choices}")


def verify(p: Project) -> None:
    p.require(p.manuscript, "set the manuscript with --manuscript or REFKIT_MANUSCRIPT")
    p.require(p.references, "run `refkit build` first")
    csl = pick_csl(p)
    entries = rendered_entries(p.manuscript, p.references, csl)
    if not entries:
        raise RefkitError("pandoc rendered no references: does the manuscript cite any keys from references.json?")
    src = {}
    for f in p.library.glob("*.bib"):
        m = re.search(r"^% source: (\S+)", f.read_text(encoding="utf-8"), re.M)
        if m:
            src[f.stem] = m.group(1)
    L = ["# Verification sheet", f"Style: `{csl.name}`. Compare each rendered entry with its official record (authors, title words, venue, "
         "volume, pages, year).",
         "House style applied to all: sentence-case titles (acronyms and proper nouns kept), conference entries without publisher, place or DOI.",
         "", "| # | rendered reference | official record | checked |", "|---|---|---|---|"]
    L += [f"| {n} | {md_cell(text)} | {f'[{k}]({src[k]})' if k in src else md_cell(k)} | [ ] |" for n, (k, text) in enumerate(entries, 1)]
    (p.root / "VERIFY.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"VERIFY.md: {len(entries)} references ({csl.name})")
