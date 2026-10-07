"""Per-administrative-unit FNR summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.stats import round_finite

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo


def fnr_regime(
    mean_fnr: float, voc_threshold: float, nox_threshold: float
) -> str:
    """Classify a mean FNR with the command's regime thresholds."""
    if mean_fnr < voc_threshold:
        return "voc_limited"
    if mean_fnr <= nox_threshold:
        return "transition"
    return "nox_limited"


def fnr_member_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    fnr: np.ndarray,
    region: RegionInfo,
    *,
    voc_threshold: float,
    nox_threshold: float,
) -> list[dict[str, Any]]:
    """Summarize each comma-selected member, keeping empty members."""
    from rsplot.geo.gridding import region_grid_mask

    rows: list[dict[str, Any]] = []
    for member in region.members:
        finite = fnr[region_grid_mask(LON, LAT, member.geometry)]
        finite = finite[np.isfinite(finite)]
        mean_fnr = float(np.mean(finite)) if len(finite) else None
        rows.append(
            {
                "name": member.qualified_name or member.name,
                "level": member.administrative_level or member.level,
                "n": len(finite),
                "mean": None if mean_fnr is None else round_finite(mean_fnr),
                "category": (
                    None
                    if mean_fnr is None
                    else fnr_regime(mean_fnr, voc_threshold, nox_threshold)
                ),
            }
        )
    return rows


def fnr_per_admin_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    fnr: np.ndarray,
    areas_gdf: gpd.GeoDataFrame,
    *,
    voc_threshold: float,
    nox_threshold: float,
) -> list[dict[str, Any]]:
    """Build per-admin-unit mean FNR and dominant regime summaries."""
    from shapely import contains_xy

    rows: list[dict[str, Any]] = []
    for _, row in areas_gdf.iterrows():
        mask = contains_xy(row.geometry, LON, LAT)
        finite = fnr[mask]
        finite = finite[np.isfinite(finite)]
        if len(finite) == 0:
            continue
        mean_fnr = float(np.mean(finite))
        regime = fnr_regime(mean_fnr, voc_threshold, nox_threshold)
        rows.append(
            {
                "name": row["name"],
                "n_pixels": len(finite),
                "mean_fnr": round_finite(mean_fnr),
                "median_fnr": round_finite(np.median(finite)),
                "regime": regime,
                "voc_limited_pct": round(
                    100 * float((finite < voc_threshold).mean()),
                    1,
                ),
                "nox_limited_pct": round(
                    100 * float((finite > nox_threshold).mean()),
                    1,
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["mean_fnr"] is None,
            row["mean_fnr"] or 1e9,
        )
    )
    return rows
