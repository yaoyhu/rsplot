"""FNR JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.fnr import FNR_DISPLAY_MAX, FNR_NOX_LIMIT, FNR_VOC_LIMIT
from rsplot.result_builders.common import serialize_region
from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.fnr import FnrResult
    from rsplot.geo.boundaries import RegionInfo


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


def build_fnr_result(
    *,
    region: RegionInfo,
    fnr_out: FnrResult,
    res: float,
    output: str,
    voc_threshold: float = FNR_VOC_LIMIT,
    nox_threshold: float = FNR_NOX_LIMIT,
    display_max: float = FNR_DISPLAY_MAX,
) -> dict[str, Any]:
    """Build the stable JSON sidecar for an FNR run."""
    from shapely import contains_xy

    from rsplot.fnr import regime_percentages, validate_fnr_thresholds

    voc_threshold, nox_threshold, display_max = validate_fnr_thresholds(
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
    )
    fnr = fnr_out.fnr
    region_mask = contains_xy(region.geometry, fnr_out.LON, fnr_out.LAT)
    total_region_pixels = int(region_mask.sum())
    n_valid_fnr = int(np.isfinite(fnr).sum())
    coverage_pct = (
        round(100 * n_valid_fnr / total_region_pixels, 3)
        if total_region_pixels
        else 0.0
    )
    both_valid_days = np.minimum(
        fnr_out.n_valid_hcho,
        fnr_out.n_valid_no2,
    )
    covered = both_valid_days[(both_valid_days > 0) & region_mask]
    coverage_days = {
        "min": int(covered.min()) if len(covered) else 0,
        "max": int(covered.max()) if len(covered) else 0,
        "mean": round(float(covered.mean()), 1) if len(covered) else 0.0,
    }
    diagnostic_masks = {
        name: mask & region_mask
        for name, mask in fnr_out.diagnostic_masks.items()
    }
    mask_diagnostics = {
        "total_region_pixels": total_region_pixels,
        "coverage_ge_n_min_pixels": int(diagnostic_masks["coverage_ok"].sum()),
        "no2_ge_threshold_pixels": int(diagnostic_masks["no2_ok"].sum()),
        "hcho_nonnegative_pixels": int(diagnostic_masks["hcho_ok"].sum()),
        "final_valid_pixels": n_valid_fnr,
    }

    result: dict[str, Any] = {
        "command": "fnr",
        "image": output,
        "region": serialize_region(region),
        "window": {
            "start": fnr_out.dates_requested[0],
            "end": fnr_out.dates_requested[-1],
            "n_days_requested": len(fnr_out.dates_requested),
            "n_days_found_no2": len(fnr_out.dates_found_no2),
            "n_days_found_hcho": len(fnr_out.dates_found_hcho),
            "dates_failed_no2": fnr_out.dates_failed_no2,
            "dates_failed_hcho": fnr_out.dates_failed_hcho,
        },
        "params": {
            "n_min": fnr_out.n_min,
            "no2_min_column": fnr_out.no2_min_column,
            "voc_threshold": voc_threshold,
            "nox_threshold": nox_threshold,
            "display_max": display_max,
            "resolution_deg": res,
        },
        "stats": {
            "grid_shape": list(fnr.shape),
            "coverage_pct": coverage_pct,
            "valid_pixels": n_valid_fnr,
            "total_region_pixels": total_region_pixels,
            "coverage_days": coverage_days,
            "mask_diagnostics": mask_diagnostics,
            **basic_stats(fnr),
        },
        "regime_pct": regime_percentages(
            fnr,
            voc_threshold=voc_threshold,
            nox_threshold=nox_threshold,
        ),
        "mean_fields": {
            "hcho_mean_raw_stats": basic_stats(fnr_out.hcho_mean),
            "no2_mean_raw_stats": basic_stats(fnr_out.no2_mean),
            "hcho_mean_filled_stats": basic_stats(fnr_out.hcho_mean_filled),
            "no2_mean_filled_stats": basic_stats(fnr_out.no2_mean_filled),
        },
    }

    sub_gdf = region.sub_boundary_gdf
    if sub_gdf is not None and len(sub_gdf) > 0:
        result["city_ranking"] = fnr_per_admin_stats(
            fnr_out.LON,
            fnr_out.LAT,
            fnr,
            sub_gdf,
            voc_threshold=voc_threshold,
            nox_threshold=nox_threshold,
        )

    return result
