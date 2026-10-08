"""Reusable preparation steps for regional raster fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from rsplot.geo.gridding import (
    fill_nan_gaps,
    grid_coverage_in_region,
    grid_data,
    mask_to_region,
    region_grid_mask,
    smooth_grid,
)

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class PreparedGrid:
    """A region-masked grid and its stable coverage diagnostics."""

    lon: np.ndarray
    lat: np.ndarray
    values: np.ndarray
    coverage_pct: float
    n_valid_region: int
    total_region_pixels: int
    # Prepared source before administrative center masking, for display only.
    unmasked_values: np.ndarray | None = None


def buffered_extent(
    extent: tuple[float, float, float, float],
    padding: float,
) -> tuple[float, float, float, float]:
    """Expand ``(lon_min, lon_max, lat_min, lat_max)`` uniformly."""
    return (
        extent[0] - padding,
        extent[1] + padding,
        extent[2] - padding,
        extent[3] + padding,
    )


def prepare_existing_grid(
    lon: np.ndarray,
    lat: np.ndarray,
    values: np.ndarray,
    geometry: BaseGeometry,
    *,
    fill_gaps: bool,
    smooth_sigma: float | None = None,
) -> PreparedGrid:
    """Fill, region-mask, optionally smooth, and summarize an existing grid."""
    prepared = (
        fill_nan_gaps(lon, lat, values) if fill_gaps else np.asarray(values)
    )
    unmasked_values = prepared
    region_mask = region_grid_mask(lon, lat, geometry)
    prepared = mask_to_region(
        lon,
        lat,
        prepared,
        geometry,
        region_mask=region_mask,
    )
    if smooth_sigma is not None:
        prepared = smooth_grid(
            prepared,
            geometry,
            lon,
            lat,
            sigma=smooth_sigma,
            region_mask=region_mask,
        )
    coverage, n_valid, total = grid_coverage_in_region(
        lon,
        lat,
        prepared,
        geometry,
        region_mask=region_mask,
    )
    return PreparedGrid(
        lon=lon,
        lat=lat,
        values=prepared,
        coverage_pct=coverage,
        n_valid_region=n_valid,
        total_region_pixels=total,
        unmasked_values=unmasked_values,
    )


def prepare_swath_grid(
    swath_lon: np.ndarray,
    swath_lat: np.ndarray,
    swath_values: np.ndarray,
    read_extent: tuple[float, float, float, float],
    resolution: float,
    geometry: BaseGeometry,
) -> PreparedGrid:
    """Grid a swath into observed cells only; filling is display-only."""
    lon, lat, raw = grid_data(
        swath_lon,
        swath_lat,
        swath_values,
        read_extent,
        resolution,
    )
    return prepare_existing_grid(
        lon,
        lat,
        raw,
        geometry,
        fill_gaps=False,
    )


def region_cell_mask(
    lon: np.ndarray,
    lat: np.ndarray,
    geometry: BaseGeometry,
) -> np.ndarray:
    """Select rectilinear cells touching the region, including exterior centers.

    Edges match pcolormesh's midpoint convention. A singleton axis has zero
    width, matching the renderer when only one center is supplied.
    """
    from shapely import box, intersects

    if lon.ndim != 2 or lat.shape != lon.shape:
        raise ValueError("显示网格经纬度必须为同形状二维数组。")
    if not (np.allclose(lon, lon[0:1, :]) and np.allclose(lat, lat[:, 0:1])):
        raise ValueError("行政边界显示裁剪需要规则经纬度网格。")

    def edges(centers: np.ndarray) -> np.ndarray:
        if centers.size == 1:
            return np.repeat(centers, 2)
        half_steps = np.diff(centers) / 2
        return np.concatenate(
            (
                centers[:1] - half_steps[:1],
                centers[:-1] + half_steps,
                centers[-1:] + half_steps[-1:],
            )
        )

    x = edges(lon[0])
    y = edges(lat[:, 0])
    cells = box(x[:-1][None, :], y[:-1, None], x[1:][None, :], y[1:, None])
    return intersects(geometry, cells)


def prepare_display_grid(
    lon: np.ndarray,
    lat: np.ndarray,
    values: np.ndarray,
    geometry: BaseGeometry,
    *,
    smooth_sigma: float | None = None,
) -> np.ndarray:
    """Keep valid intersecting cells; exact geometry clipping is render-only.

    Input must precede the administrative center mask. Smoothing can use the
    surrounding buffer but cannot create newly valid cells. Statistics must
    continue to use PreparedGrid.values, never this display array.
    """
    visible = region_cell_mask(lon, lat, geometry)
    valid = np.isfinite(values)
    display = np.asarray(values)
    if smooth_sigma is not None and smooth_sigma > 0:
        # Normalized convolution avoids NaN-gap warnings on sparse scans.
        # This display-only operation does not change legacy statistics.
        from scipy.ndimage import gaussian_filter

        numerator = gaussian_filter(
            np.where(valid, values, 0.0),
            smooth_sigma,
            mode="constant",
            cval=0.0,
        )
        denominator = gaussian_filter(
            valid.astype(float),
            smooth_sigma,
            mode="constant",
            cval=0.0,
        )
        display = np.divide(
            numerator,
            denominator,
            out=np.full(values.shape, np.nan),
            where=denominator > 0,
        )
    return np.where(visible & valid, display, np.nan)
