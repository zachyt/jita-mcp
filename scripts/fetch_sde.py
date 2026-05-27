#!/usr/bin/env python3
"""Idempotent EVE SDE downloader.

Reads the expected MD5 from sde.checksum (or --version=latest), fetches the
Fuzzwork SQLite SDE only if the local copy doesn't already match, verifies the
checksum, decompresses, and writes data/sde.sqlite atomically.

Designed to be run with bare Python — no project deps, no uv. Works the same
way locally and inside the Dockerfile.

Usage:
    python scripts/fetch_sde.py
    python scripts/fetch_sde.py --version latest
    python scripts/fetch_sde.py --force
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SDE_PATH = DATA_DIR / "sde.sqlite"
SIDECAR_PATH = DATA_DIR / "sde.sqlite.md5"
CHECKSUM_FILE = REPO_ROOT / "sde.checksum"

BASE_URL = "https://www.fuzzwork.co.uk/dump"
BZ2_URL = f"{BASE_URL}/sqlite-latest.sqlite.bz2"
MD5_URL = f"{BASE_URL}/sqlite-latest.sqlite.bz2.md5"


def log(msg: str) -> None:
    print(f"[fetch_sde] {msg}", flush=True)


def read_md5_sidecar(path: Path) -> str | None:
    return path.read_text().strip() if path.exists() else None


def fetch_upstream_md5() -> str:
    log(f"GET {MD5_URL}")
    with urllib.request.urlopen(MD5_URL, timeout=30) as r:
        body = r.read().decode().strip()
    # Fuzzwork ships md5sum format: "<hash>  <filename>"
    return body.split()[0]


def resolve_expected_md5(version: str) -> str:
    if version == "latest":
        return fetch_upstream_md5()
    if CHECKSUM_FILE.exists():
        return CHECKSUM_FILE.read_text().strip().split()[0]
    raise SystemExit(
        f"No sde.checksum file at {CHECKSUM_FILE} and --version!=latest. "
        "Create it (e.g. `python scripts/fetch_sde.py --version latest && "
        "cp data/sde.sqlite.md5 sde.checksum`) or pass --version latest."
    )


def md5_of_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def download_and_decompress(expected_md5: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bz2_path = DATA_DIR / "sqlite-latest.sqlite.bz2"
    tmp_path = SDE_PATH.with_suffix(".sqlite.tmp")

    log(f"GET {BZ2_URL} -> {bz2_path}")
    with urllib.request.urlopen(BZ2_URL, timeout=600) as r, bz2_path.open("wb") as out:
        shutil.copyfileobj(r, out, length=1 << 20)

    log("Verifying MD5...")
    actual = md5_of_file(bz2_path)
    if actual != expected_md5:
        bz2_path.unlink(missing_ok=True)
        raise SystemExit(
            f"MD5 mismatch! expected {expected_md5}, got {actual}. "
            "Either sde.checksum is stale (run with --version latest and update it) "
            "or the download was corrupted."
        )
    log("MD5 ok.")

    log(f"Decompressing -> {tmp_path}")
    with bz2.open(bz2_path, "rb") as src, tmp_path.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1 << 20)

    tmp_path.replace(SDE_PATH)
    bz2_path.unlink(missing_ok=True)
    SIDECAR_PATH.write_text(expected_md5 + "\n")
    log(f"SDE ready at {SDE_PATH} ({SDE_PATH.stat().st_size / 1e6:.0f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default="pinned",
        choices=["pinned", "latest"],
        help="pinned (read sde.checksum) or latest (fetch live upstream MD5)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if local MD5 already matches expected.",
    )
    args = parser.parse_args()

    expected = resolve_expected_md5(args.version)
    log(f"Expected MD5: {expected}")

    if not args.force and SDE_PATH.exists():
        local = read_md5_sidecar(SIDECAR_PATH)
        if local == expected:
            log(f"Local SDE already at expected MD5; nothing to do ({SDE_PATH})")
            return 0
        log(f"Local MD5 ({local}) != expected; refetching.")

    download_and_decompress(expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
