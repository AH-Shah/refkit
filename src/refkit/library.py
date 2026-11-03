"""fetch: download each official citation record verbatim -> library/<key>.bib (+ <key>.csl.json for DOIs)
build: house style + overrides -> references.json (CSL-JSON) and library/ALL.bib
check: published versions of preprints, an independent OpenAlex cross-check, odd Unicode, cited vs listed keys -> REPORT.md"""
from __future__ import annotations

import datetime
import html
import json
import re
import sys
import unicodedata
import urllib.parse

from . import net, pandoc
from .bibtex import bibfield, first_bib
from .errors import FetchError, RefkitError
from .project import Project, Source, load_proper_nouns, load_sources

CSL_JSON = "application/vnd.citationstyles.csl+json"


# ---------------------------------------------------------------- fetch

def record_url(r: Source) -> tuple[str, str | None]:
    """(URL of the official citation file, Accept header)."""
    if r.src == "doi":
        return f"https://doi.org/{net.quote_doi(r.id)}", "application/x-bibtex"
    if r.src == "arxiv":
        return f"https://arxiv.org/bibtex/{r.id}", None
    if r.src == "pmlr":
        return f"https://proceedings.mlr.press/{r.id}.html", None
    if r.src == "iclr":
        y, h = r.id.split("/")
        return f"https://proceedings.iclr.cc/paper_files/paper/{y}/file/{h}-Bibtex.bib", None
    if r.src == "neurips":
        y, h = r.id.split("/")
        return f"https://papers.nips.cc/paper_files/paper/{y}/file/{h}-Bibtex.bib", None
    if r.src == "acl":
        return f"https://aclanthology.org/{r.id}.bib", None
    if r.src == "jmlr":
        return f"https://jmlr.org/papers/{r.id}.bib", None
    if r.src == "html":
        return r.id, None
    raise ValueError(f"unknown source {r.src}")


def fetch_one(r: Source) -> tuple[str, str, str | None]:
    """(url, BibTeX entry, CSL-JSON text for DOIs or None)."""
    url, accept = record_url(r)
    text = net.get(url, accept)
    if r.src in ("pmlr", "html"):
        text = html.unescape(text).replace(" ", " ")  # web pages indent BibTeX with non-breaking spaces
    try:
        bib = first_bib(text)
    except ValueError as e:
        raise FetchError(f"{url}: {e}") from None
    csl = None
    if r.src == "doi":
        csl = net.get(url, CSL_JSON)
        try:
            json.loads(csl)
        except json.JSONDecodeError:
            raise FetchError(f"{url}: the registry did not return CSL-JSON") from None
    return url, bib, csl


def fetch(p: Project, refresh: bool = False) -> None:
    rows = load_sources(p.sources_tsv)
    p.library.mkdir(parents=True, exist_ok=True)
    failed = []
    for r in rows:
        bibf, cslf = p.library / f"{r.key}.bib", p.library / f"{r.key}.csl.json"
        if not refresh and bibf.exists() and (r.src != "doi" or cslf.exists()):
            continue
        try:
            url, bib, csl = fetch_one(r)
        except FetchError as e:
            failed.append(r.key)
            print(f"FAILED   {r.key}: {e}", file=sys.stderr, flush=True)
            continue
        bibf.write_text(f"% source: {url}\n% fetched: {datetime.date.today().isoformat()}\n{bib}\n", encoding="utf-8")
        if csl is not None:
            cslf.write_text(csl, encoding="utf-8")
        elif cslf.exists():
            cslf.unlink()  # source changed from doi to something else
        print(f"fetched  {r.key}  {url}", flush=True)
    if failed:
        raise RefkitError(f"{len(failed)} of {len(rows)} records could not be fetched: {', '.join(failed)}. "
                          "Check the identifiers in sources.tsv (or your connection) and run fetch again; records already fetched are kept.")


# ---------------------------------------------------------------- build

# Unicode repairs: dotless i (+ acute) from LaTeX {\'\i}; Greek look-alike letters inside Latin names.
FIX = {"ı́": "í", "ı": "i"}
GREEK_LATIN = {"ό": "ó", "έ": "é", "ί": "í", "ά": "á", "ο": "o"}
# registry fields that are not part of a reference
DROP_FIELDS = ("abstract", "keyword", "editor", "note", "reference", "link", "license", "subject", "assertion", "funder", "indexed",
               "deposited", "content-domain", "relation", "resource", "member", "prefix", "source", "score", "is-referenced-by-count",
               "references-count", "created", "update-policy", "alternative-id", "journal-issue", "published", "published-online",
               "published-print", "ISSN", "issn-type", "short-container-title", "container-title-short", "language", "archive_location",
               "event", "subtitle")
AUTHOR_FIELDS = ("family", "given", "literal", "suffix", "non-dropping-particle", "dropping-particle")
REGISTRY_TYPES = {"journal-article": "article-journal", "proceedings-article": "paper-conference", "posted-content": "article"}


def norm(s: str) -> str:
    for a, b in FIX.items():
        s = s.replace(a, b)
    if re.search(r"[A-Za-z]", s):
        s = "".join(GREEK_LATIN.get(c, c) for c in s)
    return unicodedata.normalize("NFC", s)


def clean(o):
    if isinstance(o, str):
        return norm(o)
    if isinstance(o, list):
        return [clean(x) for x in o]
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    return o


def sentence_case(title: str, words=frozenset(), phrases=()) -> str:
    """Sentence case that keeps acronyms (RNA, RNA-Seq), words with inner capitals or digits (PyTorch, H3K27ac), the given proper nouns
    and phrases; lower case after a colon, capital after '?'."""
    protected = [m.span() for ph in phrases for m in re.finditer(r"(?<!\w)" + re.escape(ph) + r"(?!\w)", title)]
    out, start, pos = [], True, 0
    for w in re.split(r"(\s+)", title):
        a, pos = pos, pos + len(w)
        if not w.strip():
            out.append(w)
            continue
        if not any(s <= a and pos <= e for s, e in protected):
            parts, new = w.split("-"), []
            acro = len(parts) > 1 and any(len(re.sub(r"\W", "", q)) > 1 and re.sub(r"\W", "", q).isupper() for q in parts)
            for i, q in enumerate(parts):
                core = re.sub(r"^\W+|\W+$", "", q)
                keep = (acro or (start and i == 0) or not core or core in words or re.search(r"[A-Z].*[A-Z]|\d", core)
                        or not core[0].isupper() or (core.isupper() and len(core) > 1))
                new.append(q if keep else q.replace(core, core[0].lower() + core[1:], 1))
            w = "-".join(new)
        out.append(w)
        start = w.endswith("?")
    return "".join(out)


def _issued(v: str) -> dict:
    return {"date-parts": [[int(x) for x in v.split("-")]]}


def _apply_overrides(e: dict, overrides) -> None:
    for k, v in overrides:
        if v == "":
            e.pop(k, None)
        elif k in ("issued", "accessed"):
            e[k] = _issued(v)
        else:
            e[k] = v


def read_csl(p: Project, r: Source) -> tuple[dict, str | None]:
    """(CSL-JSON item, preprint server name or None) for one source, from the files in library/."""
    if r.src == "doi":
        f = p.library / f"{r.key}.csl.json"
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise RefkitError(f"{f} is not valid JSON; run `refkit fetch --refresh`") from None
        if isinstance(e, list):
            e = e[0] if e else {}
        server = None
        if e.get("type") == "posted-content":
            inst = [i.get("name") for i in e.get("institution") or [] if isinstance(i, dict) and i.get("name")]
            server = inst[0] if inst else (e.get("publisher") or "Preprint")
        if not e.get("page") and e.get("article-number"):
            e["page"] = e["article-number"]
        if e.get("published-print"):
            e["issued"] = e["published-print"]  # cite the volume year, not the online-first date
        e["type"] = REGISTRY_TYPES.get(e.get("type"), e.get("type"))
        if (e.get("DOI") or "").lower().startswith("10.48550/"):
            server = "arXiv"
        return e, server
    bib = first_bib((p.library / f"{r.key}.bib").read_text(encoding="utf-8"))
    e = pandoc.bibtex_to_csl(bib)
    for fld, cs in (("title", "title"), ("booktitle", "container-title"), ("journal", "container-title")):
        v = bibfield(bib, fld)
        if v:
            e[cs] = pandoc.latex_text(v)
    if r.src == "iclr":
        e.pop("volume", None)  # ICLR records put the year in 'volume'
    if r.src == "arxiv":
        e["DOI"] = f"10.48550/arXiv.{r.id}"
    server = "arXiv" if (e.get("DOI") or "").lower().startswith("10.48550/") else None
    return e, server


def house_style(e: dict, r: Source, server: str | None, words=frozenset(), phrases=()) -> dict:
    """Apply the same house style to every record, then the row's overrides (an explicit override always wins)."""
    if server:  # preprint: '<server> https://doi.org/...' once
        doi = e.pop("DOI", None)
        e.update({"type": "article", "container-title": server})
        if doi:
            e["URL"] = "https://doi.org/" + doi
        e.pop("publisher", None)
    _apply_overrides(e, r.overrides)
    for k in DROP_FIELDS:
        e.pop(k, None)
    for k, v in list(e.items()):  # registry CSL sometimes gives lists of strings (titles, ISBN, URL)
        if isinstance(v, list) and not v:
            e.pop(k)
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            e[k] = v[0]
    e["author"] = [{k: a[k] for k in AUTHOR_FIELDS if k in a} for a in e.get("author", []) if isinstance(a, dict)]
    if not e["author"]:
        e.pop("author")
    if isinstance(e.get("title"), str):
        e["title"] = sentence_case(e["title"], words, phrases)
    if e.get("type") == "paper-conference":
        for k in ("publisher", "publisher-place", "DOI"):
            e.pop(k, None)
    if (e.get("DOI") or "").lower().startswith("10.5281/zenodo"):  # Zenodo: lowercase DOI, repository named once as the container
        e["DOI"] = e["DOI"].lower()
        e["URL"] = "https://doi.org/" + e["DOI"]
        e["container-title"] = "Zenodo"
        e.pop("publisher", None)
    _apply_overrides(e, r.overrides)
    e["id"] = r.key
    return e


def build(p: Project) -> None:
    rows = load_sources(p.sources_tsv)
    missing = [r.key for r in rows if not (p.library / f"{r.key}.bib").exists()
               or (r.src == "doi" and not (p.library / f"{r.key}.csl.json").exists())]
    if missing:
        raise RefkitError(f"not fetched yet: {', '.join(missing)}; run `refkit fetch` first")
    pandoc.require()
    words, phrases = load_proper_nouns(p.proper_nouns_file)
    out, errors = [], []
    for r in rows:
        try:
            e, server = read_csl(p, r)
            out.append(house_style(e, r, server, words, phrases))
        except (RefkitError, ValueError, KeyError, TypeError) as ex:
            errors.append(f"{r.key}: {ex}")
    if errors:
        raise RefkitError("could not build these references (try `refkit fetch --refresh`):\n  " + "\n  ".join(errors))
    p.references.write_text(json.dumps(clean(out), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (p.library / "ALL.bib").write_text("\n\n".join(first_bib((p.library / f"{r.key}.bib").read_text(encoding="utf-8")) for r in rows)
                                       + "\n", encoding="utf-8")
    print(f"built {len(out)} references -> {p.references}")


# ---------------------------------------------------------------- check

STOP = {"a", "an", "the", "of", "and", "in", "for", "with", "on", "to", "via"}


def ascii_lower(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def fams(authors) -> list:
    return [ascii_lower(a.get("family", "")) for a in authors or [] if isinstance(a, dict)]


def toks(t) -> set:
    return set(re.findall(r"[a-z0-9]+", (t or "").lower())) - STOP


def year_of(e: dict):
    try:
        return int(e["issued"]["date-parts"][0][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def md_cell(s) -> str:
    return re.sub(r"\s+", " ", str(s)).replace("|", "\\|")


def published_candidates(e: dict, pre_id: str, year) -> list:
    """Journal/proceedings records (Crossref) sharing >= 3 of the preprint's first 5 authors (or all, if fewer), published since the
    preprint: finds published versions even when the title changed."""
    fa = [f for f in fams(e.get("author"))[:5] if f]
    if not fa:
        return []
    need = min(3, len(fa))
    url = "https://api.crossref.org/works?rows=20&query.author=" + urllib.parse.quote(" ".join(fa))
    if year:
        url += f"&filter=from-pub-date:{year}"
    if net.contact():
        url += "&mailto=" + urllib.parse.quote(net.contact())
    out = []
    for it in net.get_json(url).get("message", {}).get("items", []):
        if it.get("type") not in ("journal-article", "proceedings-article") or it.get("DOI", "").lower() == pre_id.lower():
            continue
        if len(set(fams(it.get("author"))) & set(fa)) >= need:
            out.append(f"{it['DOI']} ({(it.get('container-title') or [''])[0]}): {(it.get('title') or [''])[0][:90]}")
    return out


def s2_venue(arxiv_id: str) -> str:
    try:
        v = net.get_json(f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields=venue,publicationVenue", tries=3)
    except FetchError:
        return ""
    return (v.get("publicationVenue") or {}).get("name") or v.get("venue") or ""


def openalex(e: dict, r: Source) -> str:
    """Independent second record: title, first author and year must agree."""
    mail = f"&mailto={urllib.parse.quote(net.contact())}" if net.contact() else ""
    doi = e.get("DOI") or (r.id if r.src == "doi" else "") or (f"10.48550/arXiv.{r.id}" if r.src == "arxiv" else "")
    try:
        if doi:
            w = net.get_json(f"https://api.openalex.org/works/doi:{net.quote_doi(doi)}?{mail.lstrip('&')}")
        else:  # no DOI: best title match among the top hits
            hits = net.get_json(f"https://api.openalex.org/works?per-page=10{mail}&search="
                                + urllib.parse.quote(e.get("title", ""))).get("results", [])
            if not hits:
                return "OpenAlex: no match"
            w = max(hits, key=lambda h: len(toks(h.get("title")) & toks(e.get("title")))
                    / max(1, len(toks(h.get("title")) | toks(e.get("title")))))
    except FetchError as ex:
        return f"OpenAlex: not found ({str(ex)[-60:]})"
    ta, tb = toks(e.get("title")), toks(w.get("title"))
    jac = len(ta & tb) / max(1, len(ta | tb))
    fa = (fams(e.get("author")) or [""])[0]
    fb = [ascii_lower((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])[:3]]
    ya, yb = year_of(e), w.get("publication_year")
    bad = []
    if jac < .8:
        bad.append(f"title differs ({jac:.2f}): {w.get('title')}")
    if fa and not any(fa in x for x in fb):
        bad.append(f"first author differs: {fb[:1]}")
    if ya and yb and abs(int(ya) - int(yb)) > 1:
        bad.append(f"year {ya} vs {yb}")
    return "OpenAlex agrees" if not bad else "OpenAlex: " + "; ".join(bad)


def preprint_pubs(e: dict, r: Source) -> tuple[bool, list]:
    """(is a preprint, notes on possible published versions)."""
    pubs = []
    server = (e.get("container-title") or "").lower() if e.get("type") == "article" else ""
    doi = r.id.lower() if r.src == "doi" else ""
    if doi.startswith("10.1101/") and server in ("biorxiv", "medrxiv"):
        j = net.get_json(f"https://api.biorxiv.org/pubs/{server}/{r.id}")
        pubs += [f"{e['container-title']}: published as {c.get('published_doi')} ({c.get('published_journal')})"
                 for c in j.get("collection", [])]
    elif r.src == "arxiv":
        x = net.get(f"https://export.arxiv.org/api/query?id_list={r.id}")
        for tag in ("arxiv:doi", "arxiv:journal_ref"):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", x, re.S)
            if m:
                pubs.append(f"arXiv {tag.split(':')[1]}: {m.group(1).strip()}")
        ven = s2_venue(r.id)
        if ven and "arxiv" not in ven.lower():
            pubs.append(f"Semantic Scholar venue: {ven}")
    elif not server:
        return False, []
    pre_id = r.id if r.src == "doi" else f"10.48550/arXiv.{r.id}"
    pubs += [f"Crossref: {c}" for c in published_candidates(e, pre_id, year_of(e))]
    return True, pubs


def check(p: Project) -> None:
    rows = load_sources(p.sources_tsv)
    p.require(p.references, "run `refkit build` first")
    js = {e["id"]: e for e in json.loads(p.references.read_text(encoding="utf-8"))}
    L = ["# Reference library report", f"generated {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
         "Each row: official citation file fetched from `source`; cross-checked against OpenAlex; preprints searched for published versions.",
         "", "| key | source | id | cross-check | published-version search | flags |", "|---|---|---|---|---|---|"]
    unresolved = 0
    for r in rows:
        e, flags = js.get(r.key), []
        if e is None:
            L.append(f"| {r.key} | {r.src} | {md_cell(r.id)} | - | - | not in references.json: run `refkit build` |")
            continue
        try:
            pre, pubs = preprint_pubs(e, r)
        except FetchError as ex:
            pre, pubs = True, [f"search failed: {ex}"]
        unresolved += bool(pre and pubs)
        odd = sorted({c for c in json.dumps(e, ensure_ascii=False)
                      if unicodedata.category(c) == "Mn" or "Ͱ" <= c <= "Ͽ" or c == "ı"})
        if odd:
            flags.append(f"odd characters {odd}")
        if r.overrides:
            flags.append(f"override: {r.override_text}")
        L.append(f"| {r.key} | {r.src} | {md_cell(r.id)} | {md_cell(openalex(e, r))} | "
                 f"{md_cell('; '.join(pubs) or ('none found' if pre else '-'))} | {md_cell('; '.join(flags) or '-')} |")
        print(f"checked  {r.key}", flush=True)
    keys = set(js)
    if p.manuscript.exists():
        cited = set(pandoc.cited_keys(p.manuscript))
        tail = [f"cited but not in library: {sorted(cited - keys) or 'none'}", f"in library but not cited: {sorted(keys - cited) or 'none'}"]
    else:
        tail = [f"manuscript {p.manuscript.name} not found: cited/listed comparison skipped"]
    tail.append(f"preprints with a possible published version to resolve: {unresolved}")
    (p.root / "REPORT.md").write_text("\n".join(L + [""] + tail) + "\n", encoding="utf-8")
    print("\n".join(tail))
    print("report ->", p.root / "REPORT.md")
