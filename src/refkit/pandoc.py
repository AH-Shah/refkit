"""Calls to the pandoc executable."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .errors import RefkitError


def require() -> None:
    if not shutil.which("pandoc"):
        raise RefkitError("pandoc not found on PATH; install pandoc 3.x from https://pandoc.org/installing.html")


def run(args: list, input: str | None = None) -> str:
    require()
    p = subprocess.run(["pandoc", *map(str, args)], input=input, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RefkitError(f"pandoc {' '.join(map(str, args))} failed: {p.stderr.strip() or 'exit code %d' % p.returncode}")
    return p.stdout


def latex_text(s: str) -> str:
    """LaTeX field -> plain Unicode, keeping the record's own capitalisation (pandoc's BibTeX reader would change it)."""
    out = run(["-f", "latex", "-t", "plain", "--wrap=none"], s).strip()
    return re.sub(r"\s+", " ", out.replace("{", "").replace("}", ""))


def bibtex_to_csl(bib: str) -> dict:
    items = json.loads(run(["-f", "bibtex", "-t", "csljson"], bib))
    if not items:
        raise ValueError("pandoc could not read the BibTeX entry")
    return items[0]


def cited_keys(manuscript: Path) -> list[str]:
    """Citation keys in the manuscript, in order of first appearance, as pandoc itself parses them."""
    ast = json.loads(run([manuscript, "-t", "json"]))
    keys = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Cite":
                keys.extend(c["citationId"] for c in node["c"][0])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(ast.get("blocks", []))
    return list(dict.fromkeys(keys))
