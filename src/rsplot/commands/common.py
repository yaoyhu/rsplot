"""Small shared helpers for CLI command services."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas as gpd
    from rich.console import Console

    from rsplot.geo.boundaries import RegionInfo


FORECAST_STATION_PAIR: dict[str, str] = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "so2": "SO2",
    "no2": "NO2",
    "co": "CO",
    "o3": "O3",
}


def parse_basemap(value: str | None) -> bool | None:
    """Parse the two supported basemap values without silent fallbacks."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "satellite":
        return True
    if normalized == "none":
        return False
    raise ValueError("--basemap 仅支持 satellite / none。")


def validate_positive(value: float, option: str) -> None:
    """Require a finite value greater than zero."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{option} 必须是大于 0 的有限数字。")


def validate_non_negative(value: float, option: str) -> None:
    """Require a finite value greater than or equal to zero."""
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{option} 必须是大于等于 0 的有限数字。")


def validate_unit_interval(value: float, option: str) -> None:
    """Require a finite fraction in the closed unit interval."""
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{option} 必须是 0 到 1 之间的有限数字。")


def validate_color_range(
    vmin: float | None,
    vmax: float | None,
) -> None:
    """Validate optional color limits, including individually supplied ones."""
    if vmin is not None and not math.isfinite(vmin):
        raise ValueError("--vmin 必须是有限数字。")
    if vmax is not None and not math.isfinite(vmax):
        raise ValueError("--vmax 必须是有限数字。")
    if vmin is not None and vmax is not None and vmax <= vmin:
        raise ValueError("--vmax 必须大于 --vmin。")


def load_fallback_city_boundaries(
    region: RegionInfo,
    geojson_dir: str,
) -> gpd.GeoDataFrame | None:
    """Load city boundaries only when a region has no subdivisions."""
    sub_boundaries = getattr(region, "sub_boundary_gdf", None)
    if sub_boundaries is not None and len(sub_boundaries) > 0:
        return None
    from rsplot.geo.boundaries import load_city_boundaries

    return load_city_boundaries(geojson_dir)


def warn_missing_tianditu_key(
    *,
    basemap: bool | None,
    default_basemap: bool,
    tianditu_key: str | None,
    console: Console,
) -> None:
    """Warn when a requested TianDiTu basemap cannot be loaded."""
    use_basemap = basemap if basemap is not None else default_basemap
    if use_basemap and not tianditu_key:
        console.print(
            "[yellow]未设置天地图 API key，底图将不会加载。请设置 "
            "TIANDITU_API_KEY，或使用 --basemap none。[/yellow]"
        )


def print_failed_dates(
    label: str,
    failed: dict[str, str],
    *,
    console: Console,
    max_items: int = 8,
) -> None:
    """Print a compact failed-date summary for window commands."""
    if not failed:
        return
    console.print(f"  → [yellow]{label} 失败日期示例:[/yellow]")
    items = list(failed.items())
    for date, message in items[:max_items]:
        console.print(f"    - {date}: {message}")
    if len(items) > max_items:
        console.print(f"    ... 另有 {len(items) - max_items} 天")
