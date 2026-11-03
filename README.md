# refkit

[![tests](https://github.com/AH-Shah/refkit/actions/workflows/tests.yml/badge.svg)](https://github.com/AH-Shah/refkit/actions/workflows/tests.yml)

**A reference list built only from official records.** You never type a reference. You list one identifier per reference; refkit downloads the publisher's or venue's own citation record, builds a CSL-JSON bibliography that pandoc, Zotero or Word can use, and then audits every entry against freshly fetched official records.

- No hand-typed metadata, so no typos in authors, titles, volumes or pages.
- Preprints are checked for published versions (bioRxiv/medRxiv, arXiv, Crossref).
- Every reference is cross-checked against a second, independent source (OpenAlex) and re-audited before submission.
- Switching journals means swapping a `.csl` file; the references stay the same.

## Install

Requirements: Python 3.9+ (standard library only), [pandoc](https://pandoc.org/installing.html) 3.x, and internet access. The Zotero desktop app is optional.

```
pip install git+https://github.com/AH-Shah/refkit
```

or from a clone: `pip install -e .`. Without installing, `python -m refkit` works from `src/` too (`PYTHONPATH=src python -m refkit ...`).

## Quick start

```
cd example
refkit --email you@example.org                # fetch build check -> library/, references.json, REPORT.md
refkit --email you@example.org audit          # -> AUDIT.md: must say "N of N OK" before you submit
refkit verify --csl styles/vancouver.csl      # -> VERIFY.md: rendered references next to their sources
pandoc manuscript.md --citeproc --bibliography references.json --csl styles/vancouver.csl -o manuscript.docx
```

## Project folder

| File | What it is |
|---|---|
| `sources.tsv` | You write this. One line per reference: `key <TAB> source <TAB> identifier [<TAB> overrides]`. Lines starting with `#` are comments. |
| `manuscript.md` | Your text, citing references as `[@key]` or `[@key1; @key2]` (pandoc syntax). Any file name: `--manuscript paper.md`. |
| `styles/*.csl` | Citation styles. The example ships nature, vancouver, apa, bioinformatics and briefings-in-bioinformatics; thousands more at https://www.zotero.org/styles |
| `proper_nouns.txt` | Optional. Words or phrases kept capitalised in titles, which are otherwise converted to sentence case. One per line; a line with several words (e.g. `Molecular Signatures Database`) is kept as written wherever the whole phrase occurs. |

refkit writes `library/` (the downloaded records), `references.json`, `REPORT.md`, `AUDIT.md` and `VERIFY.md`. Never edit `references.json` by hand: fix `sources.tsv` and rebuild.

### Sources

| source | identifier | example |
|---|---|---|
| `doi` | a DOI; the registry's own record is used (Crossref, DataCite, bioRxiv/medRxiv) | `10.1038/s41586-023-06139-9` |
| `arxiv` | an arXiv id | `1412.6980` |
| `pmlr` | volume/paper from proceedings.mlr.press | `v267/bussmann25a` |
| `iclr`, `neurips` | year/hash from the proceedings URL | `2024/1fa1ab11f4bd5f94b2ec20e794dbfa3b` |
| `jmlr` | volume/paper from jmlr.org | `v12/pedregosa11a` |
| `acl` | ACL Anthology id | `2020.emnlp-demos.6` |
| `html` | a web page that shows a BibTeX block | `https://distill.pub/2017/momentum/` |

DOIs and arXiv ids may also be pasted as URLs (`https://doi.org/...`, `https://arxiv.org/abs/...`).

### Overrides

Use overrides only where the official record lacks a field. Write them as `field=value;field=value` with [CSL field names](https://docs.citationstyles.org/en/stable/specification.html#appendix-iv-variables), e.g. `type=dataset`, or `type=paper-conference;container-title=International Conference on Learning Representations;issued=2015` for an arXiv paper published at ICLR. Dates (`issued`, `accessed`) are `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. An empty value deletes the field. An override always wins over the house style below.

### House style

Applied identically to every record: titles in sentence case (keeping acronyms, words with inner capitals or digits, and `proper_nouns.txt`); preprints cited as `<server> https://doi.org/...`; conference papers without publisher, place or DOI; Zenodo records with a lowercase DOI and "Zenodo" as the container; registry-only fields (abstracts, funders, licences, ...) removed.

## Commands

```
refkit [options] [fetch] [build] [check] [audit] [verify] [zotero]
```

Steps always run in the order above; with no step, `fetch build check` runs.

| step | does |
|---|---|
| `fetch` | Downloads each record once into `library/`. `--refresh` downloads all again (e.g. after a Zenodo record changes); deleting a file there re-downloads just that one. A record that cannot be fetched is reported and the others still are. |
| `build` | Writes `references.json` and `library/ALL.bib`. |
| `check` | Looks for published versions of preprints, cross-checks each entry with OpenAlex, flags odd characters in names and titles, and lists keys cited but not listed (and the reverse) -> `REPORT.md`. A "possible published version" can be a different paper by the same authors, so open it before switching. |
| `audit` | Compares every reference with an official record fetched now: title, author list, year, venue, volume, issue, pages, DOI registration and published versions of preprints -> `AUDIT.md`. Exits with status 1 if any row says CHECK, so it can gate a CI job. |
| `verify` | Renders the bibliography with `--csl` and puts each entry next to a link to its source -> `VERIFY.md`, a checklist for a final read-through. |
| `zotero` | Imports `library/ALL.bib` into the collection selected in the running Zotero desktop app, skipping titles already there (enable Settings > Advanced > "Allow other applications on this computer to communicate with Zotero"). |

| option | environment variable | meaning |
|---|---|---|
| `-C DIR`, `--project DIR` | `REFKIT_PROJECT` | project folder (default: current folder) |
| `-m FILE`, `--manuscript FILE` | `REFKIT_MANUSCRIPT` | manuscript (default: `manuscript.md`) |
| `-e ADDR`, `--email ADDR` | `REFKIT_EMAIL` | your address, sent to Crossref and OpenAlex as their requested contact; recommended |
| `--csl FILE` | `REFKIT_CSL` | citation style for `verify` |
| `--refresh` | | re-download records in `fetch` |

Errors in `sources.tsv` (missing tabs, unknown sources, malformed DOIs or arXiv ids, duplicate keys, bad overrides) are all reported at once with line numbers. Network requests are retried with back-off and rate-limited per service (arXiv: one request every 3 s).

## Tests

```
python -m unittest discover -s tests
```

The tests run offline.

## License

MIT, see [LICENSE](LICENSE). The citation styles in `example/styles/` are from the [CSL project](https://citationstyles.org) and licensed CC BY-SA 3.0.
