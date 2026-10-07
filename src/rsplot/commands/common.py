"""Small shared helpers for CLI command services."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, ParamSpec, TypeVar

import typer

from rsplot.errors import RsplotError

if TYPE_CHECKING:
    import geopandas as gpd
    from rich.console import Console

    from rsplot.config import AppConfig
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo


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


def parse_explicit_window(date_arg: str, days: int | None) -> list[str]:
    """Return the dates of a window whose length is stated explicitly.

    The window is either a ``YYYYMMDD-YYYYMMDD`` range or an end date
    ``YYYYMMDD`` with ``--days``; a single date alone is rejected.
    """
    from rsplot.temporal import parse_date_window

    if days is not None and days < 1:
        raise RsplotError(
            "invalid_argument", "--days 必须 >= 1。", option="--days"
        )
    if "-" in date_arg and days is not None:
        raise RsplotError(
            "invalid_argument",
            "日期区间不能与 --days 同时使用；"
            "请选择 YYYYMMDD-YYYYMMDD 或结束日期 YYYYMMDD 配合 --days N。",
            option="--days",
        )
    if "-" not in date_arg and days is None:
        raise RsplotError(
            "invalid_argument",
            "单日 DATE 需要 --days N 指定窗口长度，"
            "或使用日期区间 YYYYMMDD-YYYYMMDD。",
            option="--days",
        )
    try:
        return parse_date_window(date_arg, default_days=days or 0)
    except ValueError as error:
        raise RsplotError("invalid_time", str(error)) from error


def require_single_region(region: str) -> None:
    """Reject a comma list where a merged regional mean would be implicit."""
    names = [name.strip() for name in re.split("[,，]", region)]
    if len(names) > 1:
        raise RsplotError(
            "invalid_argument",
            f"'{region}' 列出了多个区域。时间序列一次只汇总一个区域，"
            "合并多个区域会隐式加权；请对每个区域分别运行。",
            details={"regions": [name for name in names if name]},
        )


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


def resolve_satellite(
    product: str,
    sensor: str,
    qa: float | None,
    cfg: AppConfig,
    console: Console,
    processing: str | None = None,
) -> tuple[ProductInfo, float]:
    """Resolve source and QA policy before opening regional/data files."""
    from rsplot.readers import get_product_info

    try:
        info = get_product_info(product, sensor=sensor, processing=processing)
        if info.sensor == "gems" and qa is not None:
            raise ValueError(
                "--qa 仅用于 TROPOMI；GEMS 使用最终质量标记 = 0 "
                "及 SZA/VZA < 70°，云量可通过 --cf 设置。"
            )
        threshold = (
            0.5
            if info.sensor == "gems"
            else qa
            if qa is not None
            else cfg.qa_threshold
        )
        validate_unit_interval(threshold, "--qa")
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError("invalid_argument", str(error)) from error
    return info, threshold


def satellite_filter_label(sensor: str, qa: float, cf: float) -> str:
    """Describe the actual filter rather than a synthetic GEMS QA value."""
    quality = (
        "最终质量标记 = 0, SZA/VZA < 70°" if sensor == "gems" else f"QA > {qa}"
    )
    return f"{quality}, 云量 <= {cf}"


_P = ParamSpec("_P")
_R = TypeVar("_R")


def satellite_errors(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Render expected satellite input/data errors in the CLI's style."""
    from functools import wraps

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return function(*args, **kwargs)
        except (ValueError, FileNotFoundError, OSError) as error:
            kwargs["console"].print(f"[red]{error}[/red]")
            raise typer.Exit(1) from error

    return wrapped
