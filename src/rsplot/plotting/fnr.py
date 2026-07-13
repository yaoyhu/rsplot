"""FNR (HCHO/NO2) map plotting with discrete regime colormap.

Uses the same boundary / basemap / gridline conventions as plot_raster,
but swaps the continuous colorbar for a 3-segment discrete one aligned
with the active VOC/NOx thresholds so the regime readout is directly
visible on the map.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap

from rsplot.fnr import (
    FNR_DISPLAY_MAX,
    FNR_NOX_LIMIT,
    FNR_VOC_LIMIT,
    validate_fnr_thresholds,
)
from rsplot.plotting.map_frame import (
    add_basemap_tiles,
    add_region_boundaries,
    configure_map_axes,
    create_map_frame,
    finalize_map_figure,
)

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
    frame = create_map_frame(
        region,
        dpi=dpi,
        basemap=basemap,
        tianditu_key=tianditu_key,
    )
    fig = frame.fig
    ax = frame.ax

    cmap, norm = _build_fnr_cmap(
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
    )
    alpha = 0.65 if frame.use_basemap else 0.9
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

    add_basemap_tiles(frame, region)
    add_region_boundaries(ax, region)
    configure_map_axes(ax, region, use_basemap=frame.use_basemap)

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

    finalize_map_figure(fig, dpi=dpi, output=output)
