"""Shared ``rsplot.result/2`` envelope; see docs/result-schema.md."""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    from rsplot.errors import RsplotError
    from rsplot.geo.boundaries import RegionInfo

SCHEMA = "rsplot.result/2"
STAT_KEYS = ("mean", "std", "min", "p10", "p25", "median", "p75", "p90")
SEVERITY_GRADE = {"info": 0, "warning": 1, "critical": 2}
GRADES = ("good", "limited", "unreliable")
LOW_COVERAGE = 0.30
VERY_LOW_COVERAGE = 0.10
EXTREMES_LIMIT = 10
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


def cli_argv() -> list[str]:
    """Arguments after the program name, exactly as received."""
    return [str(arg) for arg in sys.argv[1:]]


def option_given(*names: str) -> bool:
    """Whether any spelling of an option appears on the command line."""
    for arg in cli_argv():
        for name in names:
            if arg == name or arg.startswith(f"{name}="):
                return True
    return False


def resolved(
    value: Any, source: str, detail: str | None = None
) -> dict[str, Any]:
    entry = {"value": value, "source": source}
    if detail is not None:
        entry["detail"] = detail
    return entry


def request_block(values: dict[str, dict[str, Any] | None]) -> dict:
    return {
        "argv": cli_argv(),
        "resolved": {
            key: entry for key, entry in values.items() if entry is not None
        },
    }


def region_block(
    region: RegionInfo, radius: dict[str, Any] | None = None
) -> dict[str, Any]:
    administrative = region.geometry_kind == "administrative"
    block = {
        "name": region.name,
        "level": region.level if administrative else "station_radius",
        "kind": "administrative" if administrative else "station_radius",
        "extent": [round(float(value), 3) for value in region.extent],
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
    message: str,
    *,
    layer: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if layer is not None:
        result["layer"] = layer
    if evidence is not None:
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
                "No valid value falls on a statistics cell of the region; "
                "regional statistics are empty.",
                layer=layer,
                evidence=evidence,
            )
        ]
    if fraction is not None and fraction < VERY_LOW_COVERAGE:
        return [
            flag(
                "very_low_coverage",
                "critical",
                f"Only {fraction:.1%} of region cells have a valid value; "
                "regional statistics are not representative.",
                layer=layer,
                evidence={**evidence, "threshold": VERY_LOW_COVERAGE},
            )
        ]
    if fraction is not None and fraction < LOW_COVERAGE:
        return [
            flag(
                "low_coverage",
                "warning",
                f"Only {fraction:.1%} of region cells have a valid value; "
                "treat regional statistics with care.",
                layer=layer,
                evidence={**evidence, "threshold": LOW_COVERAGE},
            )
        ]
    return []


def quality_block(flags: list[dict]) -> dict[str, Any]:
    worst = max(
        (SEVERITY_GRADE[item["severity"]] for item in flags), default=0
    )
    return {"grade": GRADES[worst], "flags": flags}


def success_envelope(
    *,
    command: str,
    request: dict,
    region: RegionInfo | None,
    layers: list[dict],
    flags: list[dict],
    render: dict | None,
    artifacts: dict,
    relations: dict | None = None,
    radius: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "ok",
        "command": command,
        "rsplot_version": rsplot_version(),
        "generated_at": datetime.now().astimezone().isoformat("T", "seconds"),
        "request": request,
        "region": None if region is None else region_block(region, radius),
        "layers": layers,
        "relations": relations or {},
        "quality": quality_block(flags),
        "render": render,
        "artifacts": artifacts,
        "error": None,
    }


def error_envelope(
    *,
    command: str,
    request: dict,
    error: RsplotError,
    sidecar: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": error.code, "message": str(error)}
    if error.option:
        payload["option"] = error.option
    if error.details:
        payload["details"] = error.details
    return {
        "schema": SCHEMA,
        "status": "error",
        "command": command,
        "rsplot_version": rsplot_version(),
        "generated_at": datetime.now().astimezone().isoformat("T", "seconds"),
        "request": request,
        "region": None,
        "layers": [],
        "relations": {},
        "quality": {"grade": "failed", "flags": []},
        "render": None,
        "artifacts": {"image": None, "sidecar": sidecar, "data": []},
        "error": payload,
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
