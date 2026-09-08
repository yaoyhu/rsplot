"""Shared date-window and temporal gridding utilities.

These helpers are intentionally product-agnostic. FNR and raster window
commands both depend on them, while legacy imports from :mod:`rsplot.fnr`
remain available for compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from rich.console import Console
from rich.progress import track

from rsplot.geo.gridding import grid_data

if TYPE_CHECKING:
    from rsplot.readers.base import BaseReader


DEFAULT_INPUT_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class HourlyTimeMatch:
    """One user-facing hour adapted to a data source's timezone."""

    input_datetime: str
    input_timezone: str
    data_timezone: str
    input_time: datetime
    data_time: datetime

    @property
    def data_datetime(self) -> str:
        """Return the data-source hour in compact ``YYYYMMDDHH`` form."""
        return self.data_time.strftime("%Y%m%d%H")


def adapt_hourly_time(
    value: str,
    *,
    input_timezone: str = DEFAULT_INPUT_TIMEZONE,
    data_timezone: str = "UTC",
    label: str = "时次",
) -> HourlyTimeMatch:
    """Interpret a compact user hour and adapt it to a data timezone.

    CLI callers use China standard time by default. Data readers can choose
    their archive timezone explicitly, which keeps timezone conversion out of
    filename/path logic and makes the same adapter reusable by other sources.
    """
    if not value.isdigit() or len(value) != 10:
        raise ValueError(
            f"{label}需要精确小时，收到 '{value}'，应为 YYYYMMDDHH。"
        )
    try:
        source_tz = ZoneInfo(input_timezone)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"未知输入时区 '{input_timezone}'。") from e
    try:
        target_tz = ZoneInfo(data_timezone)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"未知数据时区 '{data_timezone}'。") from e
    try:
        naive = datetime.strptime(value, "%Y%m%d%H")
    except ValueError as e:
        raise ValueError(f"无效{label} '{value}'。") from e

    input_time = naive.replace(tzinfo=source_tz)
    return HourlyTimeMatch(
        input_datetime=value,
        input_timezone=input_timezone,
        data_timezone=data_timezone,
        input_time=input_time,
        data_time=input_time.astimezone(target_tz),
    )


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
    daily_metadata: dict[str, Any] = field(default_factory=dict)


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

    sum_grid: np.ndarray | None = None
    valid_counts: np.ndarray | None = None
    dates_found: list[str] = []
    dates_failed: dict[str, str] = {}
    daily_metadata: dict[str, Any] = {}
    n_pix_total = 0
    n_files_total = 0
    n_broken_total = 0
    LON: np.ndarray | None = None
    LAT: np.ndarray | None = None

    for date in track(dates, description=f"[cyan]读取 {label} 窗口..."):
        try:
            batch = read_scan_mean(
                reader=reader,
                data_dir=data_dir,
                request=date,
                extent=extent,
                res=res,
                qa_threshold=qa_threshold,
            )
            if batch.metadata:
                daily_metadata[date] = batch.metadata
            n_pix_total += batch.n_pixels
            n_files_total += batch.n_files
            n_broken_total += batch.n_broken
            day_lon, day_lat, grid = batch.LON, batch.LAT, batch.grid
            if not np.isfinite(grid).any():
                raise ValueError(batch.failure_message())
            LON, LAT = day_lon, day_lat
            if sum_grid is None:
                sum_grid = np.zeros(grid.shape, dtype=float)
                valid_counts = np.zeros(grid.shape, dtype=np.int32)
            finite = np.isfinite(grid)
            np.add(sum_grid, grid, out=sum_grid, where=finite)
            valid_counts += finite
            dates_found.append(date)
        except (FileNotFoundError, ValueError) as e:
            dates_failed[date] = str(e).splitlines()[0]

    if LON is None or LAT is None or sum_grid is None or valid_counts is None:
        first_errors = "\n  ".join(
            f"{date}: {message}"
            for date, message in list(dates_failed.items())[:5]
        )
        raise ValueError(
            f"窗口 {dates[0]}~{dates[-1]} 内 {label} 全部失败：\n  "
            f"{first_errors}"
        )

    n_valid = valid_counts.astype(np.int16)
    mean = np.full(LON.shape, np.nan, dtype=float)
    np.divide(
        sum_grid,
        valid_counts,
        out=mean,
        where=valid_counts > 0,
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
        daily_metadata=daily_metadata,
    )


@dataclass
class ScanMean:
    """An unfilled grid mean with per-cell temporal sample counts."""

    LON: np.ndarray
    LAT: np.ndarray
    grid: np.ndarray
    n_valid: np.ndarray
    n_pixels: int
    n_files: int
    n_broken: int
    metadata: dict[str, Any]

    def failure_message(self) -> str:
        """Keep CLI errors compact; full per-file diagnostics stay in JSON."""
        message = (
            f"{self.metadata.get('request', '')} 区域内无有效扫描 "
            f"({self.n_files} 文件, {self.n_broken} 损坏)。"
        )
        examples = list(self.metadata.get("failed_files", {}).items())[:3]
        if examples:
            from pathlib import Path

            message += " " + "; ".join(
                f"{Path(path).name}: {error}" for path, error in examples
            )
        return message


def read_scan_mean(
    *,
    reader: BaseReader,
    data_dir: str,
    request: str,
    extent: tuple[float, float, float, float],
    res: float,
    qa_threshold: float = 0.5,
) -> ScanMean:
    """Grid each scan independently, then average valid scans equally."""
    # A NaN sentinel establishes the grid even if every scan is invalid.
    lon, lat, template = grid_data(
        np.array([extent[0]]),
        np.array([extent[2]]),
        np.array([np.nan]),
        extent,
        res,
    )
    footprints = getattr(reader, "uses_footprints", False)
    if footprints:
        from rsplot.geo.footprints import overlap_mean, regular_grid

        lon, lat = regular_grid(extent, res)
        template = np.full(lon.shape, np.nan)
    total = np.zeros(template.shape, dtype=float)
    counts = np.zeros(template.shape, dtype=np.int32)
    n_pixels = n_files = n_broken = 0
    scans = []
    iterator = getattr(reader, "iter_scans", None)
    scans_iter = (
        iterator(data_dir, request, extent, qa_threshold)
        if iterator is not None
        else (reader.read(data_dir, request, extent, qa_threshold),)
    )
    for scan in scans_iter:
        n_pixels += scan.n_pixels
        n_files += scan.n_files
        n_broken += scan.n_broken
        if scan.metadata:
            scans.append(scan.metadata)
        if not scan.n_pixels:
            continue
        if footprints:
            if scan.corner_lon is None or scan.corner_lat is None:
                raise ValueError("GEMS 扫描缺少像元边界，不能退回中心点分箱。")
            grid = overlap_mean(
                scan.corner_lon, scan.corner_lat, scan.values, lon, lat, res
            )
        else:
            _, _, grid = grid_data(
                scan.lon, scan.lat, scan.values, extent, res
            )
        valid = np.isfinite(grid)
        np.add(total, grid, out=total, where=valid)
        counts += valid
    mean = np.full(template.shape, np.nan)
    np.divide(total, counts, out=mean, where=counts > 0)
    covered = counts[counts > 0]
    metadata = {
        "request": request,
        "input_timezone": "Asia/Shanghai",
        "aggregation": "scan" if len(request) == 12 else "equal_scan_mean",
        "scans": scans,
        "n_scans_found": len(scans),
        "n_scans_valid": sum(s.get("n_pixels", 0) > 0 for s in scans),
        "failed_files": {s["file"]: s["error"] for s in scans if "error" in s},
        "coverage_scope": "read_extent",
        "read_extent": list(extent),
        "coverage_scans": {
            "min": int(covered.min()) if covered.size else 0,
            "max": int(covered.max()) if covered.size else 0,
            "mean": float(covered.mean()) if covered.size else 0.0,
        },
    }
    if footprints:
        metadata["spatial_aggregation"] = "footprint_overlap_area_mean"
        metadata["area_crs"] = "EPSG:6933"
        metadata["analysis_resolution_deg"] = res
        metadata["grid_alignment"] = "global_multiples_of_resolution"
    return ScanMean(
        lon,
        lat,
        mean,
        counts,
        n_pixels,
        n_files,
        n_broken,
        metadata if scans else {},
    )
