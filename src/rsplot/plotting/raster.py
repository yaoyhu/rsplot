"""Core raster plotting pipeline.

Unified entry point for all administrative levels. Takes gridded data
and RegionInfo, produces a publication-quality map.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np

from rsplot.plotting.colormaps import register_rsplot_colormaps
from rsplot.plotting.map_frame import (
    add_basemap_tiles,
    add_region_boundaries,
    add_subdivision_labels,
    clip_raster_to_region,
    configure_map_axes,
    create_map_frame,
    figure_size_for_level,
    finalize_map_figure,
    set_map_title,
)

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.plotting.station_focus import StationFocus


def plot_raster(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    region: RegionInfo,
    *,
    # overridable params
    dpi: int = 200,
    cmap: str = "turbo",
    vmin: float = 0.0,
    vmax: float = 20.0,
    basemap: bool | None = None,
    tianditu_key: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    output: str | None = None,
    coverage_geometry: BaseGeometry | None = None,
    station_focus: StationFocus | None = None,
    colorbar_label: str = "NO2 VCD (x10^15 molec/cm2)",
) -> None:
    """Draw a raster map for the given region.

    Parameters
    ----------
    LON, LAT, grid : 2-D arrays from gridding pipeline.
    region : RegionInfo from resolve_region.
    basemap : override region.params.basemap if not None.
    output : save to file path. If None, plt.show().
    """
    register_rsplot_colormaps()

    # --- Figure setup ---
    frame = create_map_frame(
        region,
        dpi=dpi,
        basemap=basemap,
        tianditu_key=tianditu_key,
    )
    fig = frame.fig
    ax = frame.ax

    # --- Raster layer ---
    alpha = 0.55 if frame.use_basemap else 1.0
    im = ax.pcolormesh(
        LON,
        LAT,
        grid,
        transform=ccrs.PlateCarree(),
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="auto",
        alpha=alpha,
    )
    clip_raster_to_region(im, ax, region, coverage_geometry=coverage_geometry)

    # --- Basemap tiles (beneath boundaries, above raster) ---
    add_basemap_tiles(frame, region)
    add_region_boundaries(ax, region)
    if station_focus is not None:
        from rsplot.plotting.station_focus import add_station_focus

        add_station_focus(ax, region, station_focus)
    configure_map_axes(ax, region, use_basemap=frame.use_basemap)

    # Colorbar
    shrink = 0.6 if region.level in ("key_region", "province") else 0.7
    plt.colorbar(im, ax=ax, shrink=shrink, pad=0.05).set_label(colorbar_label)

    # Title
    if title is None:
        title = f"TROPOMI - {region.name}"
    set_map_title(ax, title, subtitle)

    finalize_map_figure(fig, dpi=dpi, output=output)


# Backward-compatible aliases for callers that imported the old private
# helpers. Internal plotting modules use the explicit map-frame API.
_figsize_for_level = figure_size_for_level
_add_sub_labels = add_subdivision_labels
