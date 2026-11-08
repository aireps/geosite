#!/usr/bin/env python3
"""Fetch external data sources defined in sources.yaml.

Reads the manifest at the repository root, downloads each source, and writes
to its declared target under data/ only when the SHA256 differs from the
existing file. Writes the list of changed targets to /tmp/changed.txt and
a per-file diff summary to /tmp/diff_summary.txt for the workflow to use
in the commit body.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sys
import tempfile
from collections.abc import Iterator

import requests
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sources.yaml"
CHANGED_LOG = pathlib.Path("/tmp/changed.txt")
DIFF_LOG = pathlib.Path("/tmp/diff_summary.txt")
TIMEOUT_SECONDS = 30
MARKUP_PREFIXES = (b"<!doctype", b"<html", b"<?xml")
ALLOWED_DOMAIN_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyz0123456789.-")
# Character sets and limits of the v2fly generator (main.go: validateSiteName,
# validateAttrChars, maxDomainLen, maxLabelLen).
SITE_NAME_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!-")
ATTRIBUTE_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyz0123456789!")
MAX_DOMAIN_LENGTH = 253
MAX_LABEL_LENGTH = 63
# The generator reads lists with a default bufio.Scanner, which fails with
# "token too long" on any line of 64 KiB or more, a comment included.
MAX_LINE_BYTES = 64 * 1024
KNOWN_RULE_TYPES = frozenset({"domain", "full", "keyword", "regexp"})
MANIFEST_COMMON_KEYS = frozenset(
    {"name", "type", "target", "min_bytes", "fallback_urls"}
)
MANIFEST_TYPE_KEYS = {
    "github_raw": frozenset({"repo", "ref", "path"}),
    "url": frozenset({"url"}),
}


def validate_manifest(sources: object) -> None:
    """Reject a malformed manifest before a single source is fetched.

    Deliberately harsher than the per-source handling in main(). A source that
    will not download is an outside event, so it is isolated and the rest still
    sync; a manifest that does not hold together is our own file, edited by hand
    minutes ago, and its remaining entries earn no trust from that point on.

    Unknown keys are errors rather than something to ignore, because the failure
    worth catching here is a typo in an optional one: `min_byte` instead of
    `min_bytes` turns the size check off and leaves no trace anywhere.
    """
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources: expected a non-empty list")

    problems: list[str] = []
    seen_names: set[str] = set()
    seen_targets: set[str] = set()

    for index, src in enumerate(sources):
        where = f"sources[{index}]"
        if not isinstance(src, dict):
            problems.append(f"{where}: expected a mapping, got {type(src).__name__}")
            continue

        name = src.get("name")
        if isinstance(name, str) and name:
            where = f"{where} ({name})"
            if name in seen_names:
                problems.append(f"{where}: duplicate name")
            seen_names.add(name)
        else:
            problems.append(f"{where}: missing or empty name")

        target = src.get("target")
        if isinstance(target, str) and target:
            if target in seen_targets:
                problems.append(f"{where}: duplicate target {target!r}")
            seen_targets.add(target)
        else:
            problems.append(f"{where}: missing or empty target")

        kind = src.get("type")
        type_keys = MANIFEST_TYPE_KEYS.get(kind)
        if type_keys is None:
            # Without a known type there is no way to say which keys belong
            # here, so skip the per-type checks instead of reporting every
            # remaining key as unknown.
            problems.append(
                f"{where}: type must be one of {sorted(MANIFEST_TYPE_KEYS)}, got {kind!r}"
            )
        else:
            for key in sorted(type_keys):
                value = src.get(key)
                if not isinstance(value, str) or not value:
                    problems.append(f"{where}: missing or empty {key}")
            for key in sorted(set(src) - (MANIFEST_COMMON_KEYS | type_keys)):
                problems.append(f"{where}: unknown key {key!r}")

        if "min_bytes" in src:
            min_bytes = src["min_bytes"]
            # bool is a subclass of int, and `min_bytes: true` is never intended.
            if isinstance(min_bytes, bool) or not isinstance(min_bytes, int) or min_bytes < 0:
                problems.append(
                    f"{where}: min_bytes must be a non-negative integer, got {min_bytes!r}"
                )

        if "fallback_urls" in src:
            fallback_urls = src["fallback_urls"]
            if not isinstance(fallback_urls, list) or not fallback_urls:
                problems.append(f"{where}: fallback_urls must be a non-empty list")
            else:
                for fallback_index, url in enumerate(fallback_urls):
                    if not isinstance(url, str) or not url:
                        problems.append(
                            f"{where}: fallback_urls[{fallback_index}] "
                            "must be a non-empty string"
                        )

    if problems:
        raise ValueError("\n".join(problems))


def build_url(src: dict) -> str:
    kind = src.get("type")
    if kind == "github_raw":
        return (
            f"https://raw.githubusercontent.com/{src['repo']}"
            f"/{src['ref']}/{src['path']}"
        )
    if kind == "url":
        return src["url"]
    raise ValueError(f"unknown source type: {kind!r}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, min_bytes: int = 0) -> bytes:
    """Download a source and reject a response that is not data at all.

    A 404 is caught by raise_for_status, but an error page served with 200
    would otherwise be written into data/. These two checks only answer "does
    this resemble a data file"; whether the generator will accept its contents
    is validate_domain_list's question, and the two are kept apart so that a
    change to the grammar never touches the transport code.
    """
    resp = requests.get(url, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.content
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(MARKUP_PREFIXES):
        raise ValueError(f"looks like markup, not a data file ({len(data)} bytes)")
    if min_bytes and len(data) < min_bytes:
        raise ValueError(f"too small: {len(data)} bytes, expected at least {min_bytes}")
    return data


def fetch_source(src: dict, min_bytes: int = 0) -> tuple[bytes, str, list[str]]:
    """Fetch and validate a source, trying its mirrors in declared order."""
    urls = [build_url(src), *src.get("fallback_urls", [])]
    errors: list[str] = []

    for url in urls:
        try:
            data = fetch(url, min_bytes)
            validate_domain_list(data)
            return data, url, errors
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("all URLs failed: " + " | ".join(errors))


def _rules(data: bytes) -> Iterator[tuple[int, str, list[str]]]:
    """Yield (line number, rule type, fields) for every rule, as the generator reads them.

    v2fly main.go: lines are split on '\\n', a line is cut at the first '#' and
    trimmed, the type is the part before the first ':' lowercased and defaults
    to "domain" when there is no ':', and the rest is split on whitespace.
    Raises ValueError on a line the generator's scanner cannot read at all.
    """
    for lineno, raw in enumerate(data.split(b"\n"), 1):
        if len(raw) >= MAX_LINE_BYTES:
            raise ValueError(
                f"line {lineno}: {len(raw)} bytes, the generator reads at most {MAX_LINE_BYTES - 1}"
            )
        line = raw.decode("utf-8", errors="surrogateescape").split("#", 1)[0].strip()
        if not line:
            continue
        head, separator, tail = line.partition(":")
        rule_type, rule = (head.lower(), tail) if separator else ("domain", line)
        yield lineno, rule_type, rule.split()


def _has_only(value: str, allowed: frozenset[int], case=str.lower) -> bool:
    """value is non-empty ASCII and, once case-mapped, made of allowed bytes only.

    ASCII is required before the case mapping because Python and Go map case
    differently outside it: Python turns 'ß' into 'SS', which would pass as a
    list name the generator rejects. Refusing non-ASCII up front leaves only
    differences in the safe direction, see validate_domain_list.
    """
    return bool(value) and value.isascii() and allowed.issuperset(case(value).encode())


def _is_domain_name(value: str) -> bool:
    """main.go validateDomainName: allowed characters, total length, and labels
    that are non-empty, short enough and neither start nor end with '-'."""
    if not _has_only(value, ALLOWED_DOMAIN_BYTES) or len(value) > MAX_DOMAIN_LENGTH:
        return False
    return all(
        label and len(label) <= MAX_LABEL_LENGTH and label[0] != "-" and label[-1] != "-"
        for label in value.split(".")
    )


def _check_inclusion(fields: list[str]) -> None:
    """main.go parseInclusion: a list name, then only @attr and @-attr fields."""
    if not fields:
        raise ValueError("empty inclusion")
    if not _has_only(fields[0], SITE_NAME_BYTES, case=str.upper):
        raise ValueError(f"invalid included list name {fields[0]!r}")
    for field in fields[1:]:
        if field[0] == "@":
            if not _has_only(field[1:].removeprefix("-"), ATTRIBUTE_BYTES):
                raise ValueError(f"invalid inclusion attribute {field!r}")
        elif field[0] == "&":
            raise ValueError("affiliation is not allowed for inclusion")
        else:
            raise ValueError(f"unknown field {field!r}")


def _check_entry(rule_type: str, fields: list[str]) -> None:
    """main.go parseEntry, plus one rule of our own: no affiliations."""
    if not fields:
        raise ValueError("empty rule")
    value = fields[0]
    if rule_type == "regexp":
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regexp {value!r}: {exc}") from None
    elif rule_type == "keyword":
        if not _has_only(value, ALLOWED_DOMAIN_BYTES):
            raise ValueError(f"invalid keyword {value!r}")
    elif not _is_domain_name(value):
        raise ValueError(f"invalid domain {value!r}")
    for field in fields[1:]:
        if field[0] == "@":
            if not _has_only(field[1:], ATTRIBUTE_BYTES):
                raise ValueError(f"invalid attribute {field!r}")
        elif field[0] == "&":
            # The generator accepts a well-formed affiliation and adds the entry
            # to another list, which here could be a category inherited from
            # upstream that the consumers route on. A synced source must not
            # reach into other lists, so the field is refused outright.
            raise ValueError(f"affiliation {field!r} is not allowed in a synced list")
        else:
            raise ValueError(f"unknown field {field!r}")


def validate_domain_list(data: bytes) -> None:
    """Reject a payload the geosite generator would refuse to parse.

    Mirrors the per-line checks of v2fly/domain-list-community main.go
    (parseEntry, parseInclusion, the validate* helpers and the scanner's line
    length): rule types, domain names with their length and label rules,
    keyword characters, attribute and list-name characters, inclusion syntax,
    and unknown fields. Affiliations are refused on top of that, see
    _check_entry.

    Known differences, all but one in the safe direction:
    - non-ASCII is refused before any case mapping, while Go's simple case
      mapping turns a few non-ASCII letters into ASCII ones and accepts them
      (dotless 'ı', dotted 'İ', the Kelvin sign);
    - regexps are compiled with Python's re, while the generator uses Go's
      RE2. RE2 accepts constructs such as \\p{...} that re rejects, which is
      safe. re accepts lookarounds and backreferences that RE2 rejects, which
      is not, but cannot reach us from v2fly, whose own CI builds every push
      with the generator.
    A refusal in the safe direction keeps the previous file and reports the
    line.

    Worth the duplication because of how the generator reacts: the first bad
    line makes it return an error and abandon the run, so one stray character
    in one source takes down every category at build time, in a workflow that
    has already committed the file. Checking here keeps that file out of the
    commit instead.

    Running the real generator would remove the risk of this copy drifting, and
    it is not even slow, but it reads data/ as a whole and would therefore block
    every source over one bad file. Per-source isolation is worth more than
    exactness here, and drift is not silent either way: too strict and the sync
    fails naming the file and line, too lax and the build fails as it used to.
    """
    for lineno, rule_type, fields in _rules(data):
        try:
            if rule_type == "include":
                _check_inclusion(fields)
            elif rule_type in KNOWN_RULE_TYPES:
                _check_entry(rule_type, fields)
            else:
                raise ValueError(f"unknown rule type {rule_type!r}")
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from None


def write_atomic(target: pathlib.Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    with MANIFEST.open() as fh:
        manifest = yaml.safe_load(fh) or {}
    sources = manifest.get("sources") or []

    CHANGED_LOG.write_text("")
    DIFF_LOG.write_text("")

    try:
        validate_manifest(sources)
    except ValueError as exc:
        print("manifest is not usable:", file=sys.stderr)
        for line in str(exc).splitlines():
            print(f"  {line}", file=sys.stderr)
        return 1

    changed: list[str] = []
    diff_lines: list[str] = []
    fallback_lines: list[str] = []
    failures: list[str] = []

    for src in sources:
        name = src.get("name") or "<unnamed>"
        target_rel = src.get("target")
        if not target_rel:
            failures.append(f"{name}: missing target")
            continue
        target = ROOT / target_rel

        try:
            data, used_url, source_errors = fetch_source(
                src, int(src.get("min_bytes") or 0)
            )
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        if source_errors:
            fallback_lines.append(
                f"{name}: using {used_url} after {len(source_errors)} failed attempt(s): "
                + " | ".join(source_errors)
            )

        new_sha = sha256(data)
        if target.exists():
            old_sha = sha256(target.read_bytes())
            if old_sha == new_sha:
                continue
            line = f"{target_rel}: {old_sha[:12]} -> {new_sha[:12]} ({len(data)} bytes)"
        else:
            line = f"{target_rel}: NEW {new_sha[:12]} ({len(data)} bytes)"

        write_atomic(target, data)
        changed.append(target_rel)
        diff_lines.append(line)

    if changed:
        CHANGED_LOG.write_text("\n".join(changed) + "\n")
        DIFF_LOG.write_text("\n".join(diff_lines) + "\n")

    print(
        f"sources: {len(sources)}, changed: {len(changed)}, "
        f"fallbacks: {len(fallback_lines)}, failures: {len(failures)}"
    )
    for line in diff_lines:
        print(f"  CHANGED {line}")
    for line in fallback_lines:
        print(f"  FALLBACK {line}", file=sys.stderr)
    for line in failures:
        print(f"  FAIL    {line}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
