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
    """Download a source and reject responses that are obviously not data.

    A 404 is caught by raise_for_status, but an error page served with 200
    would otherwise be written into data/ and only surface later, as a build
    failure in the geosite generator. The two checks here stay deliberately
    shallow: they never parse the domain-list grammar, which lives in
    v2fly/domain-list-community and would drift if mirrored in Python.
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

    changed: list[str] = []
    diff_lines: list[str] = []
    failures: list[str] = []

    for src in sources:
        name = src.get("name") or "<unnamed>"
        target_rel = src.get("target")
        if not target_rel:
            failures.append(f"{name}: missing target")
            continue
        target = ROOT / target_rel

        try:
            url = build_url(src)
            data = fetch(url, int(src.get("min_bytes") or 0))
            validate_domain_list(data)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue

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

    print(f"sources: {len(sources)}, changed: {len(changed)}, failures: {len(failures)}")
    for line in diff_lines:
        print(f"  CHANGED {line}")
    for line in failures:
        print(f"  FAIL    {line}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
