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
import sys
import tempfile

import requests
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sources.yaml"
CHANGED_LOG = pathlib.Path("/tmp/changed.txt")
DIFF_LOG = pathlib.Path("/tmp/diff_summary.txt")
TIMEOUT_SECONDS = 30
MARKUP_PREFIXES = (b"<!doctype", b"<html", b"<?xml")
ALLOWED_DOMAIN_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyz0123456789.-")
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


def validate_domain_list(data: bytes) -> None:
    """Reject a payload the geosite generator would refuse to parse.

    Mirrors the line handling in v2fly/domain-list-community: a line is cut at
    the first '#', a leading '<type>:' selects the rule type and its absence
    means "domain", and every rule but a regexp is lowercased and then checked
    byte by byte against a-z, 0-9, '.' and '-'.

    Worth the duplication because of how the generator reacts: the first bad
    line makes it return an error and abandon the run, so one stray character
    in one source takes down every category at build time, in a workflow that
    has already committed the file. Checking here keeps that file out of the
    commit instead.

    Running the real generator would remove the risk of this copy drifting, and
    it is not even slow, but it reads data/ as a whole and would therefore block
    all seven sources over one bad file. Per-source isolation is worth more than
    exactness here, and drift is not silent either way: too strict and the sync
    fails naming the file and line, too lax and the build fails as it used to.
    """
    text = data.decode("utf-8", errors="surrogateescape")
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head, separator, tail = line.partition(":")
        rule_type, rule = (head.lower(), tail) if separator else ("domain", line)
        if rule_type == "include":
            continue
        if rule_type not in KNOWN_RULE_TYPES:
            raise ValueError(f"line {lineno}: unknown rule type {rule_type!r}")
        fields = rule.split()
        if not fields:
            raise ValueError(f"line {lineno}: empty rule")
        if rule_type == "regexp":
            continue
        value = fields[0].lower().encode("utf-8", errors="surrogateescape")
        if not ALLOWED_DOMAIN_BYTES.issuperset(value):
            raise ValueError(f"line {lineno}: invalid domain {fields[0]!r}")


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
