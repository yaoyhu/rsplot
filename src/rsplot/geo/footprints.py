"""Area-overlap remapping and stable display support for gridded fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


def inferred_corner_grid(centers: np.ndarray) -> np.ndarray:
    """Estimate shared corners from the unfiltered 2-D native center lattice.

    Midpoints use adjacent native rows/columns, never adjacent QA survivors.
    Outer edges are linearly extrapolated. Missing geolocation stays missing.
    """
    if centers.ndim != 2 or min(centers.shape) < 2:
        raise ValueError("估算像元边界需要至少 2×2 的原始定位网格。")
    padded = np.pad(centers.astype(float), 1, mode="edge")
    padded[0, 1:-1] = 2 * centers[0] - centers[1]
    padded[-1, 1:-1] = 2 * centers[-1] - centers[-2]
    padded[:, 0] = 2 * padded[:, 1] - padded[:, 2]
    padded[:, -1] = 2 * padded[:, -2] - padded[:, -3]
    return (
        padded[:-1, :-1] + padded[1:, :-1] + padded[1:, 1:] + padded[:-1, 1:]
    ) / 4


def pixel_corners(corners: np.ndarray) -> np.ndarray:
    """Convert a shared (ny+1, nx+1) corner grid to (ny, nx, 4)."""
    return np.stack(
        [
            corners[:-1, :-1],
            corners[:-1, 1:],
            corners[1:, 1:],
            corners[1:, :-1],
        ],
        axis=-1,
    )


def regular_grid(
    extent: tuple[float, float, float, float],
    res: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Build globally aligned cell centers covering an extent."""
    west, east, south, north = extent
    x = (np.arange(np.floor(west / res), np.ceil(east / res)) + 0.5) * res
    y = (np.arange(np.floor(south / res), np.ceil(north / res)) + 0.5) * res
    return np.meshgrid(x, y)


def grid_edges(centers: np.ndarray, res: float) -> np.ndarray:
    return np.concatenate((centers - res / 2, centers[-1:] + res / 2))


def rectangle_corners(
    lon: np.ndarray,
    lat: np.ndarray,
    res: float,
) -> tuple[np.ndarray, np.ndarray]:
    x = grid_edges(lon[0], res)
    y = grid_edges(lat[:, 0], res)
    xx, yy = np.meshgrid(x, y)
    return pixel_corners(xx).reshape(-1, 4), pixel_corners(yy).reshape(-1, 4)


def overlap_mean(
    corner_lon: np.ndarray,
    corner_lat: np.ndarray,
    values: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    res: float,
) -> np.ndarray:
    """Remap valid source polygons with overlap-area weights in EPSG:6933.

    No extrapolation: a target needs positive-area overlap with a valid source.
    Chunked queries bound temporary target/intersection geometry allocations.
    """
    from pyproj import Transformer
    from shapely import STRtree, area, intersection, is_valid, polygons

    result = np.full(lon.size, np.nan)
    if not len(values):
        return result.reshape(lon.shape)
    transform = Transformer.from_crs(4326, 6933, always_xy=True)
    x, y = transform.transform(corner_lon, corner_lat)
    finite = (
        np.isfinite(values)
        & np.isfinite(x).all(axis=1)
        & np.isfinite(y).all(axis=1)
    )
    source = polygons(np.stack([x[finite], y[finite]], axis=-1))
    source_values = values[finite]
    valid = is_valid(source) & (area(source) > 0)
    source, source_values = source[valid], source_values[valid]
    if not len(source):
        return result.reshape(lon.shape)
    tree = STRtree(source)
    xcorners, ycorners = rectangle_corners(lon, lat, res)
    for start in range(0, lon.size, 8192):
        stop = min(start + 8192, lon.size)
        x, y = transform.transform(xcorners[start:stop], ycorners[start:stop])
        target = polygons(np.stack([x, y], axis=-1))
        ti, si = tree.query(target, predicate="intersects")
        if not len(ti):
            continue
        weights = area(intersection(target[ti], source[si]))
        # Shared edges can differ by a few floating-point ulps after projection.
        # Exclude numerical slivers, without extending support to empty cells.
        threshold = 1e-10 * np.minimum(area(target[ti]), area(source[si]))
        weights = np.where(weights > threshold, weights, 0.0)
        # Boundary-only touches do not supply an observation.
        sums = np.bincount(
            ti, weights=weights * source_values[si], minlength=len(target)
        )
        weight_sum = np.bincount(ti, weights=weights, minlength=len(target))
        np.divide(
            sums, weight_sum, out=result[start:stop], where=weight_sum > 0
        )
    return result.reshape(lon.shape)


def valid_grid_geometry(
    lon: np.ndarray,
    lat: np.ndarray,
    valid: np.ndarray,
    res: float,
) -> BaseGeometry:
    """Union valid analysis cells using row runs, preserving missing cells."""
    from shapely import box, union_all

    x = grid_edges(lon[0], res)
    y = grid_edges(lat[:, 0], res)
    rectangles = []
    for row, mask in enumerate(valid):
        changes = np.diff(np.r_[False, mask, False].astype(np.int8))
        starts, stops = (
            np.flatnonzero(changes == 1),
            np.flatnonzero(changes == -1),
        )
        rectangles.extend(box(x[starts], y[row], x[stops], y[row + 1]))
    return union_all(rectangles)


@dataclass
class FootprintDisplay:
    lon: np.ndarray
    lat: np.ndarray
    values: np.ndarray
    support: BaseGeometry


def prepare_footprint_display(
    lon: np.ndarray,
    lat: np.ndarray,
    values: np.ndarray,
    geometry: BaseGeometry,
    *,
    analysis_res: float,
    display_res: float,
    smooth_sigma: float | None = None,
) -> FootprintDisplay:
    """Resample a fixed field and return its invariant clipping geometry.

    The renderer must clip the colored layer to ``support``. Coarse display
    cells may span analysis holes; finite display values alone do not describe
    valid coverage. Analysis spacing is supplied by the caller.
    """
    from rsplot.geo.processing import prepare_display_grid, region_cell_mask

    finite = np.isfinite(values)
    support = valid_grid_geometry(lon, lat, finite, analysis_res).intersection(
        geometry
    )
    # Smooth only within the fixed analysis lattice, retaining QA/data holes.
    prepared = prepare_display_grid(
        lon, lat, values, geometry, smooth_sigma=smooth_sigma
    )
    x = grid_edges(lon[0], analysis_res)
    y = grid_edges(lat[:, 0], analysis_res)
    display_lon, display_lat = regular_grid(
        (x[0], x[-1], y[0], y[-1]), display_res
    )
    cx, cy = rectangle_corners(lon, lat, analysis_res)
    finite = np.isfinite(prepared).ravel()
    display = overlap_mean(
        cx[finite],
        cy[finite],
        prepared.ravel()[finite],
        display_lon,
        display_lat,
        display_res,
    )
    display = np.where(
        region_cell_mask(display_lon, display_lat, geometry), display, np.nan
    )
    return FootprintDisplay(display_lon, display_lat, display, support)
