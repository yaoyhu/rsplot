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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from rich.console import Console

from rsplot.geo.gridding import (
    fill_nan_gaps,
    mask_to_region,
    region_grid_mask,
    smooth_grid,
)
from rsplot.readers import get_product_info
from rsplot.temporal import (
    WindowResult,
    compute_window_mean,
    parse_date_window,
)

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo


__all__ = [
    "FnrResult",
    "WindowResult",
    "classify_regime",
    "compute_fnr",
    "compute_window_mean",
    "parse_date_window",
    "regime_percentages",
    "validate_fnr_thresholds",
]


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


def validate_fnr_thresholds(
    *,
    voc_threshold: float = FNR_VOC_LIMIT,
    nox_threshold: float = FNR_NOX_LIMIT,
    display_max: float = FNR_DISPLAY_MAX,
) -> tuple[float, float, float]:
    """Validate FNR regime/display thresholds and return normalized floats."""
    values = {
        "voc_threshold": float(voc_threshold),
        "nox_threshold": float(nox_threshold),
        "display_max": float(display_max),
    }
    for name, value in values.items():
        if not np.isfinite(value):
            raise ValueError(f"{name} 必须是有限数字")
    if values["voc_threshold"] < 0:
        raise ValueError("voc_threshold 必须 >= 0")
    if values["voc_threshold"] >= values["nox_threshold"]:
        raise ValueError("voc_threshold 必须小于 nox_threshold")
    if values["nox_threshold"] >= values["display_max"]:
        raise ValueError("nox_threshold 必须小于 display_max")
    return (
        values["voc_threshold"],
        values["nox_threshold"],
        values["display_max"],
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
    fnr: np.ndarray  # HCHO_mean / NO2_mean, masked
    hcho_mean: np.ndarray  # raw masked mean, 10^15 molec/cm²
    no2_mean: np.ndarray  # raw masked mean, 10^15 molec/cm²
    hcho_mean_filled: np.ndarray  # small-gap-filled diagnostic field
    no2_mean_filled: np.ndarray  # small-gap-filled diagnostic field
    n_valid_hcho: np.ndarray  # int count of valid days per pixel
    n_valid_no2: np.ndarray  # same for NO2
    dates_requested: list[str]
    dates_found_hcho: list[str]
    dates_found_no2: list[str]
    dates_failed_hcho: dict[str, str]  # date → error message
    dates_failed_no2: dict[str, str]
    n_min: int
    no2_min_column: float
    diagnostic_masks: dict[str, np.ndarray]
    processing: str | None = None
    daily_metadata_no2: dict[str, Any] = field(default_factory=dict)
    daily_metadata_hcho: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def compute_fnr(
    region: RegionInfo,
    dates: list[str],
    *,
    res: float,
    qa_threshold: float,
    cloud_fraction_max: float = 0.5,
    processing: str | None = None,
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

    if processing is None:
        no2_reader = get_product_info("no2").reader_cls()
        hcho_reader = get_product_info("hcho").reader_cls()
    else:
        no2_info = get_product_info("no2", processing=processing)
        hcho_info = get_product_info("hcho", processing=processing)
        no2_reader = no2_info.create_reader()
        hcho_reader = hcho_info.create_reader()
        processing = no2_info.processing
    no2_reader.cloud_fraction_max = cloud_fraction_max
    hcho_reader.cloud_fraction_max = cloud_fraction_max

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
    region_mask = region_grid_mask(LON, LAT, region.geometry)
    hcho_raw = mask_to_region(
        LON,
        LAT,
        hcho_win.grid,
        region.geometry,
        region_mask=region_mask,
    )
    no2_raw = mask_to_region(
        LON,
        LAT,
        no2_win.grid,
        region.geometry,
        region_mask=region_mask,
    )
    hcho_filled = fill_nan_gaps(LON, LAT, hcho_win.grid)
    no2_filled = fill_nan_gaps(LON, LAT, no2_win.grid)

    # --- Mask to region boundary ---
    fnr = mask_to_region(
        LON, LAT, fnr, region.geometry, region_mask=region_mask
    )
    hcho_filled = mask_to_region(
        LON,
        LAT,
        hcho_filled,
        region.geometry,
        region_mask=region_mask,
    )
    no2_filled = mask_to_region(
        LON,
        LAT,
        no2_filled,
        region.geometry,
        region_mask=region_mask,
    )

    if smooth_sigma is not None:
        fnr_valid_mask = np.isfinite(fnr)
        fnr = smooth_grid(
            fnr,
            region.geometry,
            LON,
            LAT,
            sigma=smooth_sigma,
            region_mask=region_mask,
        )
        # smooth_grid interpolates over NaNs before convolution. Restore the
        # scientific validity mask so smoothing cannot create new FNR pixels.
        fnr[~fnr_valid_mask] = np.nan

    return FnrResult(
        processing=processing,
        daily_metadata_no2=no2_win.daily_metadata,
        daily_metadata_hcho=hcho_win.daily_metadata,
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
def classify_regime(
    fnr: np.ndarray,
    *,
    voc_threshold: float = FNR_VOC_LIMIT,
    nox_threshold: float = FNR_NOX_LIMIT,
) -> np.ndarray:
    """Return int codes: 0=VOC-limited, 1=transition, 2=NOx-limited, -1=NaN."""
    voc_threshold = float(voc_threshold)
    nox_threshold = float(nox_threshold)
    if not np.isfinite(voc_threshold) or not np.isfinite(nox_threshold):
        raise ValueError("FNR regime thresholds 必须是有限数字")
    if voc_threshold < 0:
        raise ValueError("voc_threshold 必须 >= 0")
    if voc_threshold >= nox_threshold:
        raise ValueError("voc_threshold 必须小于 nox_threshold")
    code = np.full(fnr.shape, -1, dtype=np.int8)
    valid = np.isfinite(fnr)
    code[valid & (fnr < voc_threshold)] = 0
    code[valid & (fnr >= voc_threshold) & (fnr <= nox_threshold)] = 1
    code[valid & (fnr > nox_threshold)] = 2
    return code


def regime_percentages(
    fnr: np.ndarray,
    *,
    voc_threshold: float = FNR_VOC_LIMIT,
    nox_threshold: float = FNR_NOX_LIMIT,
) -> dict[str, float]:
    """% of valid pixels in each regime."""
    code = classify_regime(
        fnr,
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
    )
    valid_total = int((code >= 0).sum())
    if valid_total == 0:
        return {"voc_limited": 0.0, "transition": 0.0, "nox_limited": 0.0}
    return {
        "voc_limited": round(100 * int((code == 0).sum()) / valid_total, 1),
        "transition": round(100 * int((code == 1).sum()) / valid_total, 1),
        "nox_limited": round(100 * int((code == 2).sum()) / valid_total, 1),
    }
