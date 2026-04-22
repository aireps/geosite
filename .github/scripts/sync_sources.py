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


def fetch(url: str) -> bytes:
    resp = requests.get(url, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.content


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
            data = fetch(url)
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
