"""Project folder layout, sources.tsv parsing/validation and the proper-noun list."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import RefkitError

SOURCES = ("doi", "arxiv", "pmlr", "iclr", "neurips", "acl", "jmlr", "html")
KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z_-]*$")
DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z-]+(\.[A-Z]{2})?/\d{7})(v\d+)?$")
YEAR_HASH_RE = re.compile(r"^\d{4}/[0-9a-f]+$")


@dataclass
class Project:
    root: Path
    manuscript: Path
    email: str | None = None
    csl: Path | None = None

    @classmethod
    def from_options(cls, project=None, manuscript=None, email=None, csl=None) -> "Project":
        root = Path(project or os.environ.get("REFKIT_PROJECT") or Path.cwd()).expanduser().resolve()
        if not root.is_dir():
            raise RefkitError(f"project folder not found: {root}")
        manu = root / (manuscript or os.environ.get("REFKIT_MANUSCRIPT") or "manuscript.md")
        csl = csl or os.environ.get("REFKIT_CSL")
        return cls(root, manu, email or os.environ.get("REFKIT_EMAIL") or None, root / csl if csl else None)

    @property
    def sources_tsv(self) -> Path:
        return self.root / "sources.tsv"

    @property
    def library(self) -> Path:
        return self.root / "library"

    @property
    def references(self) -> Path:
        return self.root / "references.json"

    @property
    def proper_nouns_file(self) -> Path:
        return self.root / "proper_nouns.txt"

    def require(self, path: Path, hint: str) -> Path:
        if not path.exists():
            raise RefkitError(f"{path} not found; {hint}")
        return path


@dataclass
class Source:
    key: str
    src: str
    id: str
    overrides: list = field(default_factory=list)  # [(csl_field, value)], value "" deletes the field
    line: int = 0

    @property
    def override_text(self) -> str:
        return ";".join(f"{k}={v}" for k, v in self.overrides)


def _normalise_id(src: str, ident: str) -> str:
    if src == "doi":
        ident = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", ident, flags=re.I)
    elif src == "arxiv":
        ident = re.sub(r"^(https?://arxiv\.org/(abs|pdf)/|arxiv:\s*)", "", ident, flags=re.I)
        ident = re.sub(r"\.pdf$", "", ident)
    return ident.strip()


def _check_id(src: str, ident: str) -> str | None:
    if src == "doi" and not re.match(r"^10\.\d{4,9}/\S+$", ident):
        return f"'{ident}' is not a DOI (expected 10.NNNN/...)"
    if src == "arxiv" and not ARXIV_RE.match(ident):
        return f"'{ident}' is not an arXiv id (e.g. 1412.6980 or hep-th/9901001)"
    if src in ("iclr", "neurips") and not YEAR_HASH_RE.match(ident):
        return f"{src} id must be year/hash from the proceedings URL, e.g. 2024/1fa1ab11f4bd5f94b2ec20e794dbfa3b"
    if src == "html" and not re.match(r"^https?://", ident):
        return "html id must be a full http(s) URL"
    if src in ("pmlr", "jmlr") and not re.match(r"^v\d+/[\w.-]+$", ident):
        return f"{src} id must look like v12/name (volume/paper id)"
    return None


def parse_overrides(text: str) -> tuple[list, list]:
    """'field=value;field=value' -> ([(field, value)], [error messages])."""
    out, errors = [], []
    for part in (p.strip() for p in text.split(";")):
        if not part:
            continue
        if "=" not in part:
            errors.append(f"override '{part}' is not field=value")
            continue
        k, v = (s.strip() for s in part.split("=", 1))
        if not FIELD_RE.match(k):
            errors.append(f"override field '{k}' is not a CSL field name")
        elif k == "issued" and v and not DATE_RE.match(v):
            errors.append(f"issued must be YYYY, YYYY-MM or YYYY-MM-DD, not '{v}'")
        else:
            out.append((k, v))
    return out, errors


def load_sources(path: Path) -> list[Source]:
    """Read and validate sources.tsv; all problems are reported together with their line numbers."""
    if not path.exists():
        raise RefkitError(f"{path} not found: create it with one line per reference: key<TAB>source<TAB>identifier[<TAB>overrides]")
    rows, errors, seen = [], [], {}
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        p = [c.strip() for c in line.split("\t")]
        while p and p[-1] == "":
            p.pop()
        if [c.lower() for c in p[:2]] == ["key", "source"]:  # header line without '#'
            continue
        where = f"{path.name}:{n}"
        if len(p) < 3:
            hint = " (columns must be separated by TABs, not spaces)" if len(p) == 1 and " " in p[0] else ""
            errors.append(f"{where}: expected key, source, identifier; found {len(p)} column(s){hint}")
            continue
        if len(p) > 4:
            errors.append(f"{where}: more than 4 columns; join overrides with ';'")
            continue
        key, src, ident = p[0], p[1].lower(), p[2]
        if not KEY_RE.match(key):
            errors.append(f"{where}: key '{key}' may only contain letters, digits and _ . + -")
        if key in seen:
            errors.append(f"{where}: key '{key}' already used on line {seen[key]}")
        seen.setdefault(key, n)
        if src not in SOURCES:
            errors.append(f"{where}: unknown source '{p[1]}' (use one of: {', '.join(SOURCES)})")
            continue
        ident = _normalise_id(src, ident)
        bad = _check_id(src, ident)
        if bad:
            errors.append(f"{where}: {bad}")
        over, oerr = parse_overrides(p[3] if len(p) > 3 else "")
        errors += [f"{where}: {e}" for e in oerr]
        rows.append(Source(key, src, ident, over, n))
    if errors:
        raise RefkitError("problems in sources.tsv:\n  " + "\n  ".join(errors))
    if not rows:
        raise RefkitError(f"{path} lists no references")
    return rows


def load_proper_nouns(path: Path) -> tuple[frozenset, tuple]:
    """proper_nouns.txt: one word or phrase per line ('#' starts a comment). Single words are kept capitalised wherever they occur
    in a title; multi-word phrases (e.g. 'Molecular Signatures Database') are kept as written when the whole phrase occurs."""
    words, phrases = set(), []
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            entry = re.sub(r"\s+", " ", line.split("#", 1)[0]).strip()
            if not entry:
                continue
            (phrases.append(entry) if " " in entry else words.add(entry))
    return frozenset(words), tuple(sorted(phrases, key=len, reverse=True))
