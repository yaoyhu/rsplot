"""The ``satellite`` grid layer of a result sidecar."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.common import (
    grid_member_stats,
    grid_per_admin_stats,
    top_hotspots,
)
from rsplot.result_builders.envelope import (
    capped,
    coverage_block,
    coverage_flags,
    flag,
    stats_block,
    subdivision_level,
)

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo


@dataclass
class SatelliteInputs:
    """Everything prepare_raster knows about the statistical grid."""

    prod_info: ProductInfo
    lon: np.ndarray
    lat: np.ndarray
    grid: np.ndarray
    counted: np.ndarray
    time: dict[str, Any]
    data_root: str
    metadata: list[dict[str, Any]]
    method: dict[str, Any]
    valid_days: np.ndarray | None = None
    days: dict[str, Any] | None = None
    extra_flags: list[dict[str, Any]] = field(default_factory=list)


def collect_provenance(
    metadata: list[dict[str, Any]], data_root: str
) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    """Gather input files, failures and versions from reader metadata."""
    files: set[str] = set()
    failed: dict[str, str] = {}
    versions: dict[str, set[str]] = {}

    def relative(path: str) -> str:
        try:
            relpath = os.path.relpath(path, data_root)
        except ValueError:
            return path
        return path if relpath.startswith("..") else relpath

    def add_version(kind: str, value: Any) -> None:
        if value:
            versions.setdefault(kind, set()).add(str(value))

    def visit(meta: dict[str, Any]) -> None:
        for path in meta.get("source_files", []):
            files.add(relative(path))
        for path, reason in meta.get("failed_files", {}).items():
            failed[relative(path)] = reason
        for value in meta.get("processor_versions", []):
            add_version("processor", value)
        for value in meta.get("product_versions", []):
            add_version("product", value)
        if "file" in meta:
            files.add(relative(meta["file"]))
            if "error" in meta:
                failed[relative(meta["file"])] = meta["error"]
            add_version("product", meta.get("product_version"))
        for scan in meta.get("scans", []):
            visit(scan)

    for meta in metadata:
        visit(meta)
    return (
        sorted(files),
        dict(sorted(failed.items())),
        {kind: sorted(values) for kind, values in versions.items()},
    )


def build_satellite_layer(
    inputs: SatelliteInputs,
    region: RegionInfo,
    *,
    data: str | None,
    layer_id: str = "satellite",
    coverage_checks: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the satellite layer and the quality flags it raises.

    ``coverage_checks=False`` skips regional coverage flags for input layers
    whose own coverage is not the result (e.g. FNR's NO2 and HCHO means).
    """
    prod = inputs.prod_info
    files, failed, versions = collect_provenance(
        inputs.metadata, inputs.data_root
    )
    valid = np.isfinite(inputs.grid) & inputs.counted
    coverage = coverage_block(
        int(valid.sum()), int(inputs.counted.sum()), "cells"
    )
    time = dict(inputs.time)
    if inputs.days is not None:
        time["days"] = inputs.days

    sub_gdf = region.sub_boundary_gdf
    has_subdivisions = sub_gdf is not None and len(sub_gdf) > 0
    by_admin = []
    if has_subdivisions:
        level = subdivision_level(region)
        by_admin = [
            {
                "name": row["name"],
                "level": level,
                "n": int(row["n_pixels"]),
                "mean": row["mean"],
                "min": row["min"],
                "max": row["max"],
            }
            for row in grid_per_admin_stats(
                inputs.lon, inputs.lat, inputs.grid, sub_gdf
            )
        ]
    hotspots = top_hotspots(
        inputs.lon,
        inputs.lat,
        inputs.grid,
        sub_gdf if has_subdivisions else None,
        n=10,
    )
    layer: dict[str, Any] = {
        "id": layer_id,
        "kind": "grid",
        "quantity": {
            "name": prod.quantity,
            "unit": prod.unit,
            "scale": prod.unit_scale,
            "label": prod.colorbar_label,
        },
        "time": time,
        "source": {
            "sensor": prod.sensor,
            "processing": (
                prod.processing or "offl" if prod.sensor == "tropomi" else None
            ),
            "data_root": inputs.data_root,
            "files_total": len(files),
            "failed_files": failed,
            "versions": versions,
        },
        "method": inputs.method,
        "coverage": coverage,
        "stats": stats_block(inputs.grid[inputs.counted]),
        "by_admin": by_admin,
        "extremes": capped(
            [
                {
                    "lon": item["lon"],
                    "lat": item["lat"],
                    "value": item["value"],
                    "admin": item["city"],
                }
                for item in hotspots
            ],
            coverage["valid"],
            "value_desc",
        ),
        "data": data,
    }
    if region.members:
        layer["by_member"] = [
            {
                "name": row["region"]["name"],
                "level": row["region"].get("administrative_level")
                or row["region"]["level"],
                "n": int(row["stats"]["n"]),
                "mean": row["stats"]["mean"],
                "min": row["stats"]["min"],
                "max": row["stats"]["max"],
            }
            for row in grid_member_stats(
                inputs.lon, inputs.lat, inputs.grid, region
            )
        ]

    flags = coverage_flags(layer_id, coverage) if coverage_checks else []
    days = inputs.days
    if days is not None and days["found"] < days["requested"]:
        flags.append(
            flag(
                "missing_days",
                "warning",
                layer=layer_id,
                evidence={
                    "requested": days["requested"],
                    "found": days["found"],
                    "failed": days["failed"],
                },
            )
        )
    if days is not None and inputs.valid_days is not None:
        observed = inputs.valid_days[inputs.counted & (inputs.valid_days > 0)]
        median = float(np.median(observed)) if observed.size else 0.0
        if median < days["n_min"]:
            flags.append(
                flag(
                    "few_valid_days",
                    "warning",
                    layer=layer_id,
                    evidence={
                        "median_valid_days": median,
                        "n_min": days["n_min"],
                    },
                )
            )
    if failed:
        flags.append(
            flag(
                "failed_files",
                "warning",
                layer=layer_id,
                evidence={"count": len(failed)},
            )
        )
    flags.extend(inputs.extra_flags)
    return layer, flags
