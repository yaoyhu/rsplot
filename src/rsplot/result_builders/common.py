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
    if region.members:
        result["members"] = [
            serialize_member(member) for member in region.members
        ]
    return result


def serialize_member(member: RegionInfo) -> dict[str, Any]:
    """Identify a selected member with its canonical, qualified name."""
    result = serialize_region(member)
    result["name"] = member.qualified_name or member.name
    result.setdefault(
        "administrative_level", member.administrative_level or member.level
    )
    return result


def member_basic_stats(values: np.ndarray) -> dict[str, Any]:
    """Explicit null summaries retain members with no valid observations."""
    result = basic_stats(values)
    if result:
        return result
    return {
        "n": 0,
        **dict.fromkeys(
            ("min", "max", "mean", "median", "p10", "p25", "p75", "p90")
        ),
    }


def grid_member_stats(
    lon: np.ndarray,
    lat: np.ndarray,
    grid: np.ndarray,
    region: RegionInfo,
) -> list[dict[str, Any]]:
    """Select each member on the same statistical grid, never sum overlaps."""
    from rsplot.geo.gridding import mask_to_region

    result = []
    for member in region.members:
        selected = mask_to_region(lon, lat, grid, member.geometry)
        stats = grid_stats(
            lon,
            lat,
            selected,
            member,
            valid_key="valid_region_pixels",
            total_key="total_region_pixels",
        )
        stats.update(member_basic_stats(selected))
        result.append({"region": serialize_member(member), "stats": stats})
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


def grid_boundary_policy(
    lon: np.ndarray,
    lat: np.ndarray,
    display_grid: np.ndarray,
    region: RegionInfo,
) -> dict[str, Any]:
    """Describe distinct display and statistics spatial selection rules."""
    from rsplot.geo.gridding import region_grid_mask
    from rsplot.geo.processing import region_cell_mask

    visible = np.isfinite(display_grid) & region_cell_mask(
        lon, lat, region.geometry
    )
    inside = region_grid_mask(lon, lat, region.geometry)
    return {
        "statistics": {
            "selection": "grid_center_strictly_inside",
            "weighting": "equal_cells",
            "coverage": "valid_center_count / total_center_count",
        },
        "display": {
            "selection": "valid_cells_intersecting_region",
            "clip": "administrative_geometry",
            "n_valid_intersecting_cells": int(visible.sum()),
            "n_cells_with_centers_outside": int((visible & ~inside).sum()),
        },
    }
