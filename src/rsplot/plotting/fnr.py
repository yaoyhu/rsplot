"""FNR (HCHO/NO2) map plotting with discrete regime colormap.

Uses the same boundary / basemap / gridline conventions as plot_raster,
but swaps the continuous colorbar for a 3-segment discrete one aligned
with the active VOC/NOx thresholds so the regime readout is directly
visible on the map.
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
from matplotlib.colors import BoundaryNorm, ListedColormap

from rsplot.fnr import (
    FNR_DISPLAY_MAX,
    FNR_NOX_LIMIT,
    FNR_VOC_LIMIT,
    validate_fnr_thresholds,
)
from rsplot.plotting.raster import _add_sub_labels, _figsize_for_level
from rsplot.tiles.tianditu import TianDiTuTiles

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo


# Fixed regime palette — deliberately kept consistent across levels so
# readers recognise the same semantics at first glance.
_REGIME_COLORS = [
    "#d7301f",  # VOC-limited  (FNR < 1) — red
    "#fdae61",  # transition   (1-2)     — orange/yellow
    "#2c7fb8",  # NOx-limited  (FNR > 2) — blue
]


def _build_fnr_cmap(
    *,
    voc_threshold: float,
    nox_threshold: float,
    display_max: float,
) -> tuple[ListedColormap, BoundaryNorm]:
    cmap = ListedColormap(_REGIME_COLORS, name="fnr_regime")
    cmap.set_bad(color="#dddddd", alpha=0.0)  # NaN → transparent
    bounds = [0.0, voc_threshold, nox_threshold, display_max]
    norm = BoundaryNorm(bounds, ncolors=cmap.N)
    return cmap, norm


def plot_fnr(
    LON: np.ndarray,
    LAT: np.ndarray,
    fnr: np.ndarray,
    region: RegionInfo,
    *,
    dpi: int = 300,
    basemap: bool | None = None,
    tianditu_key: str | None = None,
    title: str | None = None,
    output: str | None = None,
    subtitle: str | None = None,
    voc_threshold: float = FNR_VOC_LIMIT,
    nox_threshold: float = FNR_NOX_LIMIT,
    display_max: float = FNR_DISPLAY_MAX,
) -> None:
    """Draw an FNR regime map."""
    voc_threshold, nox_threshold, display_max = validate_fnr_thresholds(
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
    )
    params = region.params
    use_basemap = basemap if basemap is not None else params.basemap

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

    cmap, norm = _build_fnr_cmap(
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
    )
    alpha = 0.65 if use_basemap else 0.9
    im = ax.pcolormesh(
        LON,
        LAT,
        fnr,
        transform=ccrs.PlateCarree(),
        cmap=cmap,
        norm=norm,
        shading="auto",
        alpha=alpha,
    )

    if tiles is not None:
        ax.add_image(tiles, params.zoom)

    # --- Boundaries (same layering as plot_raster) ---
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

    # --- Discrete colorbar with regime labels centered in each band ---
    shrink = 0.6 if region.level in ("key_region", "province") else 0.7
    cb = plt.colorbar(
        im,
        ax=ax,
        shrink=shrink,
        pad=0.05,
        ticks=[
            voc_threshold / 2,
            (voc_threshold + nox_threshold) / 2,
            (nox_threshold + display_max) / 2,
        ],
    )
    cb.ax.set_yticklabels(
        [
            f"VOC-limited\n(<{voc_threshold:g})",
            f"Transition\n({voc_threshold:g}-{nox_threshold:g})",
            f"NOx-limited\n(>{nox_threshold:g})",
        ],
        fontsize=8,
    )
    cb.set_label("FNR = HCHO / NO2", fontsize=9)

    # --- Title + subtitle ---
    if title is None:
        title = f"FNR regime — {region.name}"
    ax.set_title(title, fontsize=14)
    if subtitle:
        ax.text(
            0.5,
            -0.08,
            subtitle,
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=9,
            color="#444",
        )

    plt.tight_layout()

    if output:
        fig.savefig(output, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
