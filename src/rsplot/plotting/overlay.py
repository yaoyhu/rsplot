"""Combined raster + station overlay plotting.

A gridded raster layer (satellite or forecast) is drawn as the background
colored field, with 国控 station observations on top as colored dots. Each
layer keeps its own colorbar so the two quantity scales stay independent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import numpy as np

from rsplot.plotting.colormaps import (
    STATION_CONCENTRATION_CMAP,
    register_rsplot_colormaps,
)
from rsplot.plotting.map_frame import (
    add_basemap_tiles,
    add_region_boundaries,
    clip_raster_to_region,
    configure_map_axes,
    create_map_frame,
    finalize_map_figure,
)
from rsplot.plotting.station import (
    build_aqi_colormap,
    station_marker_size,
)

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData


def plot_overlay(
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    data: StationData,
    region: RegionInfo,
    *,
    # raster layer
    raster_cmap: str = "YlOrRd",
    raster_vmin: float = 0.0,
    raster_vmax: float = 20.0,
    raster_label: str = "",
    # station layer
    station_threshold: float | None = None,
    station_label: str = "",
    # shared
    dpi: int = 300,
    basemap: bool | None = None,
    tianditu_key: str | None = None,
    title: str | None = None,
    output: str | None = None,
    coverage_geometry: BaseGeometry | None = None,
) -> None:
    """Draw satellite raster + station scatter on the same axes.

    The raster uses a reduced alpha so station markers stay legible; when
    a basemap is requested the raster alpha is reduced further. The two
    colorbars share the right side — raster on top, stations below —
    so each quantity keeps its own scale.
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

    # --- Raster layer (beneath everything else) ---
    raster_alpha = 0.45 if frame.use_basemap else 0.7
    im = ax.pcolormesh(
        LON,
        LAT,
        grid,
        transform=ccrs.PlateCarree(),
        cmap=raster_cmap,
        vmin=raster_vmin,
        vmax=raster_vmax,
        shading="auto",
        alpha=raster_alpha,
        zorder=1,
    )
    clip_raster_to_region(im, ax, region, coverage_geometry=coverage_geometry)

    # --- Basemap tiles ---
    add_basemap_tiles(frame, region)
    add_region_boundaries(ax, region)

    # --- Station overlay ---
    valid = np.isfinite(data.values)
    lon = data.lon[valid]
    lat = data.lat[valid]
    vals = data.values[valid]

    sc = None
    if len(vals) > 0:
        marker_size = station_marker_size(region.level)

        is_aqi = data.var_name == "AQI"
        if is_aqi:
            cmap, norm = build_aqi_colormap()
            sc = ax.scatter(
                lon,
                lat,
                c=vals,
                cmap=cmap,
                norm=norm,
                s=marker_size,
                edgecolors="#111",
                linewidths=0.4,
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
        else:
            p5 = float(np.nanpercentile(vals, 5))
            p95 = float(np.nanpercentile(vals, 95))
            sc = ax.scatter(
                lon,
                lat,
                c=vals,
                cmap=STATION_CONCENTRATION_CMAP,
                vmin=p5,
                vmax=p95,
                s=marker_size,
                edgecolors="#111",
                linewidths=0.4,
                transform=ccrs.PlateCarree(),
                zorder=5,
            )

        # Red circle for exceedance
        if station_threshold is not None:
            exceed_mask = vals > station_threshold
            if exceed_mask.any():
                ax.scatter(
                    lon[exceed_mask],
                    lat[exceed_mask],
                    s=marker_size * 3,
                    facecolors="none",
                    edgecolors="red",
                    linewidths=1.5,
                    transform=ccrs.PlateCarree(),
                    zorder=6,
                )

    configure_map_axes(ax, region, use_basemap=frame.use_basemap)

    # --- Twin colorbars, hugging the right edge of the map ---
    # Using ax.inset_axes keeps the bars next to the plot instead of
    # letting them float out to the figure corners. Top half = raster,
    # bottom half = station, with a small gap between them.
    # Coords are in axes-fraction: [x0, y0, width, height].
    cax_raster = ax.inset_axes([1.03, 0.54, 0.025, 0.42])
    cb_raster = fig.colorbar(im, cax=cax_raster)
    if raster_label:
        cb_raster.set_label(raster_label, fontsize=9)
    cb_raster.ax.tick_params(labelsize=8)

    if sc is not None:
        cax_station = ax.inset_axes([1.03, 0.04, 0.025, 0.42])
        cb_station = fig.colorbar(sc, cax=cax_station)
        if station_label:
            cb_station.set_label(station_label, fontsize=9)
        cb_station.ax.tick_params(labelsize=8)

    # Title
    if title is None:
        title = f"{region.name} · raster + stations"
    ax.set_title(title, fontsize=14)

    # Reserve room on the right for the two inset colorbars.
    finalize_map_figure(
        fig,
        dpi=dpi,
        output=output,
        layout_rect=(0, 0, 0.9, 1),
    )
