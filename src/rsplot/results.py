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

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo
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
) -> dict[str, Any]:
    finite = grid[np.isfinite(grid)]
    total = grid.size
    coverage_pct = round(100 * len(finite) / total, 1) if total else 0.0

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
            **_basic_stats(grid),
        },
    }

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
    from shapely.geometry import Point

    sindex = cities_gdf.sindex
    out = np.empty(len(lon), dtype=object)
    for i, (x, y) in enumerate(zip(lon, lat)):
        if not (np.isfinite(x) and np.isfinite(y)):
            out[i] = ""
            continue
        pt = Point(float(x), float(y))
        city = ""
        for idx in sindex.intersection((x, y, x, y)):
            if cities_gdf.iloc[idx].geometry.contains(pt):
                city = cities_gdf.iloc[idx]["name"]
                break
        out[i] = city
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


def build_station_result(
    *,
    region: RegionInfo,
    data: StationData,
    datetime_str: str,
    threshold: float | None,
    unit: str,
    cities_gdf: gpd.GeoDataFrame | None,
    output: str,
) -> dict[str, Any]:
    valid = np.isfinite(data.values)
    vals = data.values[valid]
    lons = data.lon[valid]
    lats = data.lat[valid]
    ids = np.asarray(data.id)[valid]

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

    station_cities = None
    if cities_gdf is not None and len(cities_gdf) > 0 and len(vals) > 0:
        station_cities = _attribute_stations_to_cities(lons, lats, cities_gdf)

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
            if station_cities is not None:
                entry["city"] = station_cities[i] or None
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

    # Per-city ranking
    if station_cities is not None and len(vals) > 0:
        acc: dict[str, dict[str, Any]] = {}
        for i in range(len(vals)):
            c = station_cities[i]
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
                    "city": city,
                    "n_valid": len(arr),
                    "mean": _round(np.mean(arr)),
                    "max": _round(np.max(arr)),
                    "n_exceed": s["n_exceed"],
                }
            )
        ranking.sort(key=lambda r: (r["mean"] is None, -(r["mean"] or 0)))
        result["city_ranking"] = ranking

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
