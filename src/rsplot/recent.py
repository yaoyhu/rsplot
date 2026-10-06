"""Recent-day JSON summaries for raster and station data.

The ``recent`` command is intentionally read/analysis only: it produces a
compact JSON payload for comparing the last week/month/year without drawing
maps. It reuses the existing product readers, gridding, and station filters so
its daily numbers match the plotting commands' data path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
from rich.console import Console
from rich.progress import track

from rsplot.config import get_exceedance_threshold
from rsplot.geo.gridding import grid_coverage_in_region
from rsplot.geo.processing import (
    buffered_extent,
    prepare_existing_grid,
    prepare_swath_grid,
)
from rsplot.readers import ProductInfo
from rsplot.readers.guokong import (
    mask_stations_to_region,
    read_stations,
)
from rsplot.stats import basic_stats

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo


@dataclass
class RecentDaily:
    """One daily summary row."""

    date: str
    ok: bool
    value: float | None
    stats: dict[str, Any]
    meta: dict[str, Any]
    error: str | None = None


def parse_recent_dates(end_date: str, days: int) -> list[str]:
    """Return ascending YYYYMMDD dates ending on ``end_date``."""
    if days < 1:
        raise ValueError("--days 必须 >= 1")
    if len(end_date) != 8 or not end_date.isdigit():
        raise ValueError(f"日期格式错误: '{end_date}'，应为 YYYYMMDD")
    try:
        end = datetime.strptime(end_date, "%Y%m%d")
    except ValueError as e:
        raise ValueError(
            f"日期无效: '{end_date}'，请检查年月日是否真实存在 (原始错误: {e})"
        ) from e

    start = end - timedelta(days=days - 1)
    return [
        (start + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)
    ]


def summarize_recent_raster(
    *,
    region: RegionInfo,
    product: str,
    prod_info: ProductInfo,
    data_dir: str,
    dates: list[str],
    res: float,
    qa_threshold: float,
    cloud_fraction_max: float = 0.5,
    console: Console | None = None,
) -> list[RecentDaily]:
    """Read daily raster swaths and summarize each day over the region."""
    if console is None:
        console = Console()

    reader = prod_info.create_reader()
    reader.cloud_fraction_max = cloud_fraction_max
    read_extent = buffered_extent(region.extent, 1.0)
    out: list[RecentDaily] = []

    for d in track(
        dates, description=f"[cyan]统计 {product.upper()} 最近数据..."
    ):
        meta: dict[str, Any] = {}
        try:
            if prod_info.sensor == "gems":
                from rsplot.temporal import read_scan_mean

                batch = read_scan_mean(
                    reader=reader,
                    data_dir=data_dir,
                    request=d,
                    extent=read_extent,
                    res=res,
                )
                prepared = prepare_existing_grid(
                    batch.LON,
                    batch.LAT,
                    batch.grid,
                    region.geometry,
                    fill_gaps=False,
                )
                meta = {
                    "n_pixels": batch.n_pixels,
                    "n_files": batch.n_files,
                    "n_broken": batch.n_broken,
                    **batch.metadata,
                }
            else:
                swath = reader.read(data_dir, d, read_extent, qa_threshold)
                prepared = prepare_swath_grid(
                    swath.lon,
                    swath.lat,
                    swath.values,
                    read_extent,
                    res,
                    region.geometry,
                )
                meta = {
                    "n_pixels": int(swath.n_pixels),
                    "n_files": int(swath.n_files),
                    "n_broken": int(swath.n_broken),
                    **swath.metadata,
                }
            stats = _grid_stats(
                prepared.lon,
                prepared.lat,
                prepared.values,
                region.geometry,
            )
            if not stats:
                raise ValueError(f"{d} 区域内无有效网格")
            out.append(
                RecentDaily(
                    date=d,
                    ok=True,
                    value=stats.get("mean"),
                    stats=stats,
                    meta=meta,
                )
            )
        except (FileNotFoundError, ValueError) as e:
            meta.update(getattr(e, "metadata", {}))
            out.append(
                RecentDaily(
                    date=d,
                    ok=False,
                    value=None,
                    stats={},
                    meta=meta,
                    error=str(e).splitlines()[0],
                )
            )

    return out


def summarize_recent_station(
    *,
    region: RegionInfo,
    data_dir: str,
    dates: list[str],
    var_name: str,
    console: Console | None = None,
) -> list[RecentDaily]:
    """Read daily latest-hour station files and summarize each day."""
    if console is None:
        console = Console()

    read_extent = buffered_extent(region.extent, 0.5)
    threshold = get_exceedance_threshold(var_name)
    out: list[RecentDaily] = []

    for d in track(
        dates, description=f"[cyan]统计 {var_name} 站点最近数据..."
    ):
        try:
            data, resolved_dt = read_stations(
                data_dir, d, var_name, extent=read_extent
            )
            data = mask_stations_to_region(data, region.geometry)
            vals = data.values[np.isfinite(data.values)]
            stats = _array_stats(vals)
            if not stats:
                raise ValueError(f"{d} 区域内无有效站点")
            meta: dict[str, Any] = {
                "datetime": resolved_dt,
                "n_stations": int(data.n_stations),
                "n_valid": int(data.n_valid),
            }
            if threshold is not None:
                meta["threshold"] = threshold
                meta["n_exceed"] = int((vals > threshold).sum())
                meta["exceed_rate_pct"] = round(
                    100 * meta["n_exceed"] / len(vals), 1
                )
            out.append(
                RecentDaily(
                    date=d,
                    ok=True,
                    value=stats.get("mean"),
                    stats=stats,
                    meta=meta,
                )
            )
        except (FileNotFoundError, ValueError, KeyError) as e:
            out.append(
                RecentDaily(
                    date=d,
                    ok=False,
                    value=None,
                    stats={},
                    meta={},
                    error=str(e).splitlines()[0],
                )
            )

    return out


def temporal_summary(daily: list[RecentDaily]) -> dict[str, Any]:
    """Window means, window-to-window changes and the linear daily trend."""
    return {
        "windows": _window_summaries(daily),
        "changes": _change_summaries(daily),
        "trend": _trend_summary(daily),
    }


def _window_summaries(daily: list[RecentDaily]) -> dict[str, dict[str, Any]]:
    windows: dict[str, dict[str, Any]] = {}
    n = len(daily)
    specs = [
        ("last_7", max(0, n - 7), n),
        ("prev_7", max(0, n - 14), max(0, n - 7)),
        ("last_30", max(0, n - 30), n),
        ("prev_30", max(0, n - 60), max(0, n - 30)),
        ("last_365", max(0, n - 365), n),
    ]
    for name, start, end in specs:
        if end <= start or end - start < _required_span(name):
            continue
        windows[name] = _summarize_rows(daily[start:end])
    return windows


def _change_summaries(daily: list[RecentDaily]) -> dict[str, dict[str, Any]]:
    windows = _window_summaries(daily)
    pairs = [
        ("last_7_vs_prev_7", "last_7", "prev_7"),
        ("last_30_vs_prev_30", "last_30", "prev_30"),
    ]
    out: dict[str, dict[str, Any]] = {}
    for name, cur_key, prev_key in pairs:
        cur = windows.get(cur_key, {})
        prev = windows.get(prev_key, {})
        cur_mean = cur.get("mean")
        prev_mean = prev.get("mean")
        if cur_mean is None or prev_mean is None:
            continue
        abs_change = round(float(cur_mean) - float(prev_mean), 3)
        pct_change = None
        if prev_mean != 0:
            pct_change = round(100 * abs_change / float(prev_mean), 1)
        out[name] = {
            "current_mean": cur_mean,
            "previous_mean": prev_mean,
            "abs_change": abs_change,
            "pct_change": pct_change,
            "direction": _direction(abs_change),
            "current_valid_days": cur.get("valid_days", 0),
            "previous_valid_days": prev.get("valid_days", 0),
        }
    return out


def _trend_summary(daily: list[RecentDaily]) -> dict[str, Any]:
    xs = []
    ys = []
    for i, row in enumerate(daily):
        if row.ok and row.value is not None and np.isfinite(row.value):
            xs.append(i)
            ys.append(float(row.value))
    if len(ys) < 2:
        return {
            "valid_days": len(ys),
            "slope_per_day": None,
            "direction": "flat",
        }
    slope = float(
        np.polyfit(np.asarray(xs, dtype=float), np.asarray(ys), 1)[0]
    )
    return {
        "valid_days": len(ys),
        "slope_per_day": round(slope, 4),
        "direction": _direction(slope),
    }


def _summarize_rows(rows: list[RecentDaily]) -> dict[str, Any]:
    values = np.asarray(
        [row.value for row in rows if row.ok and row.value is not None],
        dtype=float,
    )
    stats = _array_stats(values)
    stats["valid_days"] = len(values)
    stats["requested_days"] = len(rows)
    return stats


def _grid_stats(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    geometry: Any,
) -> dict[str, Any]:
    stats = _array_stats(grid)
    if stats:
        coverage_pct, n_valid_region, total_region_pixels = (
            grid_coverage_in_region(LON, LAT, grid, geometry)
        )
        stats["coverage_pct"] = coverage_pct
        stats["valid_region_pixels"] = n_valid_region
        stats["total_region_pixels"] = total_region_pixels
        stats["grid_shape"] = list(grid.shape)
    return stats


def _array_stats(values: np.ndarray) -> dict[str, Any]:
    return basic_stats(np.asarray(values, dtype=float))


def _direction(delta: float) -> str:
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _required_span(name: str) -> int:
    if name.endswith("_7"):
        return 7
    if name.endswith("_30"):
        return 30
    if name.endswith("_365"):
        return 365
    return 1
