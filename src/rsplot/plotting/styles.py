"""Font registration and matplotlib style configuration."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
from matplotlib import font_manager

from rsplot.plotting.colormaps import register_rsplot_colormaps


def setup_fonts(
    font_dir: str | None, hcho_cmap_file: str | None = None
) -> None:
    """Register Chinese fonts and set matplotlib defaults.

    Looks for Microsoft YaHei in font_dir. Falls back gracefully
    if fonts are not found (labels will use default sans-serif).
    """
    if not font_dir:
        mpl.rcParams["axes.unicode_minus"] = False
        register_rsplot_colormaps(hcho_cmap_file)
        return

    font_root = Path(font_dir)
    candidates = [
        font_root / "MicrosoftYaHei" / "微软雅黑.ttf",
        font_root / "MicrosoftYaHei" / "微软雅黑粗体.ttf",
    ]

    registered = False
    for path in candidates:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            registered = True

    if registered:
        mpl.rcParams["font.family"] = "sans-serif"
        mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei"]

    mpl.rcParams["axes.unicode_minus"] = False
    register_rsplot_colormaps(hcho_cmap_file)
