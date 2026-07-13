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
        fill_nan_gaps(lon, lat, values)
        if fill_gaps
        else np.asarray(values).copy()
    )
    prepared = mask_to_region(lon, lat, prepared, geometry)
    if smooth_sigma is not None:
        prepared = smooth_grid(
            prepared,
            geometry,
            lon,
            lat,
            sigma=smooth_sigma,
        )
    coverage, n_valid, total = grid_coverage_in_region(
        lon,
        lat,
        prepared,
        geometry,
    )
    return PreparedGrid(
        lon=lon,
        lat=lat,
        values=prepared,
        coverage_pct=coverage,
        n_valid_region=n_valid,
        total_region_pixels=total,
    )


def prepare_swath_grid(
    swath_lon: np.ndarray,
    swath_lat: np.ndarray,
    swath_values: np.ndarray,
    read_extent: tuple[float, float, float, float],
    resolution: float,
    geometry: BaseGeometry,
    *,
    smooth_sigma: float | None = None,
) -> PreparedGrid:
    """Grid a swath and apply the standard raster preparation sequence."""
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
        fill_gaps=True,
        smooth_sigma=smooth_sigma,
    )
