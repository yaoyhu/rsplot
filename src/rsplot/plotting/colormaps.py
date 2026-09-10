"""Project colormap definitions."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.colors as mcolors
import numpy as np

HCHO_CMAP = "rsplot_hcho"
NO2_CMAP = "rsplot_no2"
COLORMAP_22 = "rsplot_colormap_22"
STATION_CONCENTRATION_CMAP = "rsplot_station_concentration"


def register_rsplot_colormaps() -> None:
    """Register custom colormaps used by rsplot plots."""
    _register(_build_colormap_22(COLORMAP_22))
    _register(_build_colormap_22(HCHO_CMAP))
    _register(
        mcolors.LinearSegmentedColormap.from_list(
            NO2_CMAP,
            [
                "#C2C8E1",
                "#9BA9DC",
                "#4C9DF4",
                "#86D1F9",
                "#A7E5EF",
                "#FEFC59",
                "#FD7822",
                "#FC131F",
                "#A3090E",
            ],
        )
    )
    _register(
        mcolors.LinearSegmentedColormap.from_list(
            STATION_CONCENTRATION_CMAP,
            [
                "#1a9850",
                "#66bd63",
                "#a6d96a",
                "#d9ef8b",
                "#fee08b",
                "#fdae61",
                "#f46d43",
                "#d73027",
                "#a50026",
            ],
        )
    )


def _build_colormap_22(name: str) -> mcolors.Colormap:
    cmap_file = Path(__file__).with_name("colormap_22.txt")
    cmap = mcolors.ListedColormap(np.loadtxt(cmap_file), name=name)
    cmap.set_under("w")
    return cmap


def _register(cmap: mcolors.Colormap) -> None:
    if cmap.name not in mpl.colormaps:
        mpl.colormaps.register(cmap)
