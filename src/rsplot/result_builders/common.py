"""Shared serialization and spatial-summary helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo


def serialize_region(region: RegionInfo) -> dict[str, Any]:
    """Serialize a region identically across every result type."""
    result = {
        "name": region.name,
        "level": region.level,
        "extent": [round(value, 3) for value in region.extent],
    }
    if region.administrative_level not in (None, region.level):
        result["administrative_level"] = region.administrative_level
    if region.subdivision_level is not None:
        result["subdivision_level"] = region.subdivision_level
    return result


def grid_per_admin_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    areas_gdf: gpd.GeoDataFrame,
) -> list[dict[str, Any]]:
    """Aggregate a grid over each supplied administrative geometry."""
    from shapely import contains_xy

    rows: list[dict[str, Any]] = []
    for _, row in areas_gdf.iterrows():
        mask = contains_xy(row.geometry, LON, LAT)
        finite = grid[mask]
        finite = finite[np.isfinite(finite)]
        if len(finite) == 0:
            continue
        rows.append(
            {
                "name": row["name"],
                "n_pixels": len(finite),
                "mean": round_finite(np.mean(finite)),
                "max": round_finite(np.max(finite)),
                "min": round_finite(np.min(finite)),
            }
        )
    rows.sort(key=lambda row: (row["mean"] is None, -(row["mean"] or 0)))
    return rows


def top_hotspots(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    areas_gdf: gpd.GeoDataFrame | None,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Return the highest finite grid cells with admin-unit attribution."""
    from shapely.geometry import Point

    flat = grid.ravel()
    lon_flat = LON.ravel()
    lat_flat = LAT.ravel()
    finite_indices = np.flatnonzero(np.isfinite(flat))
    count = min(max(n, 0), len(finite_indices))
    if count == 0:
        return []

    finite_values = flat[finite_indices]
    if count < len(finite_indices):
        selected = np.argpartition(finite_values, -count)[-count:]
    else:
        selected = np.arange(len(finite_indices))
    selected = selected[np.argsort(finite_values[selected])[::-1]]
    order = finite_indices[selected]

    hotspots: list[dict[str, Any]] = []
    for index in order:
        value = flat[index]
        lon = float(lon_flat[index])
        lat = float(lat_flat[index])
        area_name = None
        if areas_gdf is not None and len(areas_gdf) > 0:
            point = Point(lon, lat)
            hit = areas_gdf[areas_gdf.geometry.contains(point)]
            if len(hit) > 0:
                area_name = hit.iloc[0]["name"]
            else:
                distances = areas_gdf.geometry.distance(point)
                area_name = areas_gdf.iloc[int(distances.argmin())]["name"]
        hotspots.append(
            {
                "lon": round(lon, 3),
                "lat": round(lat, 3),
                "value": round_finite(value),
                # Compatibility key retained for existing JSON consumers.
                "city": area_name,
            }
        )
        if len(hotspots) >= n:
            break
    return hotspots


def grid_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    region: RegionInfo,
    *,
    valid_key: str,
    total_key: str,
) -> dict[str, Any]:
    """Build the common region-aware grid statistics block."""
    from rsplot.geo.gridding import grid_coverage_in_region

    coverage, n_valid, total = grid_coverage_in_region(
        LON,
        LAT,
        grid,
        region.geometry,
    )
    return {
        "grid_shape": list(grid.shape),
        "coverage_pct": coverage,
        valid_key: n_valid,
        total_key: total,
        **basic_stats(grid),
    }
