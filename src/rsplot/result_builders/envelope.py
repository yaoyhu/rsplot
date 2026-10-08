"""Shared result-sidecar envelope; see docs/result-schema.md."""

from __future__ import annotations

import json
import math
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import numpy as np

from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo

STAT_KEYS = ("mean", "std", "min", "p10", "p25", "median", "p75", "p90")
LOW_COVERAGE = 0.30
VERY_LOW_COVERAGE = 0.10
EXTREMES_LIMIT = 10
# Sidecar times are China time whatever the host clock's zone is.
CHINA_TIME = ZoneInfo("Asia/Shanghai")
# Subdivision drawn inside each region level when none is configured.
SUBDIVISION_LEVEL = {
    "country": "province",
    "key_region": "city",
    "province": "city",
    "city": "county",
    "county": "township",
}


def rsplot_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("rsplot")
    except PackageNotFoundError:
        return "unknown"


# Characters a POSIX shell treats specially; other text, such as Chinese
# region names, is written as typed.
SHELL_SPECIAL = re.compile(r"[\s'\"\\$`!*?;&|<>()\[\]{}#~]")


def command_line() -> str:
    """The command as received on one line, quoting only where needed."""
    words = ["rsplot", *(str(arg) for arg in sys.argv[1:])]
    return " ".join(
        shlex.quote(word) if not word or SHELL_SPECIAL.search(word) else word
        for word in words
    )


def region_block(
    region: RegionInfo, radius: dict[str, Any] | None = None
) -> dict[str, Any]:
    administrative = region.geometry_kind == "administrative"
    block = {
        "name": region.name,
        "level": region.level if administrative else "station_radius",
        "kind": "administrative" if administrative else "station_radius",
        "bbox": [round(float(value), 3) for value in region.extent],
        "members": [
            {
                "name": member.name,
                "qualified_name": member.qualified_name,
                "level": member.administrative_level or member.level,
            }
            for member in region.members
        ],
    }
    if radius is not None:
        block["radius"] = radius
    return block


def subdivision_level(region: RegionInfo) -> str:
    return region.subdivision_level or SUBDIVISION_LEVEL.get(
        region.level, "subdivision"
    )


def stats_block(values: np.ndarray) -> dict[str, Any]:
    """Stable statistics over finite values; explicit nulls when empty."""
    summary = basic_stats(values)
    if not summary:
        return {"n": 0, **dict.fromkeys(("max", *STAT_KEYS))}
    finite = np.asarray(values)[np.isfinite(values)]
    return {
        "n": int(summary["n"]),
        "mean": summary["mean"],
        "std": round_finite(np.std(finite)),
        "min": summary["min"],
        "p10": summary["p10"],
        "p25": summary["p25"],
        "median": summary["median"],
        "p75": summary["p75"],
        "p90": summary["p90"],
        "max": summary["max"],
    }


def coverage_block(valid: int, total: int, unit: str) -> dict[str, Any]:
    return {
        "valid": int(valid),
        "total": int(total),
        "fraction": round(valid / total, 3) if total else None,
        "unit": unit,
    }


def capped(items: list[dict], total: int, order: str) -> dict[str, Any]:
    kept = items[:EXTREMES_LIMIT]
    return {
        "items": kept,
        "total": int(total),
        "truncated": int(total) > len(kept),
        "order": order,
    }


def flag(
    code: str,
    severity: str,
    *,
    evidence: dict[str, Any],
    layer: str | None = None,
) -> dict[str, Any]:
    """A documented condition with the counts that triggered it, no prose."""
    result: dict[str, Any] = {"code": code, "severity": severity}
    if layer is not None:
        result["layer"] = layer
    result["evidence"] = evidence
    return result


def coverage_flags(layer: str, coverage: dict[str, Any]) -> list[dict]:
    """Flag grids whose regional statistics rest on few valid cells."""
    fraction = coverage["fraction"]
    evidence = {
        "valid": coverage["valid"],
        "total": coverage["total"],
        "fraction": fraction,
    }
    if coverage["valid"] == 0:
        return [
            flag(
                "no_valid_data",
                "critical",
                layer=layer,
                evidence=evidence,
            )
        ]
    if fraction is not None and fraction < VERY_LOW_COVERAGE:
        return [
            flag(
                "very_low_coverage",
                "critical",
                layer=layer,
                evidence={**evidence, "threshold": VERY_LOW_COVERAGE},
            )
        ]
    if fraction is not None and fraction < LOW_COVERAGE:
        return [
            flag(
                "low_coverage",
                "warning",
                layer=layer,
                evidence={**evidence, "threshold": LOW_COVERAGE},
            )
        ]
    return []


def success_envelope(
    *,
    command: str,
    request: str,
    region: RegionInfo | None,
    layers: list[dict],
    flags: list[dict],
    render: dict,
    artifacts: dict,
    relations: dict | None = None,
    radius: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "command": command,
        "rsplot_version": rsplot_version(),
        "generated_at": datetime.now(CHINA_TIME).isoformat("T", "seconds"),
        "request": request,
        "region": None if region is None else region_block(region, radius),
        "layers": layers,
        "relations": relations or {},
        "quality": {"flags": flags},
        "render": render,
        "artifacts": artifacts,
    }


def sidecar_path(output: str) -> str:
    return str(Path(output).with_suffix(".json"))


def _jsonable(value: Any) -> Any:
    """Convert numpy scalars and non-finite floats; JSON has no NaN."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_sidecar(payload: dict[str, Any], path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            _jsonable(payload),
            file,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    return path
