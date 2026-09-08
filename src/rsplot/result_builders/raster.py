"""Raster JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.common import (
    grid_boundary_policy,
    grid_per_admin_stats,
    grid_stats,
    serialize_region,
    top_hotspots,
)
from rsplot.stats import round_finite

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo


def build_raster_result(
    *,
    region: RegionInfo,
    product: str,
    date: str,
    prod_info: ProductInfo,
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    swath_meta: dict[str, Any],
    vmin: float,
    vmax: float,
    output: str,
    display_grid: np.ndarray | None = None,
    display_lon: np.ndarray | None = None,
    display_lat: np.ndarray | None = None,
    window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable JSON sidecar payload for a raster run."""
    result: dict[str, Any] = {
        "command": "raster",
        "image": output,
        "region": serialize_region(region),
        "product": product,
        "date": date,
        "unit": prod_info.colorbar_label,
        "vrange": {
            "vmin": round_finite(vmin),
            "vmax": round_finite(vmax),
        },
        "swath": swath_meta,
        "stats": grid_stats(
            LON,
            LAT,
            grid,
            region,
            valid_key="valid_region_pixels",
            total_key="total_region_pixels",
        ),
    }
    if prod_info.sensor == "gems":
        result["sensor"] = "gems"
        result["quantity"] = prod_info.quantity
        result["statistics_basis"] = "unfilled_unsmoothed_grid"
        result["input_timezone"] = "Asia/Shanghai"
    if window is not None:
        result["window"] = window

    if display_grid is not None:
        result["boundary_policy"] = grid_boundary_policy(
            LON if display_lon is None else display_lon,
            LAT if display_lat is None else display_lat,
            display_grid,
            region,
        )

    if (
        display_grid is not None
        and swath_meta.get("display_support") == "fixed_analysis_valid_cells"
    ):
        result["boundary_policy"]["display"]["clip"] = (
            "administrative_geometry_and_fixed_analysis_valid_cells"
        )
        result["boundary_policy"]["display"]["grid_shape"] = list(
            display_grid.shape
        )

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
