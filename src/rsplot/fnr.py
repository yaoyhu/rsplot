"""FNR (Formaldehyde-to-NO2 Ratio) computation with temporal averaging.

TROPOMI daily HCHO coverage is typically 30-50% over China (HCHO has
lower SNR and stricter cloud filters than NO2), so per-day FNR maps are
too fragmented to diagnose NOx/VOC-limited regimes reliably. The
standard fix in the literature (Duncan 2010, Jin & Holloway 2015,
Souri 2020 et al.) is:

    1. Average HCHO and NO2 columns *separately* over an N-day window
       (typically 7 or 30 days).
    2. Divide the averaged fields pixel-wise.
    3. Mask pixels with too few valid days, and pixels where the mean
       NO2 column is too low for the FNR interpretation to hold.

Regime classification (Duncan 2010):

    FNR < 1.0   →  VOC-limited   (reducing VOC more effective)
    1.0 ≤ FNR ≤ 2.0  →  Transition
    FNR > 2.0   →  NOx-limited   (reducing NOx more effective)

Both HCHO and NO2 readers return columns in 10^15 molec/cm², so FNR is
dimensionless and directly comparable with the literature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
from rich.console import Console
from rich.progress import track

from rsplot.geo.gridding import (
    fill_nan_gaps,
    grid_data,
    mask_to_region,
    smooth_grid,
)
from rsplot.readers import get_product_info

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo


# ---------------------------------------------------------------------------
# Regime thresholds (Duncan et al. 2010, widely reused in the literature)
# ---------------------------------------------------------------------------
FNR_VOC_LIMIT = 1.0
FNR_NOX_LIMIT = 2.0

# Minimum mean NO2 (10^15 molec/cm²) below which FNR is not meaningful.
# Duncan used 1.5, but over China most non-urban pixels sit below that;
# keep 0.5 as a softer default and flag in the JSON sidecar.
NO2_MIN_COLUMN = 0.5

# Display clamp for the FNR colorbar — beyond this the regime classification
# has already saturated.
FNR_DISPLAY_MAX = 6.0


# ---------------------------------------------------------------------------
# Date window parsing
# ---------------------------------------------------------------------------
def _parse_yyyymmdd(value: str, label: str = "日期") -> datetime:
    """Parse a YYYYMMDD string and report invalid calendar dates clearly."""
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError as e:
        raise ValueError(
            f"{label}无效: '{value}'，请检查年月日是否真实存在 "
            f"(原始错误: {e})"
        ) from e


def parse_date_window(arg: str, default_days: int) -> list[str]:
    """Parse a ``YYYYMMDD`` or ``YYYYMMDD-YYYYMMDD`` argument into a date list.

    - Single date → window is the ``default_days``-day period ending on
      that date (inclusive).
    - ``START-END`` → inclusive range; ``START`` and ``END`` can be equal.

    Returns YYYYMMDD strings in ascending order.
    """
    if "-" in arg:
        parts = arg.split("-")
        if len(parts) != 2 or any(len(p) != 8 or not p.isdigit() for p in parts):
            raise ValueError(
                f"日期范围格式错误: '{arg}'，应为 YYYYMMDD-YYYYMMDD"
            )
        start = _parse_yyyymmdd(parts[0], "开始日期")
        end = _parse_yyyymmdd(parts[1], "结束日期")
        if end < start:
            raise ValueError(f"日期范围起止颠倒: {arg}")
    else:
        if len(arg) != 8 or not arg.isdigit():
            raise ValueError(
                f"日期格式错误: '{arg}'，应为 YYYYMMDD 或 YYYYMMDD-YYYYMMDD"
            )
        end = _parse_yyyymmdd(arg)
        start = end - timedelta(days=default_days - 1)

    out = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Window-mean helper (used by both `rsplot fnr` and `rsplot raster --days`)
# ---------------------------------------------------------------------------
@dataclass
class WindowResult:
    """Per-product time-averaged grid over a date window.

    The mean field is *not* coverage-masked — callers apply their own
    ``n_min`` threshold against :attr:`n_valid` (FNR uses a combined
    NO2 ∧ HCHO mask; raster uses its own product-only threshold).
    """

    LON: np.ndarray
    LAT: np.ndarray
    grid: np.ndarray            # time-mean, NaN where every day was missing
    n_valid: np.ndarray         # int count of valid days per pixel
    dates_requested: list[str]
    dates_found: list[str]
    dates_failed: dict[str, str]
    n_pixels_total: int         # sum of swath pixels read across days
    n_files_total: int          # sum of swath files scanned
    n_broken_total: int         # sum of unreadable files


def compute_window_mean(
    *,
    reader,
    data_dir: str,
    dates: list[str],
    extent: tuple[float, float, float, float],
    res: float,
    qa_threshold: float,
    label: str = "数据",
    console: Console | None = None,
) -> WindowResult:
    """Read each date, regrid, return time-mean + per-pixel valid-day count.

    Each day that succeeds contributes one ``(ny, nx)`` grid to the stack;
    failed days (missing files / no valid pixels) become all-NaN slabs
    so the caller can still tell which dates fell out.
    """
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

    for d in track(dates, description=f"[cyan]读取 {label} 窗口..."):
        try:
            s = reader.read(data_dir, d, extent, qa_threshold=qa_threshold)
            _LON, _LAT, g = grid_data(s.lon, s.lat, s.values, extent, res)
            LON, LAT = _LON, _LAT
            stack.append(g)
            dates_found.append(d)
            n_pix_total += int(s.n_pixels)
            n_files_total += int(s.n_files)
            n_broken_total += int(s.n_broken)
        except (FileNotFoundError, ValueError) as e:
            dates_failed[d] = str(e).splitlines()[0]
            stack.append(None)

    if LON is None or LAT is None:
        first_errors = "\n  ".join(
            f"{d}: {msg}" for d, msg in list(dates_failed.items())[:5]
        )
        raise ValueError(
            f"窗口 {dates[0]}~{dates[-1]} 内 {label} 全部失败：\n  {first_errors}"
        )

    shape = LON.shape
    filled = [g if g is not None else np.full(shape, np.nan) for g in stack]
    arr = np.stack(filled, axis=0)  # (n_days, ny, nx)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(arr, axis=0)
    n_valid = np.isfinite(arr).sum(axis=0).astype(np.int16)

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


# ---------------------------------------------------------------------------
# FNR result container
# ---------------------------------------------------------------------------
@dataclass
class FnrResult:
    """Output of :func:`compute_fnr`.

    Grids are all ``(ny, nx)`` on the same LON/LAT meshgrid.
    """

    LON: np.ndarray
    LAT: np.ndarray
    fnr: np.ndarray           # HCHO_mean / NO2_mean, masked
    hcho_mean: np.ndarray     # raw masked mean, 10^15 molec/cm²
    no2_mean: np.ndarray      # raw masked mean, 10^15 molec/cm²
    hcho_mean_filled: np.ndarray  # small-gap-filled diagnostic field
    no2_mean_filled: np.ndarray   # small-gap-filled diagnostic field
    n_valid_hcho: np.ndarray  # int count of valid days per pixel
    n_valid_no2: np.ndarray   # same for NO2
    dates_requested: list[str]
    dates_found_hcho: list[str]
    dates_found_no2: list[str]
    dates_failed_hcho: dict[str, str]  # date → error message
    dates_failed_no2: dict[str, str]
    n_min: int
    no2_min_column: float
    diagnostic_masks: dict[str, np.ndarray]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def compute_fnr(
    region: RegionInfo,
    dates: list[str],
    *,
    res: float,
    qa_threshold: float,
    n_min: int,
    raster_dir_no2: str,
    raster_dir_hcho: str,
    no2_min_column: float = NO2_MIN_COLUMN,
    smooth_sigma: float | None = None,
    console: Console | None = None,
) -> FnrResult:
    """Read NO2 + HCHO over a date window and compute per-pixel FNR.

    Each daily swath/grid is first binned onto the same target grid, then
    the two time-stacks are averaged and divided. Pixels with fewer than
    ``n_min`` valid days in *either* product, or with mean NO2 below
    ``no2_min_column``, are masked to NaN.
    """
    if console is None:
        console = Console()

    buf = 1.0  # extent buffer to avoid edge artifacts during regridding
    read_extent = (
        region.extent[0] - buf,
        region.extent[1] + buf,
        region.extent[2] - buf,
        region.extent[3] + buf,
    )

    no2_reader = get_product_info("no2").reader_cls()
    hcho_reader = get_product_info("hcho").reader_cls()

    # --- Read each product over the window via the shared helper ---
    no2_win = compute_window_mean(
        reader=no2_reader,
        data_dir=raster_dir_no2,
        dates=dates,
        extent=read_extent,
        res=res,
        qa_threshold=qa_threshold,
        label="NO2",
        console=console,
    )
    hcho_win = compute_window_mean(
        reader=hcho_reader,
        data_dir=raster_dir_hcho,
        dates=dates,
        extent=read_extent,
        res=res,
        qa_threshold=qa_threshold,
        label="HCHO",
        console=console,
    )

    LON, LAT = no2_win.LON, no2_win.LAT
    shape = LON.shape

    # --- Combined coverage mask: need n_min valid days in BOTH products ---
    coverage_ok = (no2_win.n_valid >= n_min) & (hcho_win.n_valid >= n_min)

    # --- NO2-min mask: avoid dividing by tiny NO2 backgrounds ---
    no2_ok = np.isfinite(no2_win.grid) & (no2_win.grid >= no2_min_column)

    # HCHO retrieval noise can yield negative columns; do not let those
    # become negative FNR values that classify as VOC-limited.
    hcho_ok = np.isfinite(hcho_win.grid) & (hcho_win.grid >= 0)

    valid = coverage_ok & no2_ok & hcho_ok

    fnr = np.full(shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        fnr[valid] = hcho_win.grid[valid] / no2_win.grid[valid]

    # Keep raw mean fields for JSON statistics, and separately prepare
    # small-gap-filled diagnostic fields for users who want a less holey
    # view of the underlying columns. The FNR field itself is never filled.
    hcho_raw = mask_to_region(LON, LAT, hcho_win.grid, region.geometry)
    no2_raw = mask_to_region(LON, LAT, no2_win.grid, region.geometry)
    hcho_filled = fill_nan_gaps(LON, LAT, hcho_win.grid)
    no2_filled = fill_nan_gaps(LON, LAT, no2_win.grid)

    # --- Mask to region boundary ---
    fnr = mask_to_region(LON, LAT, fnr, region.geometry)
    hcho_filled = mask_to_region(LON, LAT, hcho_filled, region.geometry)
    no2_filled = mask_to_region(LON, LAT, no2_filled, region.geometry)

    if smooth_sigma is not None:
        fnr_valid_mask = np.isfinite(fnr)
        fnr = smooth_grid(fnr, region.geometry, LON, LAT, sigma=smooth_sigma)
        # smooth_grid interpolates over NaNs before convolution. Restore the
        # scientific validity mask so smoothing cannot create new FNR pixels.
        fnr[~fnr_valid_mask] = np.nan

    return FnrResult(
        LON=LON,
        LAT=LAT,
        fnr=fnr,
        hcho_mean=hcho_raw,
        no2_mean=no2_raw,
        hcho_mean_filled=hcho_filled,
        no2_mean_filled=no2_filled,
        n_valid_hcho=hcho_win.n_valid,
        n_valid_no2=no2_win.n_valid,
        dates_requested=list(dates),
        dates_found_hcho=hcho_win.dates_found,
        dates_found_no2=no2_win.dates_found,
        dates_failed_hcho=hcho_win.dates_failed,
        dates_failed_no2=no2_win.dates_failed,
        n_min=n_min,
        no2_min_column=no2_min_column,
        diagnostic_masks={
            "coverage_ok": coverage_ok,
            "no2_ok": no2_ok,
            "hcho_ok": hcho_ok,
            "final_valid": np.isfinite(fnr),
        },
    )


# ---------------------------------------------------------------------------
# Regime helpers (used by the plotter and the JSON builder)
# ---------------------------------------------------------------------------
def classify_regime(fnr: np.ndarray) -> np.ndarray:
    """Return int codes: 0=VOC-limited, 1=transition, 2=NOx-limited, -1=NaN."""
    code = np.full(fnr.shape, -1, dtype=np.int8)
    valid = np.isfinite(fnr)
    code[valid & (fnr < FNR_VOC_LIMIT)] = 0
    code[valid & (fnr >= FNR_VOC_LIMIT) & (fnr <= FNR_NOX_LIMIT)] = 1
    code[valid & (fnr > FNR_NOX_LIMIT)] = 2
    return code


def regime_percentages(fnr: np.ndarray) -> dict[str, float]:
    """% of valid pixels in each regime."""
    code = classify_regime(fnr)
    valid_total = int((code >= 0).sum())
    if valid_total == 0:
        return {"voc_limited": 0.0, "transition": 0.0, "nox_limited": 0.0}
    return {
        "voc_limited": round(100 * int((code == 0).sum()) / valid_total, 1),
        "transition": round(100 * int((code == 1).sum()) / valid_total, 1),
        "nox_limited": round(100 * int((code == 2).sum()) / valid_total, 1),
    }
