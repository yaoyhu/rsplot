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
    detail_boundary_gdf: gpd.GeoDataFrame | None = None  # finer sub-divisions (counties in province view)
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


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------
def resolve_region(
    name: str, cfg: AppConfig, level_override: str | None = None
) -> RegionInfo:
    """Resolve a user-supplied region name into a RegionInfo.

    Cascade order: key_region → province → city → county.
    If level_override is given, skip cascade and match only that level.
    """
    gj = cfg.geojson_dir
    gdf_prov = _load_province(gj)
    gdf_city = _load_city(gj)
    gdf_county = _load_county(gj)

    # --- 0. Country level (中国 / China) ---
    if (level_override is None or level_override == "country") and name in (
        "中国",
        "China",
        "china",
        "CHINA",
    ):
        union_geom = unary_union(gdf_prov.geometry)
        info = _build_info(
            name="中国",
            level="country",
            geometry=union_geom,
            main_gdf=gdf_prov,
            sub_gdf=gdf_prov,
        )
        # Override extent: focus on mainland (exclude deep South China Sea)
        info.extent = (73.0, 136.0, 17.0, 54.0)
        return info

    # --- Handle "city/county" format for county disambiguation ---
    if "/" in name:
        city_name, county_name = name.split("/", 1)
        city_match = _fuzzy_match(city_name, gdf_city)
        if city_match is None:
            raise ValueError(f"无法识别城市 '{city_name}'。")
        city_geom = unary_union(city_match.geometry)
        sub_counties = gdf_county[
            gdf_county.geometry.within(city_geom.buffer(0.01))
        ]
        county_match = _fuzzy_match(county_name, sub_counties)
        if county_match is None:
            available = ", ".join(sub_counties[NAME_FIELD].tolist())
            raise ValueError(
                f"在 {city_match.iloc[0][NAME_FIELD]} 下未找到 '{county_name}'。"
                f"\n可用县区: {available}"
            )
        union_geom = unary_union(county_match.geometry)
        return _build_info(
            name=county_match.iloc[0][NAME_FIELD],
            level="county",
            geometry=union_geom,
            main_gdf=county_match,
            sub_gdf=None,
        )

    # --- 1. Key regions (config presets) ---
    if level_override is None or level_override == "key_region":
        upper = name.upper()
        for kr_name, name_list in cfg.key_regions.items():
            if upper == kr_name.upper() or name == kr_name:
                # Match against both provinces and cities
                matched_provs = gdf_prov[gdf_prov[NAME_FIELD].isin(name_list)]
                matched_cities = gdf_city[gdf_city[NAME_FIELD].isin(name_list)]
                if len(matched_provs) == 0 and len(matched_cities) == 0:
                    raise ValueError(
                        f"重点区域 '{kr_name}' 包含的名称在 GeoJSON 中找不到: {name_list}"
                    )
                main_gdf = pd.concat([matched_provs, matched_cities])
                union_geom = unary_union(main_gdf.geometry)
                # Key regions show cities only (no counties) to avoid label clutter.
                # Pure city list (e.g. PRD): use matched cities directly.
                # Mixed / province list (e.g. BTH, YRD): enumerate ALL cities
                # within the union so each province also contributes its cities.
                if len(matched_provs) == 0:
                    sub = matched_cities
                else:
                    sub = gdf_city[gdf_city.geometry.intersects(union_geom)]
                return _build_info(
                    name=kr_name,
                    level="key_region",
                    geometry=union_geom,
                    main_gdf=main_gdf,
                    sub_gdf=sub,
                )

    # --- 2. Province ---
    if level_override is None or level_override == "province":
        match = _fuzzy_match(name, gdf_prov)
        if match is not None:
            prov_name = match.iloc[0][NAME_FIELD]
            union_geom = unary_union(match.geometry)

            if prov_name in MUNICIPALITIES:
                # 直辖市: show county/district boundaries like a city view
                sub_counties = gdf_county[
                    gdf_county.geometry.within(union_geom.buffer(0.01))
                ]
                return _build_info(
                    name=prov_name,
                    level="province",
                    geometry=union_geom,
                    main_gdf=match,
                    sub_gdf=sub_counties,
                )
            else:
                # Regular province: cities + counties within each city
                sub_cities = gdf_city[
                    gdf_city.geometry.intersects(union_geom)
                ]
                detail_counties = gdf_county[
                    gdf_county.geometry.intersects(union_geom)
                ]
                return _build_info(
                    name=prov_name,
                    level="province",
                    geometry=union_geom,
                    main_gdf=match,
                    sub_gdf=sub_cities,
                    detail_gdf=detail_counties,
                )

    # --- 3. City ---
    if level_override is None or level_override == "city":
        match = _fuzzy_match(name, gdf_city)
        if match is not None:
            union_geom = unary_union(match.geometry)
            sub_counties = gdf_county[
                gdf_county.geometry.within(union_geom.buffer(0.01))
            ]
            return _build_info(
                name=match.iloc[0][NAME_FIELD],
                level="city",
                geometry=union_geom,
                main_gdf=match,
                sub_gdf=sub_counties,
            )

    # --- 4. County ---
    if level_override == "county":
        # "/" case already handled above; bare name with --level county is ambiguous
        raise ValueError(
            f"县/区级别需要指定所属城市，格式: 城市/县区，如 合肥/蜀山、成都/高新"
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
