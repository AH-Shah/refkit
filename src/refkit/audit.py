"""Independent audit of every reference in references.json against an official record fetched now.

DOI -> Crossref (journal articles, preprints) or DataCite (Zenodo) plus doi.org handle resolution; arXiv -> arXiv API (+ journal_ref / DOI of a
published version); PMLR / ICLR / NeurIPS / JMLR / ACL / web pages -> the landing page (title, every author surname and the year must
appear). Checks title, every author surname in order, year, venue, volume / issue / pages where the record has them, and whether a
preprint has been published since. Output: AUDIT.md (one row per reference)."""
from __future__ import annotations

import difflib
import html
import json
import re
import time
import unicodedata
import urllib.parse

from . import net
from .errors import FetchError, NotFound, RefkitError
from .library import md_cell, year_of
from .project import Project


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", html.unescape(str(s or "")))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"<[^>]+>|\$[^$]*\$", " ", s).lower()).strip()


def sim(a, b) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def surname(s) -> str:
    parts = norm(s).split(" ")
    return parts[-1] if parts else ""


def ours(e: dict) -> dict:
    return dict(title=e.get("title", ""), fam=[surname(a.get("family") or a.get("literal", "")) for a in e.get("author", [])],
                year=year_of(e), venue=e.get("container-title", ""), vol=str(e.get("volume", "")), iss=str(e.get("issue", "")),
                page=str(e.get("page", "")).replace("–", "-"))


def fetch_or_none(url: str, accept: str | None = None):
    """Body, or None if the record does not exist (404). Other failures raise FetchError."""
    try:
        return net.get(url, accept)
    except NotFound:
        return None


def _parse_json(text: str, what: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise FetchError(f"{what}: response is not valid JSON") from None


def registry_record(doi: str) -> tuple[str, dict | None]:
    """(registry name, normalised record) from DataCite (Zenodo) or Crossref; record None if the registry has no such DOI."""
    if doi.startswith("10.5281/zenodo"):
        r = fetch_or_none(f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}")
        if not r:
            return "DataCite", None
        a = (_parse_json(r, "DataCite").get("data") or {}).get("attributes") or {}
        fam = [surname(c.get("familyName") or (c.get("name") or "").split(",")[0]) for c in a.get("creators") or []]
        return "DataCite", dict(title=((a.get("titles") or [{}])[0]).get("title", ""), fam=fam, years={a.get("publicationYear")} - {None},
                                venue=a.get("publisher", "") if isinstance(a.get("publisher"), str) else (a.get("publisher") or {}).get("name", ""),
                                vol="", iss="", page="", type=None, preprint_of=[])
    r = fetch_or_none(f"https://api.crossref.org/works/{net.quote_doi(doi)}")
    if not r:
        return "Crossref", None
    m = _parse_json(r, "Crossref").get("message") or {}
    years = {d["date-parts"][0][0] for k in ("published-print", "published-online", "issued", "posted")
             if (d := m.get(k)) and d.get("date-parts") and d["date-parts"][0] and d["date-parts"][0][0]}
    venue = (m.get("container-title") or [""])[0] or ((m.get("institution") or [{}])[0].get("name", ""))
    return "Crossref", dict(title=(m.get("title") or [""])[0], fam=[surname(a.get("family") or a.get("name", "")) for a in m.get("author", [])],
                            years=years, venue=venue, vol=str(m.get("volume", "")), iss=str(m.get("issue", "")),
                            page=str(m.get("page", "")).replace("–", "-"), type=m.get("type"), server=venue,
                            preprint_of=[x.get("id") for x in (m.get("relation") or {}).get("is-preprint-of", [])])


def audit_doi(e: dict, o: dict, doi: str, notes: list) -> tuple[str, bool]:
    ok = True
    hd = fetch_or_none(f"https://doi.org/api/handles/{net.quote_doi(doi)}")  # handle registry: responseCode 1 = registered
    if not hd or _parse_json(hd, "doi.org").get("responseCode") != 1:
        notes.append("DOI not registered")
        ok = False
    src, rec = registry_record(doi)
    if rec is None:
        notes.append("registry record not found")
        return src, False
    if rec["type"] == "posted-content":  # preprint: published since?
        pubs = []
        if doi.startswith("10.1101/") and rec["server"].lower() in ("biorxiv", "medrxiv"):
            j = fetch_or_none(f"https://api.biorxiv.org/pubs/{rec['server'].lower()}/{doi}")
            pubs = [c.get("published_doi") for c in (_parse_json(j, "bioRxiv API").get("collection", []) if j else [])]
        pubs = pubs or rec["preprint_of"]
        if pubs:
            notes.append(f"PUBLISHED VERSION EXISTS: {pubs}")
            ok = False
        else:
            notes.append("preprint, no published version")
    yr = o["year"] if o["year"] in rec["years"] else (min(rec["years"]) if rec["years"] else None)
    fam = rec["fam"]
    if sim(rec["title"], o["title"]) < .93:
        notes.append(f"title differs: record '{rec['title'][:80]}'")
        ok = False
    if fam and fam != o["fam"][:len(fam)] and fam[:len(o["fam"])] != o["fam"]:
        notes.append(f"authors differ: record {fam[:6]}... ours {o['fam'][:6]}")
        ok = False
    if fam and len(fam) != len(o["fam"]):
        notes.append(f"author count {len(o['fam'])} vs record {len(fam)}")
        ok = False
    if yr and o["year"] and int(yr) != int(o["year"]):
        notes.append(f"year {o['year']} vs record {yr}")
        ok = False
    ven = rec["venue"]
    if ven and o["venue"] and sim(ven, o["venue"]) < .8 and norm(o["venue"]) not in norm(ven) and norm(ven) not in norm(o["venue"]):
        notes.append(f"venue '{o['venue']}' vs record '{ven}'")
    for k in ("vol", "iss", "page"):
        if rec[k] and o[k] and rec[k] != o[k]:
            notes.append(f"{k} {o[k]} vs record {rec[k]}")
            ok = False
    return src, ok


def audit_arxiv(e: dict, o: dict, aid: str, notes: list) -> bool:
    x = fetch_or_none(f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(aid)}")
    ent = x.split("<entry>", 1)[1] if x and "<entry>" in x else ""
    t, pub = re.search(r"<title>(.*?)</title>", ent, re.S), re.search(r"<published>(\d{4})", ent)
    if not (t and pub):
        notes.append("arXiv record not found")
        return False
    ok, yr = True, int(pub.group(1))
    fam = [surname(n) for n in re.findall(r"<name>(.*?)</name>", ent)]
    if sim(t.group(1), o["title"]) < .93:
        notes.append(f"title differs: arXiv '{' '.join(t.group(1).split())[:80]}'")
        ok = False
    if fam != o["fam"]:
        notes.append(f"authors: arXiv {fam} ours {o['fam']}")
        ok = False
    jr = re.search(r"<arxiv:journal_ref[^>]*>(.*?)</arxiv:journal_ref>", ent, re.S)
    dd = re.search(r"<arxiv:doi[^>]*>(.*?)</arxiv:doi>", ent)
    if jr or dd:
        notes.append(f"arXiv lists publication: {(jr.group(1) if jr else '')} {(dd.group(1) if dd else '')}".strip())
    if e.get("type") == "article" and o["year"] != yr:
        notes.append(f"year {o['year']} vs arXiv {yr}")
        ok = False
    if e.get("type") != "article":
        notes.append(f"cited as {o['venue']} {o['year']} (arXiv posted {yr})")
    return ok


def landing_url(url: str) -> str:
    """Proceedings PDF links -> their abstract pages."""
    if "proceedings.iclr.cc" in url and url.endswith(".pdf"):
        url = re.sub(r"/file/([0-9a-f]+)-Paper-(\w+)\.pdf$", r"/hash/\1-Abstract-\2.html", url)
    if ("proceedings.neurips.cc" in url or "papers.nips.cc" in url) and url.endswith("-Paper.pdf"):
        url = re.sub(r"/file/([0-9a-f]+)-Paper\.pdf$", r"/hash/\1-Abstract.html", url)
    return url


def audit_page(o: dict, url: str, notes: list) -> bool:
    page = fetch_or_none(landing_url(url))
    if page is None:
        notes.append("landing page not found")
        return False
    ok, P = True, norm(page)
    if norm(o["title"]) not in P:
        notes.append("title not found on page")
        ok = False
    miss = [f for f in o["fam"] if f and f not in P]
    if miss:
        notes.append(f"surnames not on page: {miss}")
        ok = False
    if o["year"] and str(o["year"]) not in page:
        notes.append(f"year {o['year']} not on page")
        ok = False
    return ok


def audit_entry(e: dict) -> tuple[str, bool, list]:
    """(record checked against, OK?, notes) for one CSL-JSON item. Never raises: failures become CHECK notes."""
    notes = []
    o = ours(e)
    doi, url = (e.get("DOI") or "").lower(), e.get("URL") or ""
    if not doi and "doi.org/10." in url:
        doi = urllib.parse.unquote(url.split("doi.org/", 1)[1]).lower()
    try:
        if doi and not doi.startswith("10.48550"):
            src, ok = audit_doi(e, o, doi, notes)
        elif doi.startswith("10.48550") or "arxiv.org" in url.lower():
            src = "arXiv API"
            aid = re.sub(r"^10\.48550/arxiv\.", "", doi) if doi else re.sub(r"\.pdf$", "", url.rstrip("/").rsplit("/", 1)[-1])
            ok = audit_arxiv(e, o, aid, notes)
        elif url:
            src, ok = "landing page", audit_page(o, url, notes)
        else:
            src, ok = "-", False
            notes.append("no DOI or URL to check against")
    except FetchError as ex:
        return "-", False, notes + [f"could not retrieve record: {ex}"]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as ex:
        return "-", False, notes + [f"unexpected record format ({type(ex).__name__}: {ex})"]
    return src, ok, notes


def audit(p: Project) -> bool:
    """Write AUDIT.md; True if every reference is OK."""
    p.require(p.references, "run `refkit build` first")
    try:
        refs = json.loads(p.references.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        raise RefkitError(f"{p.references} is not valid JSON ({ex}); run `refkit build` again") from None
    rows, bad = [], 0
    for e in refs:
        src, ok, notes = audit_entry(e)
        bad += not ok
        rows.append(f"| {md_cell(e.get('id', '?'))} | {src} | {'OK' if ok else '**CHECK**'} | {md_cell('; '.join(notes) or '-')} |")
        print(f"{'OK   ' if ok else 'CHECK'}  {e.get('id', '?')}  {'; '.join(notes)[:200]}", flush=True)
    summary = f"{len(refs) - bad} of {len(refs)} OK"
    (p.root / "AUDIT.md").write_text(f"# Reference audit {time.strftime('%Y-%m-%d %H:%M')}\n\n{summary}\n\n| key | record | status | notes |\n"
                                     "|---|---|---|---|\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"{summary} -> {p.root / 'AUDIT.md'}")
    return bad == 0
