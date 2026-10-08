"""Administrative boundary loading and region name resolution.

Resolves user input into a RegionInfo with level, geometry,
sub-boundaries for overlay, etc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from rsplot.config import (
    LEVEL_DEFAULTS,
    AppConfig,
    LevelParams,
    SubdivisionSource,
)
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


# Suffixes to strip for fuzzy matching
_SUFFIXES = re.compile(
    r"(特别行政区|自治区|自治州|自治县|街道|地区|林区|省|市|区|县|盟|镇|乡)$"
)

NAME_FIELD = "name"

# 直辖市 — resolved as province but displayed with county-level sub-boundaries
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
# Municipalities present in both the province and city files resolve as
# cities; 重庆市 (and same-name entries such as 香港) stay provinces.
CITY_MUNICIPALITIES = {"北京市", "天津市", "上海市"}
# Placeholder features in the boundary files, never a region.
PLACEHOLDER_NAMES = {"境界线"}


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
    administrative_level: str | None = None
    subdivision_level: str | None = None
    qualified_name: str | None = None
    members: tuple[RegionInfo, ...] = ()
    geometry_kind: str = "administrative"
    projection_center: tuple[float, float] | None = None


# China's 56 ethnic groups, as written in autonomous-area names.
_ETHNIC_GROUPS = [
    "汉",
    "蒙古",
    "回",
    "藏",
    "维吾尔",
    "苗",
    "彝",
    "壮",
    "布依",
    "朝鲜",
    "满",
    "侗",
    "瑶",
    "白",
    "土家",
    "哈尼",
    "哈萨克",
    "傣",
    "黎",
    "傈僳",
    "佤",
    "畲",
    "高山",
    "拉祜",
    "水",
    "东乡",
    "纳西",
    "景颇",
    "柯尔克孜",
    "土",
    "达斡尔",
    "仫佬",
    "羌",
    "布朗",
    "撒拉",
    "毛南",
    "仡佬",
    "锡伯",
    "阿昌",
    "普米",
    "塔吉克",
    "怒",
    "乌孜别克",
    "俄罗斯",
    "鄂温克",
    "德昂",
    "保安",
    "裕固",
    "京",
    "塔塔尔",
    "独龙",
    "鄂伦春",
    "赫哲",
    "门巴",
    "珞巴",
    "基诺",
]
# One or more groups right before the autonomous suffix: 广西壮族自治区 ->
# 广西自治区, 黔东南苗族侗族自治州 -> 黔东南自治州. Groups carry 族, except
# 维吾尔 in 新疆维吾尔自治区; 内蒙古 and 西藏 are place names, not groups.
_ETHNIC_DESIGNATION = re.compile(
    r"(?:(?:"
    + "|".join(sorted(_ETHNIC_GROUPS, key=len, reverse=True))
    + r")族|维吾尔)+(?=自治[区州县旗]$)"
)


def _strip_suffix(name: str) -> str:
    stripped = _ETHNIC_DESIGNATION.sub("", name)
    if stripped.startswith("自治"):
        # The whole name is the ethnic designation (鄂伦春自治旗).
        stripped = name
    return _SUFFIXES.sub("", stripped)


def _fuzzy_match(
    query: str, candidates: gpd.GeoDataFrame
) -> gpd.GeoDataFrame | None:
    """Match query against NAME_FIELD: exact first, then suffix-stripped."""
    # exact
    exact = candidates[candidates[NAME_FIELD] == query]
    if len(exact) > 0:
        return exact

    # with common suffixes appended
    for suffix in ["省", "市", "区", "县", "自治区", "镇", "乡", "街道"]:
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
def _read_boundary_file(path: str) -> gpd.GeoDataFrame:
    """Read a configured boundary file; a missing one is a config error."""
    if not Path(path).is_file():
        raise RsplotError(
            "config_invalid",
            f"边界文件不存在: {path}；请检查配置 [paths].geojson_dir。",
            details={"path": path},
        )
    return gpd.read_file(path)


@lru_cache(maxsize=1)
def _load_province(geojson_dir: str) -> gpd.GeoDataFrame:
    return _read_boundary_file(f"{geojson_dir}/中国_省.geojson")


@lru_cache(maxsize=1)
def _load_city(geojson_dir: str) -> gpd.GeoDataFrame:
    return _read_boundary_file(f"{geojson_dir}/中国_市.geojson")


@lru_cache(maxsize=1)
def _load_county(geojson_dir: str) -> gpd.GeoDataFrame:
    return _read_boundary_file(f"{geojson_dir}/中国_县.geojson")


@lru_cache(maxsize=16)
def _load_subdivision_source(
    path: str,
    name_field: str,
    target_crs: str,
) -> gpd.GeoDataFrame:
    """Load and normalize a configured city subdivision boundary file."""
    try:
        source = gpd.read_file(path)
    except Exception as exc:
        raise ValueError(
            f"无法读取下级行政区边界文件 '{path}': {exc}"
        ) from exc

    if name_field not in source.columns:
        available = ", ".join(str(column) for column in source.columns)
        raise ValueError(
            f"下级行政区边界文件 '{path}' 缺少名称字段 "
            f"'{name_field}'。可用字段: {available}"
        )
    if source.crs is None:
        raise ValueError(f"下级行政区边界文件 '{path}' 缺少坐标系信息。")

    try:
        source = source.to_crs(target_crs)
    except Exception as exc:
        raise ValueError(
            f"下级行政区边界文件 '{path}' 无法转换到 {target_crs}: {exc}"
        ) from exc

    normalized = source[[name_field, "geometry"]].rename(
        columns={name_field: NAME_FIELD}
    )
    normalized[NAME_FIELD] = (
        normalized[NAME_FIELD].astype("string").str.strip()
    )
    normalized = normalized[
        normalized[NAME_FIELD].notna()
        & normalized[NAME_FIELD].ne("")
        & normalized.geometry.notna()
        & ~normalized.geometry.is_empty
    ].copy()
    if len(normalized) == 0:
        raise ValueError(f"下级行政区边界文件 '{path}' 没有可用要素。")
    invalid = ~normalized.geometry.is_valid
    if invalid.any():
        raise ValueError(
            f"下级行政区边界文件 '{path}' 包含 "
            f"{int(invalid.sum())} 个无效几何。"
        )
    return normalized


def load_province_boundaries(geojson_dir: str) -> gpd.GeoDataFrame:
    """Return the cached province boundary dataset."""
    return _load_province(geojson_dir)


def load_city_boundaries(geojson_dir: str) -> gpd.GeoDataFrame:
    """Return the cached city boundary dataset."""
    return _load_city(geojson_dir)


def load_county_boundaries(geojson_dir: str) -> gpd.GeoDataFrame:
    """Return the cached county boundary dataset."""
    return _load_county(geojson_dir)


def _find_subdivision_source(
    city_name: str,
    cfg: AppConfig,
) -> SubdivisionSource | None:
    """Match a configured override by canonical or suffix-free city name."""
    if city_name in cfg.subdivision_overrides:
        return cfg.subdivision_overrides[city_name]
    stripped = _strip_suffix(city_name)
    for configured_name, source in cfg.subdivision_overrides.items():
        if _strip_suffix(configured_name) == stripped:
            return source
    return None


def _city_subdivisions(
    city_name: str,
    city_geometry: BaseGeometry,
    city_crs: object,
    cfg: AppConfig,
) -> tuple[gpd.GeoDataFrame, str] | None:
    """Return a configured city-specific subdivision layer when present."""
    source = _find_subdivision_source(city_name, cfg)
    if source is None:
        return None
    if city_crs is None:
        raise ValueError("城市边界数据缺少坐标系，无法加载下级行政区覆盖。")

    subdivisions = _load_subdivision_source(
        source.path,
        source.name_field,
        str(city_crs),
    )
    subdivisions = subdivisions[
        subdivisions.geometry.intersects(city_geometry.buffer(0.01))
    ].copy()
    if len(subdivisions) == 0:
        raise ValueError(
            f"为 {city_name} 配置的边界文件与城市边界没有空间交集: "
            f"{source.path}"
        )
    return subdivisions, source.level


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
    cfg: AppConfig,
    cities: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> RegionInfo | None:
    if "/" not in name:
        return None
    city_name, county_name = name.split("/", 1)
    city_match = _fuzzy_match(city_name, cities)
    if city_match is None:
        raise ValueError(f"无法识别城市 '{city_name}'。")
    canonical_city_name = city_match.iloc[0][NAME_FIELD]
    city_geometry = unary_union(city_match.geometry)
    configured = _city_subdivisions(
        canonical_city_name,
        city_geometry,
        cities.crs,
        cfg,
    )
    if configured is None:
        sub_counties = counties[
            counties.geometry.within(city_geometry.buffer(0.01))
        ]
        administrative_level = "county"
    else:
        sub_counties, administrative_level = configured
    county_match = _fuzzy_match(county_name, sub_counties)
    if county_match is None:
        available = ", ".join(sub_counties[NAME_FIELD].tolist())
        raise ValueError(
            f"在 {canonical_city_name} 下未找到 '{county_name}'。"
            f"\n可用下级行政区: {available}"
        )
    return _build_info(
        name=county_match.iloc[0][NAME_FIELD],
        level="county",
        geometry=unary_union(county_match.geometry),
        main_gdf=county_match,
        sub_gdf=None,
        administrative_level=administrative_level,
        qualified_name=f"{canonical_city_name}/{county_match.iloc[0][NAME_FIELD]}",
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
    cfg: AppConfig,
    cities: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> RegionInfo | None:
    match = _fuzzy_match(name, cities)
    if match is None:
        return None
    city_name = match.iloc[0][NAME_FIELD]
    geometry = unary_union(match.geometry)
    configured = _city_subdivisions(city_name, geometry, cities.crs, cfg)
    if configured is None:
        sub_counties = counties[
            counties.geometry.within(geometry.buffer(0.01))
        ]
        subdivision_level = None
    else:
        sub_counties, subdivision_level = configured
    return _build_info(
        name=city_name,
        level="city",
        geometry=geometry,
        main_gdf=match,
        sub_gdf=sub_counties,
        subdivision_level=subdivision_level,
    )


def _matched_name(query: str, candidates: gpd.GeoDataFrame) -> str | None:
    match = _fuzzy_match(query, candidates)
    if match is None:
        return None
    name = match.iloc[0][NAME_FIELD]
    return None if name in PLACEHOLDER_NAMES else name


def _resolve_named_place(
    name: str,
    cfg: AppConfig,
    provinces: gpd.GeoDataFrame,
    cities: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> RegionInfo | None:
    """Resolve a province or city name without guessing between them.

    A full name selects its own level; a short name matching different
    places at both levels is rejected with the candidates.
    """
    province = _matched_name(name, provinces)
    city = _matched_name(name, cities)
    if province is not None and province == city:
        use_city = province in CITY_MUNICIPALITIES
    elif province is not None and city is not None:
        if (province == name) == (city == name):
            raise RsplotError(
                "region_ambiguous",
                f"区域名 '{name}' 同时匹配 {province}（省级）和 "
                f"{city}（市级），请写全称。",
                details={"region": name, "candidates": [province, city]},
            )
        use_city = city == name
    elif province is not None or city is not None:
        use_city = city is not None
    else:
        return None
    if use_city:
        return _resolve_city(city, cfg, cities, counties)
    return _resolve_province(province, provinces, cities, counties)


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
        qualified_county = _resolve_qualified_county(
            name,
            cfg,
            cities,
            counties,
        )
        if qualified_county is not None:
            return qualified_county

    if level_override is None or level_override == "key_region":
        assert provinces is not None
        cities = load_city_boundaries(geojson_dir)
        key_region = _resolve_key_region(name, cfg, provinces, cities)
        if key_region is not None:
            return key_region

    if level_override is None:
        assert provinces is not None
        named = _resolve_named_place(
            name,
            cfg,
            provinces,
            load_city_boundaries(geojson_dir),
            load_county_boundaries(geojson_dir),
        )
        if named is not None:
            return named
        raise ValueError(
            f"无法识别区域 '{name}'。请使用中文全称或简称，"
            "县区写成 城市/区县，如 合肥/蜀山。"
        )

    # The level filter below serves only the disabled forecast and
    # reconstruct commands; enabled commands resolve by name alone.
    if level_override == "province":
        assert provinces is not None
        cities = load_city_boundaries(geojson_dir)
        counties = load_county_boundaries(geojson_dir)
        province = _resolve_province(name, provinces, cities, counties)
        if province is not None:
            return province

    if level_override == "city":
        cities = load_city_boundaries(geojson_dir)
        counties = load_county_boundaries(geojson_dir)
        city = _resolve_city(name, cfg, cities, counties)
        if city is not None:
            return city

    if level_override == "county":
        raise ValueError(
            "县区/镇街级别需要指定所属城市，格式: 城市/下级行政区，"
            "如 合肥/蜀山、中山/板芙"
        )

    raise ValueError(
        f"无法识别区域 '{name}'。请使用中文行政区名称或重点区域名，"
        "区县写作 城市/区县，如 合肥/蜀山。"
    )


def _build_info(
    name: str,
    level: str,
    geometry: BaseGeometry,
    main_gdf: gpd.GeoDataFrame | None,
    sub_gdf: gpd.GeoDataFrame | None,
    detail_gdf: gpd.GeoDataFrame | None = None,
    administrative_level: str | None = None,
    subdivision_level: str | None = None,
    qualified_name: str | None = None,
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
        administrative_level=administrative_level,
        subdivision_level=subdivision_level,
        qualified_name=qualified_name,
    )


def resolve_regions(
    expression: str,
    cfg: AppConfig,
    level_override: str | None = None,
) -> RegionInfo:
    """Resolve a comma-separated selection without changing single-region APIs."""
    if "," not in expression and "，" not in expression:
        return resolve_region(expression, cfg, level_override)
    names = [
        part.replace("\r", "").replace("\n", "").strip()
        for part in re.split("[,，]", expression)
    ]
    if any(not name for name in names):
        raise ValueError("多区域列表包含空项，请检查连续逗号或首尾逗号。")
    members = []
    seen = set()
    for index, name in enumerate(names, 1):
        try:
            member = resolve_region(name, cfg, level_override)
        except ValueError as error:
            raise ValueError(
                f"第 {index} 个区域 '{name}' 无法解析：{error}"
            ) from error
        key = (member.level, member.qualified_name or member.name)
        if key not in seen:
            members.append(member)
            seen.add(key)

    levels = ("country", "key_region", "province", "city", "county")
    level = min((member.level for member in members), key=levels.index)
    geometry = unary_union([member.geometry for member in members])
    crs = next(
        (
            m.main_boundary_gdf.crs
            for m in members
            if m.main_boundary_gdf is not None
            and m.main_boundary_gdf.crs is not None
        ),
        "EPSG:4326",
    )
    main = gpd.GeoDataFrame(
        {NAME_FIELD: [m.qualified_name or m.name for m in members]},
        geometry=[m.geometry for m in members],
        crs=crs,
    )
    sub = _merge_member_layers(members, "sub_boundary_gdf", crs)
    detail = _merge_member_layers(members, "detail_boundary_gdf", crs)
    if detail is not None and sub is not None:
        sub_keys = {g.normalize().wkb for g in sub.geometry}
        detail = detail[
            ~detail.geometry.map(lambda g: g.normalize().wkb in sub_keys)
        ].copy()
    info = _build_info(
        name=f"联合区域（{len(members)}个）",
        level=level,
        geometry=geometry,
        main_gdf=main,
        sub_gdf=sub,
        detail_gdf=detail,
    )
    info.members = tuple(members)
    return info


def _merge_member_layers(
    members: list[RegionInfo],
    attribute: str,
    crs: object,
) -> gpd.GeoDataFrame | None:
    """Keep only each member's own subdivisions and deduplicate shared features."""
    rows = []
    seen = set()
    for member in members:
        frame = getattr(member, attribute)
        if frame is None or len(frame) == 0:
            continue
        if frame.crs is not None and frame.crs != crs:
            frame = frame.to_crs(crs)
        for _, row in frame.iterrows():
            geometry = row.geometry.intersection(member.geometry)
            if geometry.is_empty or geometry.area == 0:
                continue
            key = geometry.normalize().wkb
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {NAME_FIELD: row[member.sub_name_field], "geometry": geometry}
            )
    if not rows:
        return None
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
