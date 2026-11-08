"""Tests for sync_sources.py.

Run from the repository root:
    python3 -m unittest discover -s .github/scripts -p 'test_*.py'
"""
import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

import sync_sources as ss

LABEL_63 = "a" * 63
# 63 + 1 + 63 + 1 + 63 + 1 + 61 = 253 characters, the generator's maximum.
DOMAIN_253 = ".".join([LABEL_63, LABEL_63, LABEL_63, "a" * 61])

# Each line is accepted or rejected by the v2fly generator on its own; the
# comment names the main.go check it exercises. Lines marked POLICY are
# accepted by the generator and refused here on purpose.
ACCEPTED = [
    "example.com",                       # plain line defaults to domain
    "Domain:Example.COM",                # type and value are case-insensitive
    "full:www.example.com",
    "keyword:example",
    r"regexp:^ads\d+\.example\.com$",
    "example.com @ads",                  # attribute
    "example.com @cn @!cn",              # several attributes, '!' allowed
    "example.com # comment after a rule",
    "include:ipip",
    "include:IPIP @cn",                  # list name is uppercased
    "include:geolocation-!cn @-ads",     # '!' and '-' in names, ban attribute
    DOMAIN_253,
    LABEL_63 + ".com",
]
REJECTED = [
    "unknown:example.com",               # unknown rule type
    "full:",                             # empty rule
    "include:",                          # empty inclusion
    "include:ip_ip",                     # invalid included list name
    "include:ipip @a_b",                 # invalid inclusion attribute
    "include:ipip @-",                   # empty ban attribute
    "include:ipip &other",               # affiliation in an inclusion
    "include:ipip extra",                # unknown field in an inclusion
    "exa_mple.com",                      # invalid domain character
    DOMAIN_253 + "a",                    # 254 characters
    "a" * 64 + ".com",                   # label longer than 63
    "example..com",                      # empty label
    "-example.com",                      # label starts with '-'
    "example-.com",                      # label ends with '-'
    "full:exa mple.com",                 # second field is not an attribute
    "keyword:exa_mple",                  # invalid keyword character
    "regexp:(",                          # regexp that does not compile
    "example.com @a_b",                  # invalid attribute
    "example.com @",                     # empty attribute
    "example.com extra",                 # unknown field
    "include:ßip",                       # Go keeps 'ß' and rejects the name
    "example.com &other",                # POLICY: affiliation
]
# Accepted by the generator, whose case mapping turns these letters into ASCII,
# and refused here because non-ASCII is refused before any case mapping. The
# difference is on the safe side: the previous file is kept.
SAFE_SIDE = [
    "include:ıpıp",                      # dotless i
    "İp.com",                            # dotted capital I
    "Key.com",                      # Kelvin sign
]
LINE_LIMIT = ss.MAX_LINE_BYTES  # the generator's scanner fails from this length on


class ValidateDomainListTest(unittest.TestCase):
    def test_accepts_what_the_generator_accepts(self):
        for line in ACCEPTED:
            with self.subTest(line=line):
                ss.validate_domain_list(line.encode())

    def test_rejects_what_the_generator_rejects(self):
        for line in REJECTED:
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    ss.validate_domain_list(line.encode())

    def test_refuses_non_ascii_before_case_mapping(self):
        for line in SAFE_SIDE:
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    ss.validate_domain_list(line.encode())

    def test_line_length_limit_of_the_generator_scanner(self):
        just_fits = b"keyword:" + b"a" * (LINE_LIMIT - 1 - len(b"keyword:"))
        ss.validate_domain_list(just_fits + b"\n")
        for too_long in (just_fits + b"a", b"#" * LINE_LIMIT):
            for ending in (b"\n", b""):              # also as the last line, unterminated
                with self.subTest(length=len(too_long), terminated=bool(ending)):
                    with self.assertRaisesRegex(ValueError, r"^line 1: 65536 bytes"):
                        ss.validate_domain_list(too_long + ending)

    def test_error_names_the_line(self):
        with self.assertRaisesRegex(ValueError, r"^line 3: "):
            ss.validate_domain_list(b"# header\nexample.com\nexample..com\n")

    def test_comment_and_blank_lines_are_skipped(self):
        ss.validate_domain_list(b"# only a comment\n\n   \n#include:\n")

    def test_lines_split_on_newline_only(self):
        # The generator's scanner splits lines on '\n' only. A form feed stays
        # inside the line, where splitting on whitespace turns the second name
        # into an unknown field; str.splitlines would have made it a valid line.
        with self.assertRaises(ValueError):
            ss.validate_domain_list(b"example.com\x0cexample.org\n")


class ListIncludesTest(unittest.TestCase):
    def test_names_are_uppercased_and_fields_after_the_name_ignored(self):
        payload = b"include:ipip @cn # comment\nexample.com\nInclude:Test-IPv6\n"
        self.assertEqual(ss.list_includes(payload), ["IPIP", "TEST-IPV6"])


class ResolveIncludesTest(unittest.TestCase):
    LISTS = {"A", "B", "C"}

    def test_include_of_a_list_on_disk_is_accepted(self):
        self.assertEqual(ss.resolve_includes({"a": ("A", ["B"])}, self.LISTS, {"B": []}), {})

    def test_include_outside_the_manifest_is_refused(self):
        refused = ss.resolve_includes({"a": ("A", ["OTHER"])}, self.LISTS, {"B": []})
        self.assertEqual(list(refused), ["a"])
        self.assertIn("include:other has no target in the manifest", refused["a"])

    def test_include_of_a_list_that_will_not_exist_is_refused(self):
        refused = ss.resolve_includes({"a": ("A", ["B"])}, self.LISTS, {})
        self.assertIn("include:b would not exist after this run", refused["a"])

    def test_dependency_accepted_in_the_same_run_counts_whatever_the_order(self):
        candidates = {"a": ("A", ["B"]), "b": ("B", [])}
        self.assertEqual(ss.resolve_includes(candidates, self.LISTS, {}), {})

    def test_refusal_cascades_to_what_includes_the_refused_list(self):
        candidates = {"a": ("A", ["B"]), "b": ("B", ["OTHER"])}
        refused = ss.resolve_includes(candidates, self.LISTS, {})
        self.assertEqual(sorted(refused), ["a", "b"])

    def test_refused_update_keeps_the_old_file_available(self):
        candidates = {"a": ("A", ["B"]), "b": ("B", ["OTHER"])}
        refused = ss.resolve_includes(candidates, self.LISTS, {"B": []})
        self.assertEqual(list(refused), ["b"])

    # The generator rejects all three below as "circular inclusion".
    def test_self_inclusion_is_refused(self):
        refused = ss.resolve_includes({"a": ("A", ["A"])}, self.LISTS, {})
        self.assertIn("circular inclusion a -> a", refused["a"])

    def test_cycle_between_two_new_payloads_refuses_both(self):
        candidates = {"a": ("A", ["B"]), "b": ("B", ["A"])}
        self.assertEqual(sorted(ss.resolve_includes(candidates, self.LISTS, {})), ["a", "b"])

    def test_cycle_through_a_file_already_on_disk_is_refused(self):
        refused = ss.resolve_includes({"a": ("A", ["B"])}, self.LISTS, {"B": ["C"], "C": ["A"]})
        self.assertIn("circular inclusion a -> b -> c -> a", refused["a"])

    def test_old_cycle_elsewhere_does_not_refuse_an_unrelated_payload(self):
        refused = ss.resolve_includes({"a": ("A", [])}, self.LISTS, {"B": ["C"], "C": ["B"]})
        self.assertEqual(refused, {})


class MainTest(unittest.TestCase):
    """main() on a temporary repository; every module path is redirected there."""

    def run_main(self, sources, payloads, existing=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "data").mkdir()
            for rel, content in (existing or {}).items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(content)
            lines = ["sources:"]
            for name, target in sources:
                lines += [f"  - name: {name}", "    type: url",
                          f"    url: https://example.invalid/{name}", f"    target: {target}"]
            (root / "sources.yaml").write_text("\n".join(lines) + "\n")

            def fake_fetch(src, _min_bytes=0):
                payload = payloads[src["name"]]
                if payload is None:              # the source did not download
                    raise RuntimeError("all URLs failed")
                ss.validate_domain_list(payload)
                return payload, src["url"], []

            out = io.StringIO()
            with mock.patch.object(ss, "ROOT", root), \
                    mock.patch.object(ss, "MANIFEST", root / "sources.yaml"), \
                    mock.patch.object(ss, "CHANGED_LOG", root / "changed.txt"), \
                    mock.patch.object(ss, "DIFF_LOG", root / "diff.txt"), \
                    mock.patch.object(ss, "fetch_source", fake_fetch), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = ss.main()
            files = {p.relative_to(root).as_posix(): p.read_bytes()
                     for p in root.rglob("*") if p.is_file()}
            return code, (root / "changed.txt").read_text().split(), files, out.getvalue()

    def test_include_outside_the_manifest_keeps_the_old_file_and_fails(self):
        code, changed, files, out = self.run_main(
            [("dependent", "data/dependent"), ("neighbour", "data/neighbour")],
            {"dependent": b"include:missing\n", "neighbour": b"example.org\n"},
            existing={"data/dependent": b"example.com\n"},
        )
        self.assertEqual(code, 1)
        self.assertEqual(changed, ["data/neighbour"])
        self.assertEqual(files["data/dependent"], b"example.com\n")
        self.assertEqual(files["data/neighbour"], b"example.org\n")
        self.assertIn("FAIL    dependent: include:missing has no target in the manifest", out)

    def test_dependency_listed_after_the_dependent_is_accepted(self):
        code, changed, _, _ = self.run_main(
            [("dependent", "data/dependent"), ("dep", "data/dep")],
            {"dependent": b"include:dep\n", "dep": b"example.org\n"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(changed, ["data/dependent", "data/dep"])

    def test_target_outside_data_is_not_an_include_target(self):
        code, changed, _, out = self.run_main(
            [("dependent", "data/dependent"), ("elsewhere", "other/dep")],
            {"dependent": b"include:dep\n", "elsewhere": b"example.org\n"},
        )
        self.assertEqual(code, 1)
        self.assertEqual(changed, ["other/dep"])
        self.assertIn("include:dep has no target in the manifest", out)

    def test_include_name_matches_the_target_whatever_the_case(self):
        code, changed, _, _ = self.run_main(
            [("dependent", "data/dependent"), ("ipip", "data/ipip")],
            {"dependent": b"include:IPIP\n", "ipip": b"example.org\n"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(changed, ["data/dependent", "data/ipip"])

    def test_unchanged_payload_is_not_rewritten(self):
        code, changed, _, _ = self.run_main(
            [("same", "data/same")], {"same": b"example.com\n"},
            existing={"data/same": b"example.com\n"},
        )
        self.assertEqual((code, changed), (0, []))

    def test_target_elsewhere_does_not_stand_in_for_a_missing_list_of_the_same_name(self):
        code, changed, _, out = self.run_main(
            [("dependent", "data/dependent"), ("dep", "data/dep"), ("elsewhere", "other/dep")],
            {"dependent": b"include:dep\n", "dep": None, "elsewhere": b"example.org\n"},
        )
        self.assertEqual(code, 1)
        self.assertEqual(changed, ["other/dep"])
        self.assertIn("dependent: include:dep would not exist after this run", out)

    def test_unreadable_file_on_disk_is_reported_and_the_rest_still_syncs(self):
        code, changed, _, out = self.run_main(
            [("neighbour", "data/neighbour")], {"neighbour": b"example.org\n"},
            existing={"data/huge": b"#" * ss.MAX_LINE_BYTES + b"\n"},
        )
        self.assertEqual(code, 1)
        self.assertEqual(changed, ["data/neighbour"])
        self.assertIn("data/huge: line 1: 65536 bytes", out)


class RepositoryTest(unittest.TestCase):
    def test_every_include_in_the_manifest_resolves(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        sources = ss.yaml.safe_load((root / "sources.yaml").read_text())["sources"]
        ss.validate_manifest(sources)
        lists = ss.data_lists(sources)
        candidates = {
            name: (name, ss.list_includes((root / target).read_bytes()))
            for name, target in lists.items()
        }
        # Nothing counted as already on disk: every include must be satisfied
        # by another manifest source on its own.
        self.assertEqual(ss.resolve_includes(candidates, set(lists), {}), {})


if __name__ == "__main__":
    unittest.main()
