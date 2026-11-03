"""Import library/ALL.bib entries into the running Zotero desktop app (currently selected collection), skipping titles already present.
Requires Zotero 7: Settings > Advanced > 'Allow other applications on this computer to communicate with Zotero'."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from . import net, pandoc
from .bibtex import bibfield, first_bib
from .errors import FetchError, RefkitError
from .library import toks
from .project import Project, load_sources

ZOTERO = "http://127.0.0.1:23119"


def title_key(t: str) -> str:
    return " ".join(sorted(toks(t)))


def existing_titles() -> set:
    have, start = set(), 0
    while True:
        items = net.get_json(f"{ZOTERO}/api/users/0/items?format=json&limit=100&start={start}", tries=1)
        have |= {title_key((it.get("data") or {}).get("title", "")) for it in items}
        if len(items) < 100:
            return have
        start += 100


def zotero(p: Project) -> None:
    rows = load_sources(p.sources_tsv)
    try:
        net.get(f"{ZOTERO}/connector/ping", tries=1, timeout=5)
    except FetchError:
        raise RefkitError("Zotero desktop is not running (nothing answers on port 23119)") from None
    try:
        have = existing_titles()
    except FetchError:
        raise RefkitError("enable Zotero's local API (Settings > Advanced > 'Allow other applications on this computer to communicate "
                          "with Zotero') so refkit can skip entries already in the library") from None
    failed = []
    for r in rows:
        f = p.library / f"{r.key}.bib"
        if not f.exists():
            print(f"missing  {r.key} (run `refkit fetch`)")
            failed.append(r.key)
            continue
        bib = first_bib(f.read_text(encoding="utf-8"))
        if title_key(pandoc.latex_text(bibfield(bib, "title") or "")) in have:
            print(f"present  {r.key}")
            continue
        req = urllib.request.Request(f"{ZOTERO}/connector/import?session={uuid.uuid4().hex}", data=bib.encode(), method="POST",
                                     headers={"Content-Type": "application/x-bibtex", "X-Zotero-Connector-API-Version": "3"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                n = len(json.loads(resp.read() or b"[]"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            n = 0
            print(f"  {r.key}: {e}")
        print(f"{'imported' if n else 'FAILED  '} {r.key}")
        if not n:
            failed.append(r.key)
    if failed:
        raise RefkitError(f"not imported into Zotero: {', '.join(failed)}")
