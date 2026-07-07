"""Structured result builder and emitter for agent-friendly output.

Every CLI command writes a sidecar JSON file next to the output image
({output}.json). The calling agent reads this file directly instead of
parsing stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.fnr import FNR_DISPLAY_MAX, FNR_NOX_LIMIT, FNR_VOC_LIMIT

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.fnr import FnrResult
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo
    from rsplot.readers.era5_wind import WindFieldData
    from rsplot.readers.forecast import ForecastData
    from rsplot.readers.guokong import StationData


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _round(x: float, n: int = 2) -> float:
    """Round, keeping NaN as None for JSON."""
    if not np.isfinite(x):
        return None  # type: ignore[return-value]
    return round(float(x), n)


def _basic_stats(values: np.ndarray, n: int = 2) -> dict[str, float]:
    """min/max/mean/median + p10/p25/p75/p90 over finite values."""
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return {}
    return {
        "n": int(len(finite)),
        "min": _round(np.min(finite), n),
        "max": _round(np.max(finite), n),
        "mean": _round(np.mean(finite), n),
        "median": _round(np.median(finite), n),
        "p10": _round(np.percentile(finite, 10), n),
        "p25": _round(np.percentile(finite, 25), n),
        "p75": _round(np.percentile(finite, 75), n),
        "p90": _round(np.percentile(finite, 90), n),
    }


# ---------------------------------------------------------------------------
# Raster
# ---------------------------------------------------------------------------
def _grid_per_city_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    cities_gdf: gpd.GeoDataFrame,
) -> list[dict[str, Any]]:
    """Per-city aggregation on a gridded raster."""
    from shapely.vectorized import contains

    rows: list[dict[str, Any]] = []
    for _, row in cities_gdf.iterrows():
        mask = contains(row.geometry, LON, LAT)
        sub = grid[mask]
        finite = sub[np.isfinite(sub)]
        if len(finite) == 0:
            continue
        rows.append(
            {
                "name": row["name"],
                "n_pixels": int(len(finite)),
                "mean": _round(np.mean(finite)),
                "max": _round(np.max(finite)),
                "min": _round(np.min(finite)),
            }
        )
    rows.sort(key=lambda r: (r["mean"] is None, -(r["mean"] or 0)))
    return rows


def _top_hotspots(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    cities_gdf: gpd.GeoDataFrame | None,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Top-N highest finite pixels, each tagged with its containing city."""
    from shapely.geometry import Point

    flat = grid.ravel()
    lon_flat = LON.ravel()
    lat_flat = LAT.ravel()
    order = np.argsort(flat)[::-1]

    hotspots: list[dict[str, Any]] = []
    for i in order:
        v = flat[i]
        if not np.isfinite(v):
            continue
        lon, lat = float(lon_flat[i]), float(lat_flat[i])
        nearest_city = None
        if cities_gdf is not None and len(cities_gdf) > 0:
            pt = Point(lon, lat)
            hit = cities_gdf[cities_gdf.geometry.contains(pt)]
            if len(hit) > 0:
                nearest_city = hit.iloc[0]["name"]
            else:
                dists = cities_gdf.geometry.distance(pt)
                nearest_city = cities_gdf.iloc[int(dists.argmin())]["name"]
        hotspots.append(
            {
                "lon": round(lon, 3),
                "lat": round(lat, 3),
                "value": _round(v),
                "city": nearest_city,
            }
        )
        if len(hotspots) >= n:
            break
    return hotspots


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
    window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON sidecar payload for a raster run.

    ``window`` is None for single-day runs and a dict (start/end/
    n_days_requested/n_days_found/n_min/dates_failed/coverage_days) for
    window-mean runs.
    """
    from rsplot.geo.gridding import grid_coverage_in_region

    coverage_pct, n_valid_region, total_region_pixels = (
        grid_coverage_in_region(LON, LAT, grid, region.geometry)
    )

    result: dict[str, Any] = {
        "command": "raster",
        "image": output,
        "region": {
            "name": region.name,
            "level": region.level,
            "extent": [round(x, 3) for x in region.extent],
        },
        "product": product,
        "date": date,
        "unit": prod_info.colorbar_label,
        "vrange": {"vmin": _round(vmin), "vmax": _round(vmax)},
        "swath": swath_meta,
        "stats": {
            "grid_shape": list(grid.shape),
            "coverage_pct": coverage_pct,
            "valid_region_pixels": n_valid_region,
            "total_region_pixels": total_region_pixels,
            **_basic_stats(grid),
        },
    }
    if window is not None:
        result["window"] = window

    sub_gdf = region.sub_boundary_gdf
    if sub_gdf is not None and len(sub_gdf) > 0:
        result["spatial_summary"] = _grid_per_city_stats(LON, LAT, grid, sub_gdf)
        result["hotspots"] = _top_hotspots(LON, LAT, grid, sub_gdf, n=5)

    return result


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------
def build_forecast_result(
    *,
    region: RegionInfo,
    data: ForecastData,
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    vmin: float,
    vmax: float,
    output: str,
    station_data: StationData | None = None,
    station_datetime: str | None = None,
    station_threshold: float | None = None,
    station_unit: str = "",
    cities_gdf: gpd.GeoDataFrame | None = None,
) -> dict[str, Any]:
    """Build the JSON sidecar payload for a forecast run."""
    from rsplot.geo.gridding import grid_coverage_in_region

    coverage_pct, n_valid_region, total_region_pixels = (
        grid_coverage_in_region(LON, LAT, grid, region.geometry)
    )

    result: dict[str, Any] = {
        "command": "forecast",
        "mode": (
            "forecast_station_overlay"
            if station_data is not None
            else "forecast"
        ),
        "image": output,
        "region": {
            "name": region.name,
            "level": region.level,
            "extent": [round(x, 3) for x in region.extent],
        },
        "variable": data.variable,
        "label": data.label,
        "unit": data.unit,
        "forecast": {
            "source": "forecast",
            "init_datetime": data.init_datetime,
            "lead_hour": data.lead_hour,
            "valid_datetime": data.valid_datetime,
            "source_file": data.source_file,
        },
        "vrange": {"vmin": _round(vmin), "vmax": _round(vmax)},
        "stats": {
            "grid_shape": list(grid.shape),
            "coverage_pct": coverage_pct,
            "n_region_cells": total_region_pixels,
            "n_valid": n_valid_region,
            "n_read_cells": int(data.n_cells),
            "n_read_valid": int(data.n_valid),
            **_basic_stats(grid),
        },
    }

    if station_data is not None:
        station_block = build_station_result(
            region=region,
            data=station_data,
            datetime_str=station_datetime or data.valid_datetime,
            threshold=station_threshold,
            unit=station_unit,
            cities_gdf=cities_gdf,
            output=output,
        )
        for key in ("command", "image", "region"):
            station_block.pop(key, None)
        result["station"] = station_block

    sub_gdf = region.sub_boundary_gdf
    if sub_gdf is not None and len(sub_gdf) > 0:
        result["spatial_summary"] = _grid_per_city_stats(LON, LAT, grid, sub_gdf)
        result["hotspots"] = _top_hotspots(LON, LAT, grid, sub_gdf, n=5)

    return result


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------
def _attribute_stations_to_cities(
    lon: np.ndarray, lat: np.ndarray, cities_gdf: gpd.GeoDataFrame
) -> np.ndarray:
    """Return city name for each (lon, lat); empty string if none contain it."""
    return _attribute_stations_to_areas(lon, lat, cities_gdf)


def _attribute_stations_to_areas(
    lon: np.ndarray,
    lat: np.ndarray,
    areas_gdf: gpd.GeoDataFrame,
    name_field: str = "name",
) -> np.ndarray:
    """Return containing admin-unit name for each (lon, lat)."""
    from shapely.geometry import Point

    sindex = areas_gdf.sindex
    out = np.empty(len(lon), dtype=object)
    for i, (x, y) in enumerate(zip(lon, lat)):
        if not (np.isfinite(x) and np.isfinite(y)):
            out[i] = ""
            continue
        pt = Point(float(x), float(y))
        area = ""
        for idx in sindex.intersection((x, y, x, y)):
            if areas_gdf.iloc[idx].geometry.contains(pt):
                area = areas_gdf.iloc[idx][name_field]
                break
        out[i] = area
    return out


def _aqi_distribution(vals: np.ndarray) -> dict[str, int]:
    bounds = [0, 50, 100, 150, 200, 300, 500]
    labels = ["优", "良", "轻度", "中度", "重度", "严重"]
    dist: dict[str, int] = {}
    for i, label in enumerate(labels):
        lo, hi = bounds[i], bounds[i + 1]
        if i == 0:
            m = (vals >= lo) & (vals <= hi)
        else:
            m = (vals > lo) & (vals <= hi)
        dist[label] = int(m.sum())
    dist["爆表"] = int((vals > 500).sum())
    return dist


def _station_admin_level(region: RegionInfo) -> str | None:
    if region.level == "country":
        return "province"
    if region.level == "key_region":
        return "city"
    if region.level == "province":
        municipalities = {"北京市", "天津市", "上海市", "重庆市"}
        return "county" if region.name in municipalities else "city"
    if region.level == "city":
        return "county"
    return None


def _top_station_entries(
    *,
    vals: np.ndarray,
    ids: np.ndarray,
    lons: np.ndarray,
    lats: np.ndarray,
    area_names: np.ndarray | None,
    admin_level: str | None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    top_stations: list[dict[str, Any]] = []
    for i in np.argsort(vals)[::-1][:limit]:
        entry: dict[str, Any] = {
            "id": str(ids[i]),
            "value": _round(vals[i]),
            "lon": round(float(lons[i]), 3),
            "lat": round(float(lats[i]), 3),
        }
        if area_names is not None:
            entry["admin_level"] = admin_level
            entry["admin_name"] = area_names[i] or None
            # Backward-compatible alias for older consumers.
            entry["city"] = area_names[i] or None
        top_stations.append(entry)
    return top_stations


def _build_wind_block(
    wind: WindFieldData, stride: int
) -> dict[str, Any]:
    """Build machine-readable metadata for a plotted ERA5 wind layer."""
    step = max(1, stride)
    sample = np.s_[::step, ::step]
    sampled_valid = np.isfinite(wind.speed[sample])
    finite = np.isfinite(wind.speed)
    total = wind.n_cells

    mean_u = float(np.nanmean(wind.u))
    mean_v = float(np.nanmean(wind.v))
    direction_to = (np.degrees(np.arctan2(mean_u, mean_v)) + 360.0) % 360.0
    direction_from = (direction_to + 180.0) % 360.0

    max_flat_index = int(np.nanargmax(wind.speed))
    max_index = np.unravel_index(max_flat_index, wind.speed.shape)
    return {
        "source": "ERA5",
        "level": wind.level,
        "station_datetime": wind.station_datetime,
        "datetime_utc": wind.datetime_utc,
        "unit": wind.unit,
        "source_files": list(wind.source_files),
        "grid_shape": list(wind.speed.shape),
        "coverage_pct": (
            round(100 * int(finite.sum()) / total, 1) if total else 0.0
        ),
        "n_region_cells": int(total),
        "stride": step,
        "n_vectors_valid": int(finite.sum()),
        "n_arrows_plotted": int(sampled_valid.sum()),
        "u_stats": _basic_stats(wind.u),
        "v_stats": _basic_stats(wind.v),
        "speed_stats": _basic_stats(wind.speed),
        "resultant": {
            "mean_u": _round(mean_u),
            "mean_v": _round(mean_v),
            "direction_to_deg": _round(direction_to, 1),
            "wind_from_deg": _round(direction_from, 1),
        },
        "max_speed_location": {
            "lon": round(float(wind.lon[max_index]), 3),
            "lat": round(float(wind.lat[max_index]), 3),
            "speed": _round(wind.speed[max_index]),
        },
    }


def build_station_result(
    *,
    region: RegionInfo,
    data: StationData,
    datetime_str: str,
    threshold: float | None,
    unit: str,
    cities_gdf: gpd.GeoDataFrame | None,
    output: str,
    wind: WindFieldData | None = None,
    wind_stride: int | None = None,
) -> dict[str, Any]:
    valid = np.isfinite(data.values)
    vals = data.values[valid]
    lons = data.lon[valid]
    lats = data.lat[valid]
    ids = np.asarray(data.id)[valid]
    admin_gdf = (
        region.sub_boundary_gdf
        if region.sub_boundary_gdf is not None and len(region.sub_boundary_gdf) > 0
        else cities_gdf
    )
    admin_level = _station_admin_level(region)

    result: dict[str, Any] = {
        "command": "station",
        "image": output,
        "region": {
            "name": region.name,
            "level": region.level,
            "extent": [round(x, 3) for x in region.extent],
        },
        "datetime": datetime_str,
        "variable": data.var_name,
        "unit": unit or None,
        "threshold": threshold,
        "n_stations": int(data.n_stations),
        "n_valid": int(data.n_valid),
        "stats": _basic_stats(vals),
    }

    station_areas = None
    if admin_gdf is not None and len(admin_gdf) > 0 and len(vals) > 0:
        station_areas = _attribute_stations_to_areas(
            lons, lats, admin_gdf, region.sub_name_field
        )

    if len(vals) > 0:
        result["top_stations"] = _top_station_entries(
            vals=vals,
            ids=ids,
            lons=lons,
            lats=lats,
            area_names=station_areas,
            admin_level=admin_level,
            limit=10,
        )
        result["top_station_ids"] = [
            entry["id"] for entry in result["top_stations"]
        ]

    # Exceedance summary
    if threshold is not None and len(vals) > 0:
        exceed_mask = vals > threshold
        n_exceed = int(exceed_mask.sum())
        top_idx = np.argsort(vals)[::-1]
        top_stations: list[dict[str, Any]] = []
        for i in top_idx:
            if vals[i] <= threshold:
                break
            entry: dict[str, Any] = {
                "id": str(ids[i]),
                "value": _round(vals[i]),
                "lon": round(float(lons[i]), 3),
                "lat": round(float(lats[i]), 3),
            }
            if station_areas is not None:
                entry["admin_level"] = admin_level
                entry["admin_name"] = station_areas[i] or None
                # Backward-compatible alias for older consumers.
                entry["city"] = station_areas[i] or None
            top_stations.append(entry)
            if len(top_stations) >= 10:
                break
        result["exceedance"] = {
            "count": n_exceed,
            "rate_pct": round(100 * n_exceed / len(vals), 1),
            "top_stations": top_stations,
        }

    # AQI discrete distribution
    if data.var_name == "AQI" and len(vals) > 0:
        result["aqi_distribution"] = _aqi_distribution(vals)

    # Per-admin-unit ranking, exposed under the legacy city_ranking key.
    if station_areas is not None and len(vals) > 0:
        acc: dict[str, dict[str, Any]] = {}
        for i in range(len(vals)):
            c = station_areas[i]
            if not c:
                continue
            s = acc.setdefault(c, {"values": [], "n_exceed": 0})
            s["values"].append(float(vals[i]))
            if threshold is not None and vals[i] > threshold:
                s["n_exceed"] += 1
        ranking = []
        for city, s in acc.items():
            arr = np.asarray(s["values"])
            ranking.append(
                {
                    "name": city,
                    "admin_level": admin_level,
                    # Backward-compatible alias for older consumers.
                    "city": city,
                    "n_valid": len(arr),
                    "mean": _round(np.mean(arr)),
                    "max": _round(np.max(arr)),
                    "n_exceed": s["n_exceed"],
                }
            )
        ranking.sort(key=lambda r: (r["mean"] is None, -(r["mean"] or 0)))
        result["city_ranking"] = ranking

    if wind is not None:
        result["wind"] = _build_wind_block(wind, wind_stride or 1)

    return result


# ---------------------------------------------------------------------------
# Overlay (raster + station combined)
# ---------------------------------------------------------------------------
def build_overlay_result(
    *,
    region: RegionInfo,
    product: str,
    date: str,
    prod_info: ProductInfo,
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    swath_meta: dict[str, Any],
    raster_vmin: float,
    raster_vmax: float,
    data: StationData,
    datetime_str: str,
    threshold: float | None,
    unit: str,
    cities_gdf: gpd.GeoDataFrame | None,
    output: str,
) -> dict[str, Any]:
    """Combine raster + station results into a single JSON payload.

    Nested under `raster` and `station` keys so agents can inspect either
    layer independently. A shared `region`, `image`, and `datetime` sit
    at the top level.
    """
    raster_block = build_raster_result(
        region=region,
        product=product,
        date=date,
        prod_info=prod_info,
        LON=LON,
        LAT=LAT,
        grid=grid,
        swath_meta=swath_meta,
        vmin=raster_vmin,
        vmax=raster_vmax,
        output=output,
    )
    station_block = build_station_result(
        region=region,
        data=data,
        datetime_str=datetime_str,
        threshold=threshold,
        unit=unit,
        cities_gdf=cities_gdf,
        output=output,
    )

    # Shared fields are promoted to the top level; strip them from the
    # per-layer blocks so the structure stays flat and non-redundant.
    shared_keys = ("command", "image", "region")
    for key in shared_keys:
        raster_block.pop(key, None)
        station_block.pop(key, None)

    return {
        "command": "overlay",
        "image": output,
        "region": {
            "name": region.name,
            "level": region.level,
            "extent": [round(x, 3) for x in region.extent],
        },
        "datetime": datetime_str,
        "date": date,
        "raster": raster_block,
        "station": station_block,
    }


# ---------------------------------------------------------------------------
# FNR (HCHO/NO2 regime)
# ---------------------------------------------------------------------------
def _fnr_per_city_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    fnr: np.ndarray,
    cities_gdf: gpd.GeoDataFrame,
    *,
    voc_threshold: float,
    nox_threshold: float,
) -> list[dict[str, Any]]:
    """Per-city mean FNR and dominant regime."""
    from shapely.vectorized import contains

    rows: list[dict[str, Any]] = []
    for _, row in cities_gdf.iterrows():
        mask = contains(row.geometry, LON, LAT)
        sub = fnr[mask]
        finite = sub[np.isfinite(sub)]
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
                "n_pixels": int(len(finite)),
                "mean_fnr": _round(mean_fnr),
                "median_fnr": _round(np.median(finite)),
                "regime": regime,
                "voc_limited_pct": round(
                    100 * float((finite < voc_threshold).mean()), 1
                ),
                "nox_limited_pct": round(
                    100 * float((finite > nox_threshold).mean()), 1
                ),
            }
        )
    rows.sort(key=lambda r: (r["mean_fnr"] is None, r["mean_fnr"] or 1e9))
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
    """Build the JSON sidecar for an FNR run."""
    from rsplot.fnr import (
        regime_percentages,
        validate_fnr_thresholds,
    )

    voc_threshold, nox_threshold, display_max = validate_fnr_thresholds(
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
    )

    fnr = fnr_out.fnr
    finite = fnr[np.isfinite(fnr)]

    # Per-pixel coverage histogram: how many of the requested days had
    # both NO2 and HCHO valid?
    from shapely.vectorized import contains

    region_mask = contains(region.geometry, fnr_out.LON, fnr_out.LAT)
    total_region_pixels = int(region_mask.sum())
    n_valid_fnr = int(np.isfinite(fnr).sum())
    coverage_pct = (
        round(100 * n_valid_fnr / total_region_pixels, 3)
        if total_region_pixels
        else 0.0
    )
    both_valid_days = np.minimum(fnr_out.n_valid_hcho, fnr_out.n_valid_no2)
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
        "coverage_ge_n_min_pixels": int(
            diagnostic_masks["coverage_ok"].sum()
        ),
        "no2_ge_threshold_pixels": int(diagnostic_masks["no2_ok"].sum()),
        "hcho_nonnegative_pixels": int(diagnostic_masks["hcho_ok"].sum()),
        "final_valid_pixels": n_valid_fnr,
    }

    result: dict[str, Any] = {
        "command": "fnr",
        "image": output,
        "region": {
            "name": region.name,
            "level": region.level,
            "extent": [round(x, 3) for x in region.extent],
        },
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
            **_basic_stats(fnr),
        },
        "regime_pct": regime_percentages(
            fnr,
            voc_threshold=voc_threshold,
            nox_threshold=nox_threshold,
        ),
        "mean_fields": {
            "hcho_mean_raw_stats": _basic_stats(fnr_out.hcho_mean),
            "no2_mean_raw_stats": _basic_stats(fnr_out.no2_mean),
            "hcho_mean_filled_stats": _basic_stats(fnr_out.hcho_mean_filled),
            "no2_mean_filled_stats": _basic_stats(fnr_out.no2_mean_filled),
        },
    }

    sub_gdf = region.sub_boundary_gdf
    if sub_gdf is not None and len(sub_gdf) > 0:
        result["city_ranking"] = _fnr_per_city_stats(
            fnr_out.LON,
            fnr_out.LAT,
            fnr,
            sub_gdf,
            voc_threshold=voc_threshold,
            nox_threshold=nox_threshold,
        )

    return result


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------
def emit_result(result: dict[str, Any], image_path: str) -> str:
    """Write {image}.json sidecar. Return sidecar path."""
    sidecar = str(Path(image_path).with_suffix(".json"))
    result["sidecar"] = sidecar

    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return sidecar
