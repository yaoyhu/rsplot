"""Combined raster + station overlay plotting.

Satellite raster as the background colored field, 国控 station observations
on top as colored dots. Each layer keeps its own colorbar so the two
quantity scales stay independent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from cartopy.feature import ShapelyFeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

from rsplot.plotting.colormaps import (
    STATION_CONCENTRATION_CMAP,
    register_rsplot_colormaps,
)
from rsplot.plotting.raster import _add_sub_labels, _figsize_for_level
from rsplot.plotting.station import _build_aqi_cmap, _station_marker_size
from rsplot.tiles.tianditu import TianDiTuTiles

if TYPE_CHECKING:
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
) -> None:
    """Draw satellite raster + station scatter on the same axes.

    The raster uses a reduced alpha so station markers stay legible; when
    a basemap is requested the raster alpha is reduced further. The two
    colorbars share the right side — raster on top, stations below —
    so each quantity keeps its own scale.
    """
    params = region.params
    use_basemap = basemap if basemap is not None else params.basemap
    register_rsplot_colormaps()

    # --- Figure setup ---
    if use_basemap and tianditu_key:
        tiles = TianDiTuTiles(tk=tianditu_key, layer="img")
        projection = tiles.crs
    else:
        tiles = None
        projection = ccrs.PlateCarree()

    fig, ax = plt.subplots(
        figsize=_figsize_for_level(region.level),
        dpi=dpi,
        subplot_kw={"projection": projection},
    )

    # --- Raster layer (beneath everything else) ---
    raster_alpha = 0.45 if use_basemap else 0.7
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

    # --- Basemap tiles ---
    if tiles is not None:
        ax.add_image(tiles, params.zoom)

    # --- Detail boundaries (dotted) ---
    if (
        region.detail_boundary_gdf is not None
        and len(region.detail_boundary_gdf) > 0
    ):
        ax.add_feature(
            ShapelyFeature(
                region.detail_boundary_gdf.geometry,
                ccrs.PlateCarree(),
                edgecolor="#aaa",
                facecolor="none",
                linewidth=0.25,
                linestyle=":",
            )
        )

    # --- Sub-boundaries ---
    if (
        region.sub_boundary_gdf is not None
        and len(region.sub_boundary_gdf) > 0
    ):
        is_county_sub = region.level == "city"
        ax.add_feature(
            ShapelyFeature(
                region.sub_boundary_gdf.geometry,
                ccrs.PlateCarree(),
                edgecolor="#888" if not is_county_sub else "#666",
                facecolor="none",
                linewidth=0.4 if not is_county_sub else 0.6,
                linestyle="-" if not is_county_sub else "--",
            )
        )
        _add_sub_labels(ax, region)

    # --- Main boundary (red) ---
    if region.main_boundary_gdf is not None:
        ax.add_feature(
            ShapelyFeature(
                region.main_boundary_gdf.geometry,
                ccrs.PlateCarree(),
                edgecolor="red",
                facecolor="none",
                linewidth=params.boundary_linewidth,
            )
        )

    # --- Station overlay ---
    valid = np.isfinite(data.values)
    lon = data.lon[valid]
    lat = data.lat[valid]
    vals = data.values[valid]

    sc = None
    if len(vals) > 0:
        marker_size = _station_marker_size(region.level)

        is_aqi = data.var_name == "AQI"
        if is_aqi:
            cmap, norm = _build_aqi_cmap()
            sc = ax.scatter(
                lon, lat, c=vals, cmap=cmap, norm=norm,
                s=marker_size, edgecolors="#111", linewidths=0.4,
                transform=ccrs.PlateCarree(), zorder=5,
            )
        else:
            p5 = float(np.nanpercentile(vals, 5))
            p95 = float(np.nanpercentile(vals, 95))
            sc = ax.scatter(
                lon, lat, c=vals, cmap=STATION_CONCENTRATION_CMAP,
                vmin=p5, vmax=p95,
                s=marker_size, edgecolors="#111", linewidths=0.4,
                transform=ccrs.PlateCarree(), zorder=5,
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

    # --- Map decorations ---
    if not use_basemap:
        ax.coastlines(linewidth=0.5, color="#333")
        ax.add_feature(cfeature.OCEAN, facecolor="#e6f2ff", zorder=0)

    lon_min, lon_max, lat_min, lat_max = region.extent
    pad = params.pad
    ax.set_extent(
        [lon_min - pad, lon_max + pad, lat_min - pad, lat_max + pad],
        crs=ccrs.PlateCarree(),
    )

    gl = ax.gridlines(
        draw_labels=True, linewidth=0.2, linestyle="--", alpha=0.5
    )
    gl.top_labels = gl.right_labels = False
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER
    gl.xlocator = mticker.MultipleLocator(params.grid_step)
    gl.ylocator = mticker.MultipleLocator(params.grid_step)

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

    # Reserve room on the right for the two inset colorbars — plain
    # tight_layout() ignores inset_axes and would crop them off.
    fig.tight_layout(rect=[0, 0, 0.9, 1])

    # --- Output ---
    if output:
        fig.savefig(output, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
