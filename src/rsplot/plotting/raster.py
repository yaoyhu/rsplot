"""Core raster plotting pipeline.

Unified entry point for all administrative levels. Takes gridded data
and RegionInfo, produces a publication-quality map.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from cartopy.feature import ShapelyFeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

from rsplot.tiles.tianditu import TianDiTuTiles

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo


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
    output: str | None = None,
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

    # --- Raster layer ---
    alpha = 0.55 if use_basemap else 1.0
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

    # --- Basemap tiles (beneath boundaries, above raster) ---
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
        # Sub-boundary labels
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

    # --- Map decorations ---
    if not use_basemap:
        ax.coastlines(linewidth=0.5, color="#333")
        ax.add_feature(cfeature.OCEAN, facecolor="#e6f2ff", zorder=0)

    # Set extent with padding
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

    # Colorbar
    shrink = 0.6 if region.level in ("key_region", "province") else 0.7
    plt.colorbar(im, ax=ax, shrink=shrink, pad=0.05).set_label(colorbar_label)

    # Title
    if title is None:
        title = f"TROPOMI - {region.name}"
    ax.set_title(title, fontsize=14)

    plt.tight_layout()

    # --- Output ---
    if output:
        fig.savefig(output, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def _figsize_for_level(level: str) -> tuple[float, float]:
    """Choose figure size based on admin level."""
    return {
        "country": (14, 12),
        "key_region": (12, 10),
        "province": (10, 10),
        "city": (10, 8),
        "county": (8, 7),
    }.get(level, (10, 8))


def _add_sub_labels(ax, region: RegionInfo) -> None:
    """Add name labels for sub-boundary features."""
    gdf = region.sub_boundary_gdf
    if gdf is None or len(gdf) == 0:
        return

    name_field = region.sub_name_field
    fontsize = region.params.label_fontsize

    for _, row in gdf.iterrows():
        pt = row.geometry.representative_point()
        # For key_region/province level: only label cities inside the region
        if region.level in (
            "key_region",
            "province",
        ) and not region.geometry.contains(pt):
            continue

        label = row[name_field]
        # Strip "市" suffix for city-level labels in province/key_region view
        if region.level in ("key_region", "province"):
            label = label.replace("市", "")

        ax.text(
            pt.x,
            pt.y,
            label,
            transform=ccrs.PlateCarree(),
            fontsize=fontsize,
            ha="center",
            va="center",
            color="#222",
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
        )
