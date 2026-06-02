"""Project colormap definitions."""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib as mpl
import matplotlib.colors as mcolors
import numpy as np

HCHO_CMAP = "rsplot_hcho"
STATION_CONCENTRATION_CMAP = "rsplot_station_concentration"


def register_rsplot_colormaps(hcho_cmap_file: str | None = None) -> None:
    """Register custom colormaps used by rsplot plots."""
    _register(_build_hcho_cmap(hcho_cmap_file))
    _register(
        mcolors.LinearSegmentedColormap.from_list(
            STATION_CONCENTRATION_CMAP,
            [
                "#fff7ec",
                "#fee8c8",
                "#fdbb84",
                "#fc8d59",
                "#e34a33",
                "#b30000",
            ],
        )
    )


def _build_hcho_cmap(hcho_cmap_file: str | None) -> mcolors.Colormap:
    if hcho_cmap_file:
        cmap_file = Path(os.path.expandvars(hcho_cmap_file)).expanduser()
        if not cmap_file.exists():
            raise FileNotFoundError(
                f"Configured HCHO colormap file does not exist: {cmap_file}"
            )
        data = np.loadtxt(cmap_file)
        if data.shape != (256, 3):
            raise ValueError(
                f"{cmap_file} must contain a 256x3 RGB colormap table, "
                f"got shape {data.shape}"
            )
        cmap = mcolors.ListedColormap(data, name=HCHO_CMAP)
    else:
        cmap = mcolors.LinearSegmentedColormap.from_list(
            HCHO_CMAP,
            [
                "#ffffff",
                "#fff7bc",
                "#fec44f",
                "#fd8d3c",
                "#e31a1c",
                "#800026",
            ],
        )
    cmap.set_under("w")
    return cmap


def _register(cmap: mcolors.Colormap) -> None:
    if cmap.name not in mpl.colormaps:
        mpl.colormaps.register(cmap)
