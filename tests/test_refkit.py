"""Offline tests (no network). Run: python -m unittest discover -s tests"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from refkit import audit, net
from refkit.bibtex import bibfield, first_bib
from refkit.errors import FetchError, NotFound, RefkitError
from refkit.library import house_style, sentence_case
from refkit.project import Source, load_proper_nouns, load_sources, parse_overrides


class SentenceCase(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(sentence_case("Adam: A Method for Stochastic Optimization", {"Adam"}), "Adam: a method for stochastic optimization")

    def test_keeps_acronyms_and_inner_capitals(self):
        self.assertEqual(sentence_case("Single-Cell RNA-Seq Analysis With PyTorch"), "Single-cell RNA-Seq analysis with PyTorch")

    def test_proper_noun_word(self):
        self.assertEqual(sentence_case("Machine Learning in Python", {"Python"}), "Machine learning in Python")
        self.assertEqual(sentence_case("Machine Learning in Python"), "Machine learning in python")

    def test_phrase(self):
        t = "The Molecular Signatures Database Hallmark Gene Set Collection"
        self.assertEqual(sentence_case(t, phrases=("Molecular Signatures Database",)),
                         "The Molecular Signatures Database hallmark gene set collection")

    def test_capital_after_question_mark(self):
        self.assertEqual(sentence_case("Why? Because It Works"), "Why? Because it works")


class Bibtex(unittest.TestCase):
    def test_first_bib_skips_css(self):
        page = "<style>@page { margin: 0 } @media print { a {} }</style><pre>@Manual{,\n  title = {R {A} B},\n  year = {2024},\n}</pre>"
        self.assertEqual(first_bib(page), "@Manual{,\n  title = {R {A} B},\n  year = {2024},\n}")

    def test_first_bib_errors(self):
        with self.assertRaises(ValueError):
            first_bib("no entry here")
        with self.assertRaises(ValueError):
            first_bib("@article{k, title={open")

    def test_bibfield(self):
        bib = '@inproceedings{k,\n booktitle = {Proc. {ICML}},\n title = "Quoted",\n year = 2020\n}'
        self.assertEqual(bibfield(bib, "booktitle"), "Proc. {ICML}")
        self.assertEqual(bibfield(bib, "title"), "Quoted")
        self.assertEqual(bibfield(bib, "year"), "2020")
        self.assertIsNone(bibfield(bib, "journal"))
        self.assertIsNone(bibfield("@misc{k, title = ", "title"))


class Sources(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, text):
        f = self.dir / "sources.tsv"
        f.write_text(text)
        return f

    def test_valid_and_normalised(self):
        rows = load_sources(self.write("# comment\nkey\tsource\tid\na\tdoi\thttps://doi.org/10.1038/X \nb\tarxiv\tarXiv:1412.6980\ttype=dataset;issued=2015\n"))
        self.assertEqual([(r.key, r.id) for r in rows], [("a", "10.1038/X"), ("b", "1412.6980")])
        self.assertEqual(rows[1].overrides, [("type", "dataset"), ("issued", "2015")])

    def test_errors_reported_together(self):
        with self.assertRaises(RefkitError) as cm:
            load_sources(self.write("a\tdoi\tnope\nb  doi  10.1/x\nc\tweb\tx\na\ticlr\t2024/zz\n"))
        msg = str(cm.exception)
        for part in (":1:", ":2:", "TABs", "unknown source 'web'", "already used", "year/hash"):
            self.assertIn(part, msg)

    def test_missing_file(self):
        with self.assertRaises(RefkitError):
            load_sources(self.dir / "absent.tsv")

    def test_overrides(self):
        self.assertEqual(parse_overrides("a=1; b= ;"), ([("a", "1"), ("b", "")], []))
        self.assertTrue(parse_overrides("noequals")[1])

    def test_proper_nouns(self):
        f = self.dir / "proper_nouns.txt"
        f.write_text("# comment\nPython\nMolecular  Signatures Database  # trailing comment\n\n")
        self.assertEqual(load_proper_nouns(f), (frozenset({"Python"}), ("Molecular Signatures Database",)))
        self.assertEqual(load_proper_nouns(self.dir / "absent.txt"), (frozenset(), ()))


class HouseStyle(unittest.TestCase):
    def test_preprint_and_overrides_win(self):
        r = Source("k", "doi", "10.1101/1", [("title", "Kept As Written"), ("note", "x")])
        e = house_style({"DOI": "10.1101/1", "publisher": "CSHL", "title": "T", "author": [{"family": "F", "ORCID": "o"}]},
                        r, "bioRxiv")
        self.assertEqual(e["container-title"], "bioRxiv")
        self.assertEqual(e["URL"], "https://doi.org/10.1101/1")
        self.assertNotIn("DOI", e)
        self.assertNotIn("publisher", e)
        self.assertEqual(e["title"], "Kept As Written")
        self.assertEqual(e["note"], "x")
        self.assertEqual(e["author"], [{"family": "F"}])

    def test_issued_override_and_delete(self):
        r = Source("k", "doi", "10.1/x", [("issued", "2015-03"), ("volume", "")])
        e = house_style({"volume": "3", "title": "A"}, r, None)
        self.assertEqual(e["issued"], {"date-parts": [[2015, 3]]})
        self.assertNotIn("volume", e)


class Audit(unittest.TestCase):
    def test_missing_registry_record_is_a_check_row(self):
        with mock.patch.object(net, "get", side_effect=NotFound("404")):
            src, ok, notes = audit.audit_entry({"id": "k", "DOI": "10.1038/typo", "title": "T"})
        self.assertFalse(ok)
        self.assertIn("registry record not found", notes)

    def test_network_failure_is_a_check_row(self):
        with mock.patch.object(net, "get", side_effect=FetchError("timeout")):
            src, ok, notes = audit.audit_entry({"id": "k", "DOI": "10.1038/x", "title": "T"})
        self.assertFalse(ok)
        self.assertTrue(any("could not retrieve" in n for n in notes))

    def test_no_identifier(self):
        self.assertEqual(audit.audit_entry({"id": "k", "title": "T"}), ("-", False, ["no DOI or URL to check against"]))


@unittest.skipUnless(shutil.which("pandoc"), "pandoc not installed")
class Pandoc(unittest.TestCase):
    def test_cited_keys(self):
        from refkit.pandoc import cited_keys
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.md"
            f.write_text("See [@a; @b:2020] and @c-d. Mail x@y.org. Again [@a].\n")
            self.assertEqual(cited_keys(f), ["a", "b:2020", "c-d"])


if __name__ == "__main__":
    unittest.main()
