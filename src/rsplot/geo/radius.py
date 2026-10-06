"""Geodesic station neighborhoods with independent administrative context."""

from __future__ import annotations

import math
from dataclasses import replace

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely.geometry import Point, Polygon, box

from rsplot.config import LEVEL_DEFAULTS, AppConfig
from rsplot.geo.boundaries import (
    RegionInfo,
    _city_subdivisions,
    load_city_boundaries,
    load_county_boundaries,
)

GEOD = Geod(ellps="WGS84")


def geodesic_square(lon: float, lat: float, km: float) -> Polygon:
    """Build a north-oriented square in station-centered WGS84 AEQD meters."""
    if not math.isfinite(km) or km <= 0:
        raise ValueError("--km 必须是大于 0 的有限数字。")
    if not (np.isfinite(lon) and np.isfinite(lat)):
        raise ValueError("中心站坐标不是有效数字。")
    if not (-180 <= lon <= 180 and -90 < lat < 90):
        raise ValueError("中心站坐标超出有效经纬度范围。")
    half_width = km * 1000
    outline = box(-half_width, -half_width, half_width, half_width)
    xy = np.asarray(outline.segmentize(half_width / 32).exterior.coords)
    azimuth = np.degrees(np.arctan2(xy[:, 0], xy[:, 1]))
    x, y, _ = GEOD.fwd(
        np.full(len(xy), lon),
        np.full(len(xy), lat),
        azimuth,
        np.hypot(xy[:, 0], xy[:, 1]),
    )
    square = Polygon(zip(x, y, strict=True))
    # The existing rectilinear plotting pipeline cannot wrap the dateline.
    pole_distance = min(
        GEOD.inv(lon, lat, lon, 90)[2],
        GEOD.inv(lon, lat, lon, -90)[2],
    )
    if (
        km * 1000 * math.sqrt(2) >= pole_distance
        or np.ptp(x) > 180
        or not square.is_valid
    ):
        raise ValueError("正方形范围跨越极点或日期变更线，当前地图不支持。")
    return square


def station_distances(
    lon: float,
    lat: float,
    station_lon: np.ndarray,
    station_lat: np.ndarray,
) -> np.ndarray:
    """Return WGS84 distances in km; invalid coordinates remain NaN."""
    valid = (
        np.isfinite(station_lon)
        & np.isfinite(station_lat)
        & (np.abs(station_lon) <= 180)
        & (np.abs(station_lat) <= 90)
    )
    distances = np.full(station_lon.shape, np.nan)
    _, _, meters = GEOD.inv(
        np.full(valid.sum(), lon),
        np.full(valid.sum(), lat),
        station_lon[valid],
        station_lat[valid],
    )
    distances[valid] = meters / 1000
    return distances


def station_offsets_km(
    lon: float,
    lat: float,
    station_lon: np.ndarray,
    station_lat: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """East and north offsets from the centre, in km, along the geodesic."""
    azimuth, _, meters = GEOD.inv(
        np.full(station_lon.shape, lon),
        np.full(station_lat.shape, lat),
        station_lon,
        station_lat,
    )
    angle = np.radians(azimuth)
    return meters * np.sin(angle) / 1000, meters * np.cos(angle) / 1000


def station_square_mask(
    lon: float,
    lat: float,
    km: float,
    station_lon: np.ndarray,
    station_lat: np.ndarray,
) -> np.ndarray:
    """Select the square including its edges, rather than a radial disk."""
    x_km, y_km = station_offsets_km(lon, lat, station_lon, station_lat)
    x, y = x_km * 1000, y_km * 1000
    return (
        np.isfinite(x)
        & np.isfinite(y)
        & (np.abs(station_lon) <= 180)
        & (np.abs(station_lat) <= 90)
        & (np.abs(x) <= km * 1000 + 1e-6)
        & (np.abs(y) <= km * 1000 + 1e-6)
    )


def resolve_radius_region(
    station_id: str,
    lon: float,
    lat: float,
    km: float,
    cfg: AppConfig,
) -> RegionInfo:
    """Resolve visible city and county/township context around a square."""
    square = geodesic_square(lon, lat, km)
    west, south, east, north = square.bounds
    view = square
    if not cfg.geojson_dir:
        raise ValueError("请配置行政边界目录 geojson_dir。")
    cities = load_city_boundaries(cfg.geojson_dir).to_crs("EPSG:4326")
    counties = load_county_boundaries(cfg.geojson_dir).to_crs("EPSG:4326")
    cities = cities[cities.geometry.intersects(view)].copy()
    layers = []
    for _, city in cities.iterrows():
        override = _city_subdivisions(
            city["name"],
            city.geometry,
            cities.crs,
            cfg,
        )
        if override is None:
            layer = counties[
                counties.geometry.intersects(city.geometry)
                & counties.geometry.intersects(view)
            ].copy()
            layer["administrative_level"] = "county"
        else:
            layer, level = override
            layer = layer[layer.geometry.intersects(view)].copy()
            layer["administrative_level"] = level
        # Clip contextual units to their city, avoiding border-touch neighbors.
        layer.geometry = layer.geometry.intersection(city.geometry)
        layer = layer[
            (~layer.geometry.is_empty)
            & (layer.geometry.to_crs("EPSG:6933").area > 0)
        ]
        layer["city"] = city["name"]
        layers.append(layer)
    subdivisions = (
        gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), crs=cities.crs)
        if layers
        else None
    )
    return RegionInfo(
        name=f"{station_id} 上下左右各 {km:g} km",
        level="county",
        geometry=square,
        extent=(west, east, south, north),
        params=replace(LEVEL_DEFAULTS["county"], pad=0, basemap=False),
        main_boundary_gdf=cities,
        sub_boundary_gdf=subdivisions,
        geometry_kind="station_radius",
        projection_center=(lon, lat),
    )


def administrative_context(region: RegionInfo, lon: float, lat: float) -> dict:
    """Describe the center's affiliations and the visible administrative units."""
    point = Point(lon, lat)
    cities = region.main_boundary_gdf
    subdivisions = region.sub_boundary_gdf
    visible_cities = [] if cities is None else cities["name"].tolist()
    center_cities = (
        []
        if cities is None
        else cities[cities.geometry.covers(point)]["name"].tolist()
    )
    units = []
    if subdivisions is not None:
        for _, row in subdivisions.iterrows():
            units.append(
                {
                    "name": row["name"],
                    "city": row["city"],
                    "level": row["administrative_level"],
                    "contains_center": bool(row.geometry.covers(point)),
                }
            )
    return {
        "center_cities": center_cities,
        "visible_cities": visible_cities,
        "subdivisions": units,
    }
