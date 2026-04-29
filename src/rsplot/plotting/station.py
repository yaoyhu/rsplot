"""Station scatter plot pipeline.

Plots ground monitoring station data as colored dots on a map,
with red circles for stations exceeding air quality limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from cartopy.feature import ShapelyFeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

from rsplot.config import AQI_COLORS
from rsplot.plotting.raster import _add_sub_labels, _figsize_for_level
from rsplot.tiles.tianditu import TianDiTuTiles

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData


def _build_aqi_cmap() -> tuple[mcolors.ListedColormap, mcolors.BoundaryNorm]:
    """Build a discrete colormap matching official AQI color bands."""
    bounds = [0] + [b for b, _ in AQI_COLORS]
    colors = [c for _, c in AQI_COLORS]
    cmap = mcolors.ListedColormap(colors)
    norm = mcolors.BoundaryNorm(bounds, cmap.N)
    return cmap, norm


def _station_marker_size(level: str) -> int:
    """Marker area by region level, in points squared."""
    return {
        "country": 18,
        "key_region": 32,
        "province": 46,
        "city": 76,
        "county": 110,
    }.get(level, 46)


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
    """Draw a station scatter map for the given region.

    Parameters
    ----------
    data : StationData from guokong reader.
    region : RegionInfo from resolve_region.
    threshold : value above which a red exceedance circle is drawn.
    """
    params = region.params
    use_basemap = basemap if basemap is not None else params.basemap

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

    # --- Basemap tiles ---
    if tiles is not None:
        ax.add_image(tiles, params.zoom)

    # --- Detail boundaries (counties in province view, dotted) ---
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

    # --- Sub-boundaries (grey) ---
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

    # --- Filter to valid data ---
    valid = np.isfinite(data.values)
    lon = data.lon[valid]
    lat = data.lat[valid]
    vals = data.values[valid]

    if len(vals) == 0:
        ax.text(
            0.5, 0.5, "No valid data",
            transform=ax.transAxes, ha="center", fontsize=14,
        )
    else:
        # --- Marker size by level ---
        marker_size = _station_marker_size(region.level)

        # --- Colormap / norm ---
        is_aqi = data.var_name == "AQI"
        if is_aqi:
            cmap, norm = _build_aqi_cmap()
            sc = ax.scatter(
                lon, lat, c=vals, cmap=cmap, norm=norm,
                s=marker_size, edgecolors="#333", linewidths=0.3,
                transform=ccrs.PlateCarree(), zorder=5,
            )
        else:
            p5 = float(np.nanpercentile(vals, 5))
            p95 = float(np.nanpercentile(vals, 95))
            sc = ax.scatter(
                lon, lat, c=vals, cmap="YlOrRd",
                vmin=p5, vmax=p95,
                s=marker_size, edgecolors="#333", linewidths=0.3,
                transform=ccrs.PlateCarree(), zorder=5,
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

        # --- Colorbar ---
        shrink = 0.6 if region.level in ("country", "key_region", "province") else 0.7
        cb = plt.colorbar(sc, ax=ax, shrink=shrink, pad=0.05)
        if colorbar_label:
            cb.set_label(colorbar_label)

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

    # Gridlines
    gl = ax.gridlines(
        draw_labels=True, linewidth=0.2, linestyle="--", alpha=0.5
    )
    gl.top_labels = gl.right_labels = False
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER
    gl.xlocator = mticker.MultipleLocator(params.grid_step)
    gl.ylocator = mticker.MultipleLocator(params.grid_step)

    # Title
    if title is None:
        title = f"{data.var_name} - {region.name}"
    ax.set_title(title, fontsize=14)

    plt.tight_layout()

    # --- Output ---
    if output:
        fig.savefig(output, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
