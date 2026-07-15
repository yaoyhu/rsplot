"""Administrative boundary loading and region name resolution.

Resolves user input into a RegionInfo with level, geometry,
sub-boundaries for overlay, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from rsplot.config import LEVEL_DEFAULTS, AppConfig, LevelParams

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


# Suffixes to strip for fuzzy matching
_SUFFIXES = re.compile(
    r"(省|市|区|县|自治区|自治州|自治县|地区|盟|林区|特别行政区)$"
)

NAME_FIELD = "name"

# 直辖市 — resolved as province but displayed with county-level sub-boundaries
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}


@dataclass
class RegionInfo:
    """Everything the plotting pipeline needs about a resolved region."""

    name: str  # display name (e.g. "芜湖市")
    level: str  # "key_region" | "province" | "city" | "county"
    geometry: BaseGeometry  # union geometry for masking
    extent: tuple[
        float, float, float, float
    ]  # (lon_min, lon_max, lat_min, lat_max)
    params: LevelParams  # plotting parameters for this level

    # sub-boundary GeoDataFrames for overlay
    main_boundary_gdf: gpd.GeoDataFrame | None = None  # red border
    sub_boundary_gdf: gpd.GeoDataFrame | None = None  # grey sub-divisions
    detail_boundary_gdf: gpd.GeoDataFrame | None = (
        None  # finer sub-divisions (counties in province view)
    )
    sub_name_field: str = NAME_FIELD


def _strip_suffix(name: str) -> str:
    return _SUFFIXES.sub("", name)


def _fuzzy_match(
    query: str, candidates: gpd.GeoDataFrame
) -> gpd.GeoDataFrame | None:
    """Match query against NAME_FIELD: exact first, then suffix-stripped."""
    # exact
    exact = candidates[candidates[NAME_FIELD] == query]
    if len(exact) > 0:
        return exact

    # with common suffixes appended
    for suffix in ["省", "市", "区", "县", "自治区"]:
        padded = candidates[candidates[NAME_FIELD] == query + suffix]
        if len(padded) > 0:
            return padded

    # strip suffix from both sides
    q_stripped = _strip_suffix(query)
    for _, row in candidates.iterrows():
        if _strip_suffix(row[NAME_FIELD]) == q_stripped:
            return candidates[candidates[NAME_FIELD] == row[NAME_FIELD]]

    return None


# ---------------------------------------------------------------------------
# GeoJSON loaders (cached)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_province(geojson_dir: str) -> gpd.GeoDataFrame:
    return gpd.read_file(f"{geojson_dir}/中国_省.geojson")


@lru_cache(maxsize=1)
def _load_city(geojson_dir: str) -> gpd.GeoDataFrame:
    return gpd.read_file(f"{geojson_dir}/中国_市.geojson")


@lru_cache(maxsize=1)
def _load_county(geojson_dir: str) -> gpd.GeoDataFrame:
    return gpd.read_file(f"{geojson_dir}/中国_县.geojson")


def load_province_boundaries(geojson_dir: str) -> gpd.GeoDataFrame:
    """Return the cached province boundary dataset."""
    return _load_province(geojson_dir)


def load_city_boundaries(geojson_dir: str) -> gpd.GeoDataFrame:
    """Return the cached city boundary dataset."""
    return _load_city(geojson_dir)


def load_county_boundaries(geojson_dir: str) -> gpd.GeoDataFrame:
    """Return the cached county boundary dataset."""
    return _load_county(geojson_dir)


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------
def _resolve_country(
    name: str,
    level_override: str | None,
    provinces: gpd.GeoDataFrame,
) -> RegionInfo | None:
    if (level_override is None or level_override == "country") and name in (
        "中国",
        "China",
        "china",
        "CHINA",
    ):
        info = _build_info(
            name="中国",
            level="country",
            geometry=unary_union(provinces.geometry),
            main_gdf=provinces,
            sub_gdf=provinces,
        )
        info.extent = (73.0, 136.0, 17.0, 54.0)
        return info
    return None


def _resolve_qualified_county(
    name: str,
    cities: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> RegionInfo | None:
    if "/" not in name:
        return None
    city_name, county_name = name.split("/", 1)
    city_match = _fuzzy_match(city_name, cities)
    if city_match is None:
        raise ValueError(f"无法识别城市 '{city_name}'。")
    city_geometry = unary_union(city_match.geometry)
    sub_counties = counties[
        counties.geometry.within(city_geometry.buffer(0.01))
    ]
    county_match = _fuzzy_match(county_name, sub_counties)
    if county_match is None:
        available = ", ".join(sub_counties[NAME_FIELD].tolist())
        raise ValueError(
            f"在 {city_match.iloc[0][NAME_FIELD]} 下未找到 '{county_name}'。"
            f"\n可用县区: {available}"
        )
    return _build_info(
        name=county_match.iloc[0][NAME_FIELD],
        level="county",
        geometry=unary_union(county_match.geometry),
        main_gdf=county_match,
        sub_gdf=None,
    )


def _resolve_key_region(
    name: str,
    cfg: AppConfig,
    provinces: gpd.GeoDataFrame,
    cities: gpd.GeoDataFrame,
) -> RegionInfo | None:
    upper = name.upper()
    for region_name, name_list in cfg.key_regions.items():
        if upper != region_name.upper() and name != region_name:
            continue
        matched_provinces = provinces[provinces[NAME_FIELD].isin(name_list)]
        matched_cities = cities[cities[NAME_FIELD].isin(name_list)]
        if len(matched_provinces) == 0 and len(matched_cities) == 0:
            raise ValueError(
                f"重点区域 '{region_name}' 包含的名称在 GeoJSON 中找不到: "
                f"{name_list}"
            )
        main_gdf = pd.concat([matched_provinces, matched_cities])
        geometry = unary_union(main_gdf.geometry)
        sub_gdf = (
            matched_cities
            if len(matched_provinces) == 0
            else cities[cities.geometry.intersects(geometry)]
        )
        return _build_info(
            name=region_name,
            level="key_region",
            geometry=geometry,
            main_gdf=main_gdf,
            sub_gdf=sub_gdf,
        )
    return None


def _resolve_province(
    name: str,
    provinces: gpd.GeoDataFrame,
    cities: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> RegionInfo | None:
    match = _fuzzy_match(name, provinces)
    if match is None:
        return None
    province_name = match.iloc[0][NAME_FIELD]
    geometry = unary_union(match.geometry)
    if province_name in MUNICIPALITIES:
        sub_counties = counties[
            counties.geometry.within(geometry.buffer(0.01))
        ]
        return _build_info(
            name=province_name,
            level="province",
            geometry=geometry,
            main_gdf=match,
            sub_gdf=sub_counties,
        )
    sub_cities = cities[cities.geometry.intersects(geometry)]
    detail_counties = counties[counties.geometry.intersects(geometry)]
    return _build_info(
        name=province_name,
        level="province",
        geometry=geometry,
        main_gdf=match,
        sub_gdf=sub_cities,
        detail_gdf=detail_counties,
    )


def _resolve_city(
    name: str,
    cities: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> RegionInfo | None:
    match = _fuzzy_match(name, cities)
    if match is None:
        return None
    geometry = unary_union(match.geometry)
    sub_counties = counties[counties.geometry.within(geometry.buffer(0.01))]
    return _build_info(
        name=match.iloc[0][NAME_FIELD],
        level="city",
        geometry=geometry,
        main_gdf=match,
        sub_gdf=sub_counties,
    )


def resolve_region(
    name: str,
    cfg: AppConfig,
    level_override: str | None = None,
) -> RegionInfo:
    """Resolve a user region through the established matching cascade."""
    geojson_dir = cfg.require_geojson_dir()
    provinces = None
    if level_override in (None, "country", "key_region", "province"):
        provinces = load_province_boundaries(geojson_dir)

    if provinces is not None:
        country = _resolve_country(name, level_override, provinces)
        if country is not None:
            return country

    if "/" in name:
        cities = load_city_boundaries(geojson_dir)
        counties = load_county_boundaries(geojson_dir)
        qualified_county = _resolve_qualified_county(name, cities, counties)
        if qualified_county is not None:
            return qualified_county

    if level_override is None or level_override == "key_region":
        assert provinces is not None
        cities = load_city_boundaries(geojson_dir)
        key_region = _resolve_key_region(name, cfg, provinces, cities)
        if key_region is not None:
            return key_region

    if level_override is None or level_override == "province":
        assert provinces is not None
        cities = load_city_boundaries(geojson_dir)
        counties = load_county_boundaries(geojson_dir)
        province = _resolve_province(name, provinces, cities, counties)
        if province is not None:
            return province

    if level_override is None or level_override == "city":
        cities = load_city_boundaries(geojson_dir)
        counties = load_county_boundaries(geojson_dir)
        city = _resolve_city(name, cities, counties)
        if city is not None:
            return city

    if level_override == "county":
        raise ValueError(
            "县/区级别需要指定所属城市，格式: 城市/县区，如 合肥/蜀山、成都/高新"
        )

    raise ValueError(
        f"无法识别区域 '{name}'。请检查名称是否正确，"
        "或使用 --level 指定级别 (key_region/province/city/county)。"
    )


def _build_info(
    name: str,
    level: str,
    geometry: BaseGeometry,
    main_gdf: gpd.GeoDataFrame | None,
    sub_gdf: gpd.GeoDataFrame | None,
    detail_gdf: gpd.GeoDataFrame | None = None,
) -> RegionInfo:
    bounds = geometry.bounds  # (minx, miny, maxx, maxy)
    params = LEVEL_DEFAULTS[level]
    extent = (
        bounds[0],
        bounds[2],
        bounds[1],
        bounds[3],
    )  # (lon_min, lon_max, lat_min, lat_max)
    return RegionInfo(
        name=name,
        level=level,
        geometry=geometry,
        extent=extent,
        params=params,
        main_boundary_gdf=main_gdf,
        sub_boundary_gdf=sub_gdf,
        detail_boundary_gdf=detail_gdf,
    )
