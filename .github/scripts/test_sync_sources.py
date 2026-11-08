"""Tests for sync_sources.py.

Run from the repository root:
    python3 -m unittest discover -s .github/scripts -p 'test_*.py'
"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
