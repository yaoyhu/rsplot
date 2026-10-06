"""Per-administrative-unit FNR summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.stats import round_finite

if TYPE_CHECKING:
    import geopandas as gpd


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
        if mean_fnr < voc_threshold:
            regime = "voc_limited"
        elif mean_fnr <= nox_threshold:
            regime = "transition"
        else:
            regime = "nox_limited"
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
