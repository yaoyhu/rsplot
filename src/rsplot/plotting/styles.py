"""Font registration and matplotlib style configuration."""

from __future__ import annotations

import os

import matplotlib as mpl
from matplotlib import font_manager


def setup_fonts(font_dir: str) -> None:
    """Register Chinese fonts and set matplotlib defaults.

    Looks for Microsoft YaHei in font_dir. Falls back gracefully
    if fonts are not found (labels will use default sans-serif).
    """
    candidates = [
        os.path.join(font_dir, "MicrosoftYaHei", "微软雅黑.ttf"),
        os.path.join(font_dir, "MicrosoftYaHei", "微软雅黑粗体.ttf"),
    ]

    registered = False
    for fp in candidates:
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp)
            registered = True

    if registered:
        mpl.rcParams["font.family"] = "sans-serif"
        mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei"]

    mpl.rcParams["axes.unicode_minus"] = False
