"""Fingerprint a layer's input files without listing them."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from rsplot.temporal import DEFAULT_INPUT_TIMEZONE


def input_fingerprint(data_root: str, paths: Iterable[str]) -> dict[str, Any]:
    """Return ``inputs_digest`` and ``data_as_of`` for a ``source`` block.

    The digest hashes each input's name relative to ``data_root``, size and
    modification time, so a later run can tell whether the same request
    now reads different files (an NRTI day that gained granules). Paths
    may be absolute or relative to ``data_root``; files that no longer
    exist are skipped. ``data_as_of`` is the latest modification time.
    """
    rows: list[str] = []
    latest: int | None = None
    for path in set(paths):
        full = os.path.join(data_root, path)
        try:
            stat = os.stat(full)
        except OSError:
            continue
        name = os.path.relpath(full, data_root)
        rows.append(f"{name}\t{stat.st_size}\t{stat.st_mtime_ns}")
        latest = max(latest or 0, stat.st_mtime_ns)
    digest = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()
    return {
        "inputs_digest": f"sha256:{digest}",
        "data_as_of": None if latest is None else _china_time(latest),
    }


def combined_fingerprint(sources: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Fingerprint a layer derived from other layers' ``source`` blocks."""
    sources = list(sources)
    digest = hashlib.sha256(
        "\n".join(source["inputs_digest"] for source in sources).encode()
    ).hexdigest()
    stamps = [s["data_as_of"] for s in sources if s["data_as_of"]]
    return {
        "inputs_digest": f"sha256:{digest}",
        "data_as_of": max(stamps, default=None),
    }


def _china_time(mtime_ns: int) -> str:
    moment = datetime.fromtimestamp(
        mtime_ns / 1e9, ZoneInfo(DEFAULT_INPUT_TIMEZONE)
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%S")
