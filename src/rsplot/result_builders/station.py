"""Station JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.config import get_station_color_scale
from rsplot.result_builders.common import serialize_region
from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData


def attribute_stations_to_areas(
    lon: np.ndarray,
    lat: np.ndarray,
    areas_gdf: gpd.GeoDataFrame,
    name_field: str = "name",
) -> np.ndarray:
    """Return the containing admin-unit name for each coordinate."""
    from shapely.geometry import Point

    spatial_index = areas_gdf.sindex
    out = np.empty(len(lon), dtype=object)
    for index, (x, y) in enumerate(zip(lon, lat, strict=True)):
        if not (np.isfinite(x) and np.isfinite(y)):
            out[index] = ""
            continue
        point = Point(float(x), float(y))
        area = ""
        for candidate in spatial_index.intersection((x, y, x, y)):
            if areas_gdf.iloc[candidate].geometry.contains(point):
                area = areas_gdf.iloc[candidate][name_field]
                break
        out[index] = area
    return out


def aqi_distribution(values: np.ndarray) -> dict[str, int]:
    bounds = [0, 50, 100, 150, 200, 300, 500]
    labels = ["优", "良", "轻度", "中度", "重度", "严重"]
    distribution: dict[str, int] = {}
    for index, label in enumerate(labels):
        lower, upper = bounds[index], bounds[index + 1]
        if index == 0:
            mask = (values >= lower) & (values <= upper)
        else:
            mask = (values > lower) & (values <= upper)
        distribution[label] = int(mask.sum())
    distribution["爆表"] = int((values > 500).sum())
    return distribution


def station_admin_level(region: RegionInfo) -> str | None:
    if region.subdivision_level is not None:
        return region.subdivision_level
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


def top_station_entries(
    *,
    values: np.ndarray,
    ids: np.ndarray,
    lons: np.ndarray,
    lats: np.ndarray,
    area_names: np.ndarray | None,
    admin_level: str | None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index in np.argsort(values)[::-1][:limit]:
        entry: dict[str, Any] = {
            "id": str(ids[index]),
            "value": round_finite(values[index]),
            "lon": round(float(lons[index]), 3),
            "lat": round(float(lats[index]), 3),
        }
        if area_names is not None:
            entry["admin_level"] = admin_level
            entry["admin_name"] = area_names[index] or None
            entry["city"] = area_names[index] or None
        entries.append(entry)
    return entries


def build_station_display(data: StationData) -> dict[str, Any] | None:
    """Describe the fixed scale shared by station map renderers."""
    scale = get_station_color_scale(data.var_name)
    if scale is None:
        return None
    return {
        "colorbar": bool(np.isfinite(data.values).any()),
        "cmap": scale.cmap,
        "range_method": "fixed_exceedance",
        "vmin": scale.vmin,
        "vmax": scale.vmax,
        "threshold": scale.threshold,
        "exceedance_operator": ">",
        "exceedance_color": scale.exceedance_color,
        "extend": "max",
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
) -> dict[str, Any]:
    valid = np.isfinite(data.values)
    values = data.values[valid]
    lons = data.lon[valid]
    lats = data.lat[valid]
    ids = np.asarray(data.id)[valid]
    admin_gdf = (
        region.sub_boundary_gdf
        if region.sub_boundary_gdf is not None
        and len(region.sub_boundary_gdf) > 0
        else cities_gdf
    )
    admin_level = station_admin_level(region)

    result: dict[str, Any] = {
        "command": "station",
        "image": output,
        "region": serialize_region(region),
        "datetime": datetime_str,
        "variable": data.var_name,
        "unit": unit or None,
        "threshold": threshold,
        "n_stations": int(data.n_stations),
        "n_valid": int(data.n_valid),
        "stats": basic_stats(values),
    }

    display = build_station_display(data)
    if display is not None:
        result["display"] = display

    station_areas = None
    if admin_gdf is not None and len(admin_gdf) > 0 and len(values) > 0:
        station_areas = attribute_stations_to_areas(
            lons,
            lats,
            admin_gdf,
            region.sub_name_field,
        )

    if len(values) > 0:
        result["top_stations"] = top_station_entries(
            values=values,
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

    if threshold is not None and len(values) > 0:
        exceed_mask = values > threshold
        top_stations: list[dict[str, Any]] = []
        for index in np.argsort(values)[::-1]:
            if values[index] <= threshold:
                break
            entry: dict[str, Any] = {
                "id": str(ids[index]),
                "value": round_finite(values[index]),
                "lon": round(float(lons[index]), 3),
                "lat": round(float(lats[index]), 3),
            }
            if station_areas is not None:
                entry["admin_level"] = admin_level
                entry["admin_name"] = station_areas[index] or None
                entry["city"] = station_areas[index] or None
            top_stations.append(entry)
            if len(top_stations) >= 10:
                break
        n_exceed = int(exceed_mask.sum())
        result["exceedance"] = {
            "count": n_exceed,
            "rate_pct": round(100 * n_exceed / len(values), 1),
            "top_stations": top_stations,
        }

    if data.var_name == "AQI" and len(values) > 0:
        result["aqi_distribution"] = aqi_distribution(values)

    if station_areas is not None and len(values) > 0:
        accumulator: dict[str, dict[str, Any]] = {}
        for index, value in enumerate(values):
            area = station_areas[index]
            if not area:
                continue
            summary = accumulator.setdefault(
                area,
                {"values": [], "n_exceed": 0},
            )
            summary["values"].append(float(value))
            if threshold is not None and value > threshold:
                summary["n_exceed"] += 1

        ranking = []
        for area, summary in accumulator.items():
            area_values = np.asarray(summary["values"])
            ranking.append(
                {
                    "name": area,
                    "admin_level": admin_level,
                    "city": area,
                    "n_valid": len(area_values),
                    "mean": round_finite(np.mean(area_values)),
                    "max": round_finite(np.max(area_values)),
                    "n_exceed": summary["n_exceed"],
                }
            )
        ranking.sort(
            key=lambda row: (row["mean"] is None, -(row["mean"] or 0))
        )
        result["city_ranking"] = ranking

    return result
