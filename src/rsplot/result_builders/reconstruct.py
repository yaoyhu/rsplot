"""Reconstructed-grid JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.common import (
    grid_per_admin_stats,
    grid_stats,
    serialize_region,
    top_hotspots,
)
from rsplot.stats import round_finite

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.reconstruct import ReconstructData


def build_reconstruct_result(
    *,
    region: RegionInfo,
    data: ReconstructData,
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    vmin: float,
    vmax: float,
    output: str,
) -> dict[str, Any]:
    """Build the stable JSON sidecar payload for a reconstructed grid."""
    stats = grid_stats(
        LON,
        LAT,
        grid,
        region,
        valid_key="n_valid",
        total_key="n_region_cells",
    )
    stats.update(
        {
            "n_source_cells": int(data.n_source_cells),
            "n_source_valid": int(data.n_source_valid),
            "n_output_cells": int(data.n_output_cells),
            "n_output_valid": int(data.n_output_valid),
        }
    )
    result: dict[str, Any] = {
        "command": "reconstruct",
        "mode": "reconstruct",
        "image": output,
        "region": serialize_region(region),
        "variable": data.variable,
        "label": data.label,
        "unit": data.unit,
        "reconstruct": {
            "source": "reconstruct",
            "datetime": data.datetime,
            "timezone": data.timezone,
            "archive_datetime": data.archive_datetime,
            "archive_timezone": data.archive_timezone,
            "source_file": data.source_file,
            "native_resolution_deg": round_finite(data.native_resolution_deg),
            "output_resolution_deg": round_finite(data.output_resolution_deg),
        },
        "vrange": {
            "vmin": round_finite(vmin),
            "vmax": round_finite(vmax),
        },
        "stats": stats,
    }

    sub_gdf = region.sub_boundary_gdf
    if sub_gdf is not None and len(sub_gdf) > 0:
        result["spatial_summary"] = grid_per_admin_stats(
            LON,
            LAT,
            grid,
            sub_gdf,
        )
        result["hotspots"] = top_hotspots(LON, LAT, grid, sub_gdf, n=5)

    return result
