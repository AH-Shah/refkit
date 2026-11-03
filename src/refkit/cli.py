"""Command line: refkit [options] [step ...]"""
from __future__ import annotations

import argparse
import sys

from . import __version__, net
from .errors import RefkitError
from .project import Project

STEPS = ("fetch", "build", "check", "audit", "verify", "zotero")
DEFAULT = ("fetch", "build", "check")

HELP = """steps (run in this order, whatever order they are given in):
  fetch    download each official citation record into library/ (skips records already there unless --refresh)
  build    write references.json (CSL-JSON for pandoc, Zotero, Word) and library/ALL.bib
  check    look for published versions of preprints, cross-check with OpenAlex, compare cited and listed keys -> REPORT.md
  audit    re-check every reference against a freshly fetched official record -> AUDIT.md (exit code 1 if any needs checking)
  verify   rendered references next to their official records, for a manual read-through -> VERIFY.md (needs --csl)
  zotero   import library/ALL.bib into the running Zotero desktop app

default: fetch build check

environment variables (used when the matching option is not given):
  REFKIT_PROJECT, REFKIT_MANUSCRIPT, REFKIT_EMAIL, REFKIT_CSL"""


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="refkit", description="Build a reference list only from official citation records.",
                                 epilog=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steps", nargs="*", metavar="step", help="one or more of: " + ", ".join(STEPS))
    ap.add_argument("-C", "--project", metavar="DIR", help="project folder (default: current folder)")
    ap.add_argument("-m", "--manuscript", metavar="FILE", help="manuscript file, relative to the project (default: manuscript.md)")
    ap.add_argument("-e", "--email", help="your email, sent to Crossref and OpenAlex as a polite-pool contact")
    ap.add_argument("--csl", metavar="FILE", help="citation style for verify, relative to the project, e.g. styles/vancouver.csl")
    ap.add_argument("--refresh", action="store_true", help="fetch: download records again even if present")
    ap.add_argument("--version", action="version", version=f"refkit {__version__}")
    return ap


def main(argv=None) -> int:
    ap = parser()
    a = ap.parse_args(argv)
    bad = [s for s in a.steps if s not in STEPS]
    if bad:
        ap.error(f"unknown step(s): {', '.join(bad)} (choose from {', '.join(STEPS)})")
    steps = [s for s in STEPS if s in (a.steps or DEFAULT)]
    try:
        p = Project.from_options(a.project, a.manuscript, a.email, a.csl)
        net.configure(p.email)
        if not p.email and set(steps) & {"fetch", "check", "audit"}:
            print("note: set REFKIT_EMAIL or --email so Crossref and OpenAlex can contact you (faster, more reliable service)",
                  file=sys.stderr)
        from . import audit, library, verify, zotero
        status = 0
        for s in steps:
            if s == "fetch":
                library.fetch(p, a.refresh)
            elif s == "build":
                library.build(p)
            elif s == "check":
                library.check(p)
            elif s == "audit":
                status |= 0 if audit.audit(p) else 1
            elif s == "verify":
                verify.verify(p)
            elif s == "zotero":
                zotero.zotero(p)
        return status
    except RefkitError as e:
        print(f"refkit: error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("refkit: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
