"""Gridding and smoothing for satellite swath data.

Bins irregular satellite pixels onto a regular lat/lon grid,
applies region masking and optional NaN-aware Gaussian smoothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.stats import binned_statistic_2d

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


def grid_data(
    lon: np.ndarray,
    lat: np.ndarray,
    values: np.ndarray,
    extent: tuple[float, float, float, float],
    res: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bin irregular data onto a regular grid.

    Parameters
    ----------
    lon, lat, values : 1-D arrays of the same length.
    extent : (lon_min, lon_max, lat_min, lat_max).
    res : grid resolution in degrees.

    Returns
    -------
    LON, LAT : 2-D meshgrid arrays.
    grid : 2-D array of mean values (NaN where no data).
    """
    lon_min, lon_max, lat_min, lat_max = extent
    lon_bins = np.arange(lon_min, lon_max + res, res)
    lat_bins = np.arange(lat_min, lat_max + res, res)

    grid = (
        binned_statistic_2d(
            lon, lat, values, statistic="mean", bins=[lon_bins, lat_bins]
        ).statistic.T
    )  # transpose: binned_statistic_2d returns (x, y), we want (lat, lon)

    lon_c = 0.5 * (lon_bins[:-1] + lon_bins[1:])
    lat_c = 0.5 * (lat_bins[:-1] + lat_bins[1:])
    LON, LAT = np.meshgrid(lon_c, lat_c)

    return LON, LAT, grid


def fill_nan_gaps(
    LON: np.ndarray, LAT: np.ndarray, grid: np.ndarray, max_gap: int = 3
) -> np.ndarray:
    """Fill small NaN gaps using nearest-neighbor interpolation.

    Only fills NaN cells within *max_gap* cells of valid data, preventing
    long-range extrapolation across large empty swath gaps.
    """
    from scipy.interpolate import NearestNDInterpolator
    from scipy.ndimage import binary_dilation

    valid = np.isfinite(grid)
    if valid.all() or not valid.any():
        return grid

    # Only fill NaN cells near existing data
    fill_zone = binary_dilation(valid, iterations=max_gap) & ~valid
    if not fill_zone.any():
        return grid

    interp = NearestNDInterpolator(
        np.column_stack((LON[valid], LAT[valid])), grid[valid]
    )
    filled = grid.copy()
    filled[fill_zone] = interp(LON[fill_zone], LAT[fill_zone])
    return filled


def mask_to_region(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    geometry: BaseGeometry,
    *,
    region_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Mask grid to region boundary using grid-center containment."""
    if region_mask is None:
        region_mask = region_grid_mask(LON, LAT, geometry)
    return np.where(region_mask, grid, np.nan)


def region_grid_mask(
    LON: np.ndarray,
    LAT: np.ndarray,
    geometry: BaseGeometry,
) -> np.ndarray:
    """Return True for grid centers inside the administrative geometry."""
    from shapely import contains_xy

    return contains_xy(geometry, LON, LAT)


def grid_coverage_in_region(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    geometry: BaseGeometry,
    *,
    region_mask: np.ndarray | None = None,
) -> tuple[float, int, int]:
    """Return valid-pixel coverage using only region-interior grid centers."""
    if region_mask is None:
        region_mask = region_grid_mask(LON, LAT, geometry)
    total = int(region_mask.sum())
    valid = int((region_mask & np.isfinite(grid)).sum())
    pct = round(100 * valid / total, 1) if total else 0.0
    return pct, valid, total


def smooth_grid(
    grid: np.ndarray,
    geometry: BaseGeometry,
    LON: np.ndarray,
    LAT: np.ndarray,
    sigma: float = 2.0,
    *,
    region_mask: np.ndarray | None = None,
) -> np.ndarray:
    """NaN-aware Gaussian smoothing using astropy, re-masked to region boundary.

    Uses astropy's convolve with nan_treatment='interpolate' to avoid
    boundary dilution that scipy.ndimage.gaussian_filter causes.
    """
    from astropy.convolution import Gaussian2DKernel, convolve

    kernel = Gaussian2DKernel(x_stddev=sigma)
    smoothed = convolve(
        grid, kernel, nan_treatment="interpolate", preserve_nan=False
    )

    # Re-mask to region boundary (smoothing bleeds outside)
    if region_mask is None:
        region_mask = region_grid_mask(LON, LAT, geometry)
    smoothed[~region_mask] = np.nan

    return smoothed
