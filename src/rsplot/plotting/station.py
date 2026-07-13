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
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.era5_wind import WindFieldData
    from rsplot.readers.guokong import StationData


def build_aqi_colormap() -> tuple[
    mcolors.ListedColormap, mcolors.BoundaryNorm
]:
    """Build a discrete colormap matching official AQI color bands."""
    bounds = [0] + [b for b, _ in AQI_COLORS]
    colors = [c for _, c in AQI_COLORS]
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


# Compatibility aliases for callers that used these pre-refactor helpers.
_build_aqi_cmap = build_aqi_colormap
_station_marker_size = station_marker_size


def wind_stride_for_shape(shape: tuple[int, int], level: str) -> int:
    """Choose a readable quiver stride for a regional ERA5 subset."""
    target = {
        "country": 32,
        "key_region": 30,
        "province": 28,
        "city": 24,
        "county": 20,
    }.get(level, 24)
    return max(1, round(max(shape) / target))


def _nice_wind_reference(speed: np.ndarray) -> float:
    """Return a compact, human-readable quiver-key magnitude."""
    value = float(np.nanpercentile(speed, 75))
    if value <= 0:
        return 1.0
    magnitude = 10 ** np.floor(np.log10(value))
    scaled = value / magnitude
    nice = 1.0 if scaled <= 1 else 2.0 if scaled <= 2 else 5.0
    return nice * magnitude


def plot_station(
    data: StationData,
    region: RegionInfo,
    *,
    wind: WindFieldData | None = None,
    wind_stride: int = 1,
    wind_scale: float | None = None,
    wind_width: float = 0.004,
    wind_cmap: str = "viridis",
    wind_vmin: float | None = None,
    wind_vmax: float | None = None,
    threshold: float | None = None,
    dpi: int = 300,
    basemap: bool | None = None,
    tianditu_key: str | None = None,
    title: str | None = None,
    output: str | None = None,
    colorbar_label: str = "",
) -> None:
    """Draw a station scatter map for the given region.

    Parameters
    ----------
    data : StationData from guokong reader.
    region : RegionInfo from resolve_region.
    threshold : value above which a red exceedance circle is drawn.
    """
    # --- Figure setup ---
    frame = create_map_frame(
        region,
        dpi=dpi,
        basemap=basemap,
        tianditu_key=tianditu_key,
    )
    fig = frame.fig
    ax = frame.ax

    # --- Basemap tiles ---
    add_basemap_tiles(frame, region)

    # --- ERA5 wind vectors (above basemap, below boundaries and stations) ---
    wind_quiver = None
    if wind is not None:
        step = max(1, wind_stride)
        sample = np.s_[::step, ::step]
        sampled_speed = wind.speed[sample]
        finite_speed = sampled_speed[np.isfinite(sampled_speed)]
        if len(finite_speed) > 0:
            use_wind_vmin = wind_vmin if wind_vmin is not None else 0.0
            use_wind_vmax = (
                wind_vmax
                if wind_vmax is not None
                else float(np.nanpercentile(finite_speed, 95))
            )
            if use_wind_vmax <= use_wind_vmin:
                use_wind_vmax = use_wind_vmin + 1.0
            wind_norm = mcolors.Normalize(use_wind_vmin, use_wind_vmax)
            wind_quiver = ax.quiver(
                wind.lon[sample],
                wind.lat[sample],
                wind.u[sample],
                wind.v[sample],
                sampled_speed,
                transform=ccrs.PlateCarree(),
                cmap=wind_cmap,
                norm=wind_norm,
                scale=wind_scale,
                pivot="middle",
                width=wind_width,
                alpha=0.9,
                zorder=3,
            )
            reference = _nice_wind_reference(finite_speed)
            ax.quiverkey(
                wind_quiver,
                0.86,
                0.035,
                reference,
                f"{reference:g} {wind.unit}",
                labelpos="E",
                coordinates="axes",
                fontproperties={"size": 8},
            )

    add_region_boundaries(ax, region)

    # --- Filter to valid data ---
    valid = np.isfinite(data.values)
    lon = data.lon[valid]
    lat = data.lat[valid]
    vals = data.values[valid]

    sc = None
    if len(vals) == 0:
        ax.text(
            0.5,
            0.5,
            "No valid data",
            transform=ax.transAxes,
            ha="center",
            fontsize=14,
        )
    else:
        # --- Marker size by level ---
        marker_size = station_marker_size(region.level)

        # --- Colormap / norm ---
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
                edgecolors="#333",
                linewidths=0.3,
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
                edgecolors="#333",
                linewidths=0.3,
                transform=ccrs.PlateCarree(),
                zorder=5,
            )

        # --- Red circles for exceedance ---
        if threshold is not None:
            exceed_mask = vals > threshold
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

    # --- Colorbars ---
    if sc is not None and wind_quiver is not None:
        cax_station = ax.inset_axes([1.03, 0.54, 0.025, 0.42])
        cb_station = fig.colorbar(sc, cax=cax_station)
        if colorbar_label:
            cb_station.set_label(colorbar_label, fontsize=9)
        cb_station.ax.tick_params(labelsize=8)

        cax_wind = ax.inset_axes([1.03, 0.04, 0.025, 0.42])
        cb_wind = fig.colorbar(wind_quiver, cax=cax_wind)
        cb_wind.set_label(f"Wind speed ({wind.unit})", fontsize=9)
        cb_wind.ax.tick_params(labelsize=8)
    elif sc is not None:
        shrink = (
            0.6
            if region.level in ("country", "key_region", "province")
            else 0.7
        )
        cb_station = fig.colorbar(sc, ax=ax, shrink=shrink, pad=0.05)
        if colorbar_label:
            cb_station.set_label(colorbar_label)
    elif wind_quiver is not None:
        cb_wind = fig.colorbar(wind_quiver, ax=ax, shrink=0.7, pad=0.05)
        cb_wind.set_label(f"Wind speed ({wind.unit})")

    # Title
    if title is None:
        if wind is None:
            title = f"{data.var_name} - {region.name}"
        else:
            title = f"{data.var_name} + ERA5 {wind.level} wind - {region.name}"
    ax.set_title(title, fontsize=14)

    layout_rect = (
        (0, 0, 0.9, 1) if wind_quiver is not None and sc is not None else None
    )
    finalize_map_figure(
        fig,
        dpi=dpi,
        output=output,
        layout_rect=layout_rect,
    )
