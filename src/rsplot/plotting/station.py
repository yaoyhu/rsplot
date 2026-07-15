"""Station scatter plot pipeline.

Plots ground monitoring station data as colored dots on a map,
with red circles for stations exceeding air quality limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import matplotlib.colors as mcolors
import numpy as np

from rsplot.config import AQI_COLORS
from rsplot.plotting.colormaps import STATION_CONCENTRATION_CMAP
from rsplot.plotting.map_frame import (
    add_basemap_tiles,
    add_region_boundaries,
    configure_map_axes,
    create_map_frame,
    finalize_map_figure,
)

if TYPE_CHECKING:
    from cartopy.mpl.geoaxes import GeoAxes
    from matplotlib.collections import PathCollection

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData


def build_aqi_colormap() -> tuple[
    mcolors.ListedColormap, mcolors.BoundaryNorm
]:
    """Build a discrete colormap matching official AQI color bands."""
    bounds = [0] + [bound for bound, _ in AQI_COLORS]
    colors = [color for _, color in AQI_COLORS]
    cmap = mcolors.ListedColormap(colors)
    norm = mcolors.BoundaryNorm(bounds, cmap.N)
    return cmap, norm


def station_marker_size(level: str) -> int:
    """Marker area by region level, in points squared."""
    return {
        "country": 18,
        "key_region": 32,
        "province": 46,
        "city": 76,
        "county": 110,
    }.get(level, 46)


# Compatibility aliases for callers that used these helpers.
_build_aqi_cmap = build_aqi_colormap
_station_marker_size = station_marker_size


def draw_station_layer(
    ax: GeoAxes,
    data: StationData,
    region: RegionInfo,
    *,
    threshold: float | None = None,
) -> PathCollection | None:
    """Draw station values and exceedance rings on an existing map axes."""
    valid = np.isfinite(data.values)
    lon = data.lon[valid]
    lat = data.lat[valid]
    values = data.values[valid]

    if len(values) == 0:
        ax.text(
            0.5,
            0.5,
            "No valid data",
            transform=ax.transAxes,
            ha="center",
            fontsize=14,
        )
        return None

    marker_size = station_marker_size(region.level)
    if data.var_name == "AQI":
        cmap, norm = build_aqi_colormap()
        scatter = ax.scatter(
            lon,
            lat,
            c=values,
            cmap=cmap,
            norm=norm,
            s=marker_size,
            edgecolors="#333",
            linewidths=0.3,
            transform=ccrs.PlateCarree(),
            zorder=5,
        )
    else:
        vmin = float(np.nanpercentile(values, 5))
        vmax = float(np.nanpercentile(values, 95))
        scatter = ax.scatter(
            lon,
            lat,
            c=values,
            cmap=STATION_CONCENTRATION_CMAP,
            vmin=vmin,
            vmax=vmax,
            s=marker_size,
            edgecolors="#333",
            linewidths=0.3,
            transform=ccrs.PlateCarree(),
            zorder=5,
        )

    if threshold is not None:
        exceed_mask = values > threshold
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
    return scatter


def plot_station(
    data: StationData,
    region: RegionInfo,
    *,
    threshold: float | None = None,
    dpi: int = 300,
    basemap: bool | None = None,
    tianditu_key: str | None = None,
    title: str | None = None,
    output: str | None = None,
    colorbar_label: str = "",
) -> None:
    """Draw a station scatter map for the given region."""
    frame = create_map_frame(
        region,
        dpi=dpi,
        basemap=basemap,
        tianditu_key=tianditu_key,
    )
    fig = frame.fig
    ax = frame.ax
    add_basemap_tiles(frame, region)
    add_region_boundaries(ax, region)
    scatter = draw_station_layer(ax, data, region, threshold=threshold)
    configure_map_axes(ax, region, use_basemap=frame.use_basemap)

    if scatter is not None:
        shrink = (
            0.6
            if region.level in ("country", "key_region", "province")
            else 0.7
        )
        colorbar = fig.colorbar(scatter, ax=ax, shrink=shrink, pad=0.05)
        if colorbar_label:
            colorbar.set_label(colorbar_label)

    use_title = (
        title if title is not None else f"{data.var_name} - {region.name}"
    )
    ax.set_title(use_title, fontsize=14)
    finalize_map_figure(fig, dpi=dpi, output=output)
