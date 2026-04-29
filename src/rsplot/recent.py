"""Recent-day JSON summaries for raster and station data.

The ``recent`` command is intentionally read/analysis only: it produces a
compact JSON payload for comparing the last week/month/year without drawing
maps. It reuses the existing product readers, gridding, and station filters so
its daily numbers match the plotting commands' data path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from rich.console import Console
from rich.progress import track

from rsplot.config import STATION_VAR_META, get_exceedance_threshold
from rsplot.geo.gridding import fill_nan_gaps, grid_data, mask_to_region
from rsplot.readers import ProductInfo
from rsplot.readers.guokong import (
    mask_stations_to_region,
    read_stations,
)

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
            f"日期无效: '{end_date}'，请检查年月日是否真实存在 "
            f"(原始错误: {e})"
        ) from e

    start = end - timedelta(days=days - 1)
    return [
        (start + timedelta(days=i)).strftime("%Y%m%d")
        for i in range(days)
    ]


def summarize_recent_raster(
    *,
    region: "RegionInfo",
    product: str,
    prod_info: ProductInfo,
    data_dir: str,
    dates: list[str],
    res: float,
    qa_threshold: float,
    console: Console | None = None,
) -> list[RecentDaily]:
    """Read daily raster swaths and summarize each day over the region."""
    if console is None:
        console = Console()

    reader = prod_info.reader_cls()
    buf = 1.0
    read_extent = (
        region.extent[0] - buf,
        region.extent[1] + buf,
        region.extent[2] - buf,
        region.extent[3] + buf,
    )
    out: list[RecentDaily] = []

    for d in track(dates, description=f"[cyan]统计 {product.upper()} 最近数据..."):
        try:
            swath = reader.read(data_dir, d, read_extent, qa_threshold)
            LON, LAT, grid_raw = grid_data(
                swath.lon, swath.lat, swath.values, read_extent, res
            )
            grid = mask_to_region(
                LON, LAT, fill_nan_gaps(LON, LAT, grid_raw), region.geometry
            )
            stats = _grid_stats(grid)
            if not stats:
                raise ValueError(f"{d} 区域内无有效网格")
            out.append(
                RecentDaily(
                    date=d,
                    ok=True,
                    value=stats.get("mean"),
                    stats=stats,
                    meta={
                        "n_pixels": int(swath.n_pixels),
                        "n_files": int(swath.n_files),
                        "n_broken": int(swath.n_broken),
                    },
                )
            )
        except (FileNotFoundError, ValueError) as e:
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


def summarize_recent_station(
    *,
    region: "RegionInfo",
    data_dir: str,
    dates: list[str],
    var_name: str,
    console: Console | None = None,
) -> list[RecentDaily]:
    """Read daily latest-hour station files and summarize each day."""
    if console is None:
        console = Console()

    buf = 0.5
    read_extent = (
        region.extent[0] - buf,
        region.extent[1] + buf,
        region.extent[2] - buf,
        region.extent[3] + buf,
    )
    threshold = get_exceedance_threshold(var_name)
    out: list[RecentDaily] = []

    for d in track(dates, description=f"[cyan]统计 {var_name} 站点最近数据..."):
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


def build_recent_result(
    *,
    region: "RegionInfo",
    source: str,
    dates: list[str],
    daily: list[RecentDaily],
    params: dict[str, Any],
    output: str,
    product: str | None = None,
    variable: str | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    """Build the JSON payload for a recent run."""
    daily_rows = [_daily_to_json(row) for row in daily]
    failed = {row.date: row.error for row in daily if not row.ok and row.error}
    found = [row for row in daily if row.ok]

    result: dict[str, Any] = {
        "command": "recent",
        "image": None,
        "sidecar": output,
        "source": source,
        "region": {
            "name": region.name,
            "level": region.level,
            "extent": [round(x, 3) for x in region.extent],
        },
        "period": {
            "start": dates[0],
            "end": dates[-1],
            "days_requested": len(dates),
        },
        "params": params,
        "availability": {
            "days_found": len(found),
            "days_failed": len(failed),
            "failed_dates": failed,
        },
        "daily": daily_rows,
        "windows": _window_summaries(daily),
        "changes": _change_summaries(daily),
        "trend": _trend_summary(daily),
        "warnings": _warnings(daily),
    }
    if product is not None:
        result["product"] = product
    if variable is not None:
        result["variable"] = variable
    if unit:
        result["unit"] = unit
    return result


def write_recent_result(result: dict[str, Any], output: str) -> str:
    """Write a recent JSON result and return the path."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(path)


def _daily_to_json(row: RecentDaily) -> dict[str, Any]:
    data: dict[str, Any] = {
        "date": row.date,
        "ok": row.ok,
        "stats": row.stats,
        "meta": row.meta,
    }
    if row.error:
        data["error"] = row.error
    return data


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
        return {"valid_days": len(ys), "slope_per_day": None, "direction": "flat"}
    slope = float(np.polyfit(np.asarray(xs, dtype=float), np.asarray(ys), 1)[0])
    return {
        "valid_days": len(ys),
        "slope_per_day": round(slope, 4),
        "direction": _direction(slope),
    }


def _warnings(daily: list[RecentDaily]) -> list[str]:
    if not daily:
        return []
    valid_days = sum(1 for row in daily if row.ok)
    rate = valid_days / len(daily)
    warnings: list[str] = []
    if valid_days == 0:
        warnings.append("请求窗口内无有效日期。")
    elif rate < 0.5:
        warnings.append("有效日期少于请求天数的一半，变化判断可信度较低。")
    return warnings


def _summarize_rows(rows: list[RecentDaily]) -> dict[str, Any]:
    values = np.asarray(
        [row.value for row in rows if row.ok and row.value is not None],
        dtype=float,
    )
    stats = _array_stats(values)
    stats["valid_days"] = int(len(values))
    stats["requested_days"] = int(len(rows))
    return stats


def _grid_stats(grid: np.ndarray) -> dict[str, Any]:
    total = int(grid.size)
    stats = _array_stats(grid[np.isfinite(grid)])
    if stats:
        stats["coverage_pct"] = round(100 * stats["n"] / total, 1)
        stats["grid_shape"] = list(grid.shape)
    return stats


def _array_stats(values: np.ndarray) -> dict[str, Any]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return {}
    return {
        "n": int(len(finite)),
        "min": _round(np.min(finite)),
        "max": _round(np.max(finite)),
        "mean": _round(np.mean(finite)),
        "median": _round(np.median(finite)),
        "p10": _round(np.percentile(finite, 10)),
        "p25": _round(np.percentile(finite, 25)),
        "p75": _round(np.percentile(finite, 75)),
        "p90": _round(np.percentile(finite, 90)),
    }


def _round(value: float, ndigits: int = 2) -> float | None:
    if not np.isfinite(value):
        return None
    return round(float(value), ndigits)


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
