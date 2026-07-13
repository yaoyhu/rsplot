"""Shared date-window and temporal gridding utilities.

These helpers are intentionally product-agnostic. FNR and raster window
commands both depend on them, while legacy imports from :mod:`rsplot.fnr`
remain available for compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
from rich.console import Console
from rich.progress import track

from rsplot.geo.gridding import grid_data

if TYPE_CHECKING:
    from rsplot.readers.base import BaseReader


def parse_yyyymmdd(value: str, label: str = "日期") -> datetime:
    """Parse a YYYYMMDD string and report invalid dates consistently."""
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError as e:
        raise ValueError(
            f"{label}无效: '{value}'，请检查年月日是否真实存在 (原始错误: {e})"
        ) from e


def parse_date_window(arg: str, default_days: int) -> list[str]:
    """Expand a single date or inclusive date range into ascending dates."""
    if "-" in arg:
        parts = arg.split("-")
        if len(parts) != 2 or any(
            len(p) != 8 or not p.isdigit() for p in parts
        ):
            raise ValueError(
                f"日期范围格式错误: '{arg}'，应为 YYYYMMDD-YYYYMMDD"
            )
        start = parse_yyyymmdd(parts[0], "开始日期")
        end = parse_yyyymmdd(parts[1], "结束日期")
        if end < start:
            raise ValueError(f"日期范围起止颠倒: {arg}")
    else:
        if len(arg) != 8 or not arg.isdigit():
            raise ValueError(
                f"日期格式错误: '{arg}'，应为 YYYYMMDD 或 YYYYMMDD-YYYYMMDD"
            )
        end = parse_yyyymmdd(arg)
        start = end - timedelta(days=default_days - 1)

    out = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


@dataclass
class WindowResult:
    """Per-product time-averaged grid over a date window."""

    LON: np.ndarray
    LAT: np.ndarray
    grid: np.ndarray
    n_valid: np.ndarray
    dates_requested: list[str]
    dates_found: list[str]
    dates_failed: dict[str, str]
    n_pixels_total: int
    n_files_total: int
    n_broken_total: int


def compute_window_mean(
    *,
    reader: BaseReader,
    data_dir: str,
    dates: list[str],
    extent: tuple[float, float, float, float],
    res: float,
    qa_threshold: float,
    label: str = "数据",
    console: Console | None = None,
) -> WindowResult:
    """Read daily swaths and return their grid mean and valid-day counts."""
    if console is None:
        console = Console()

    stack: list[np.ndarray | None] = []
    dates_found: list[str] = []
    dates_failed: dict[str, str] = {}
    n_pix_total = 0
    n_files_total = 0
    n_broken_total = 0
    LON: np.ndarray | None = None
    LAT: np.ndarray | None = None

    for date in track(dates, description=f"[cyan]读取 {label} 窗口..."):
        try:
            swath = reader.read(
                data_dir,
                date,
                extent,
                qa_threshold=qa_threshold,
            )
            day_lon, day_lat, grid = grid_data(
                swath.lon,
                swath.lat,
                swath.values,
                extent,
                res,
            )
            LON, LAT = day_lon, day_lat
            stack.append(grid)
            dates_found.append(date)
            n_pix_total += int(swath.n_pixels)
            n_files_total += int(swath.n_files)
            n_broken_total += int(swath.n_broken)
        except (FileNotFoundError, ValueError) as e:
            dates_failed[date] = str(e).splitlines()[0]
            stack.append(None)

    if LON is None or LAT is None:
        first_errors = "\n  ".join(
            f"{date}: {message}"
            for date, message in list(dates_failed.items())[:5]
        )
        raise ValueError(
            f"窗口 {dates[0]}~{dates[-1]} 内 {label} 全部失败：\n  "
            f"{first_errors}"
        )

    shape = LON.shape
    filled = [
        grid if grid is not None else np.full(shape, np.nan) for grid in stack
    ]
    values = np.stack(filled, axis=0)
    n_valid = np.isfinite(values).sum(axis=0).astype(np.int16)
    mean = np.full(shape, np.nan, dtype=float)
    np.divide(
        np.nansum(values, axis=0),
        n_valid,
        out=mean,
        where=n_valid > 0,
    )

    return WindowResult(
        LON=LON,
        LAT=LAT,
        grid=mean,
        n_valid=n_valid,
        dates_requested=list(dates),
        dates_found=dates_found,
        dates_failed=dates_failed,
        n_pixels_total=n_pix_total,
        n_files_total=n_files_total,
        n_broken_total=n_broken_total,
    )
