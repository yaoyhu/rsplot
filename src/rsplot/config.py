"""Configuration management for rsplot.

# TODO: Loads defaults from ~/.config/rsplot/config.toml if present,
CLI arguments override everything.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

load_dotenv()


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
DEFAULT_DATA_DIRS: dict[str, str] = {
    "no2": "/satellite/exports3/dhxu114/tropomi/NRT/NO2/product",
    "o3": "/satellite/exports3/dhxu114/tropomi/NRT/O3TOT/product",
}
DEFAULT_GEOJSON_DIR = "/satellite/d4/yaoyhu/tiandi"
DEFAULT_FONT_DIR = "/satellite/d4/yaoyhu/fonts"
DEFAULT_TIANDITU_KEY = os.getenv("TIANDITU_API_KEY")


CONFIG_PATH = Path.home() / ".config" / "rsplot" / "config.toml"


# ---------------------------------------------------------------------------
# Per-level default parameters
# ---------------------------------------------------------------------------
@dataclass
class LevelParams:
    """Plotting parameters derived from administrative level."""

    res: float
    basemap: bool
    smooth_sigma: float | None
    grid_step: float
    pad: float
    boundary_linewidth: float
    label_fontsize: float
    zoom: int  # TianDiTu tile zoom level


LEVEL_DEFAULTS: dict[str, LevelParams] = {
    "key_region": LevelParams(
        res=0.05,
        basemap=False,
        smooth_sigma=None,
        grid_step=2.0,
        pad=0.2,
        boundary_linewidth=1.0,
        label_fontsize=6,
        zoom=7,
    ),
    "province": LevelParams(
        res=0.05,
        basemap=False,
        smooth_sigma=None,
        grid_step=1.0,
        pad=0.15,
        boundary_linewidth=0.8,
        label_fontsize=6,
        zoom=8,
    ),
    "city": LevelParams(
        res=0.03,
        basemap=True,
        smooth_sigma=1.5,
        grid_step=0.5,
        pad=0.15,
        boundary_linewidth=1.5,
        label_fontsize=7,
        zoom=10,
    ),
    "county": LevelParams(
        res=0.01,
        basemap=True,
        smooth_sigma=1.5,
        grid_step=0.2,
        pad=0.05,
        boundary_linewidth=1.5,
        label_fontsize=8,
        zoom=12,
    ),
}

# ---------------------------------------------------------------------------
# Preset key regions (province name lists)
# ---------------------------------------------------------------------------
DEFAULT_KEY_REGIONS: dict[str, list[str]] = {
    "YRD": ["上海市", "江苏省", "浙江省", "安徽省"],
    "长三角": ["上海市", "江苏省", "浙江省", "安徽省"],
    "BTH": ["北京市", "天津市", "河北省"],
    "京津冀": ["北京市", "天津市", "河北省"],
    "PRD": [
        "广州市",
        "深圳市",
        "珠海市",
        "东莞市",
        "中山市",
        "江门市",
        "惠州市",
        "肇庆市",
        "佛山市",
    ],
    "珠三角": [
        "广州市",
        "深圳市",
        "珠海市",
        "东莞市",
        "中山市",
        "江门市",
        "惠州市",
        "肇庆市",
        "佛山市",
    ],
    "SCB": ["四川省", "重庆市"],
    "成渝": ["四川省", "重庆市"],
}


# ---------------------------------------------------------------------------
# Global app config
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    """Merged configuration (file defaults + CLI overrides)."""

    # paths (per-product data directories)
    data_dirs: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_DATA_DIRS)
    )
    geojson_dir: str = DEFAULT_GEOJSON_DIR
    font_dir: str = DEFAULT_FONT_DIR
    tianditu_key: str = DEFAULT_TIANDITU_KEY

    # plotting defaults
    dpi: int = 300
    qa_threshold: float = 0.8

    # key regions
    key_regions: dict[str, list[str]] = field(
        default_factory=lambda: dict(DEFAULT_KEY_REGIONS)
    )

    @classmethod
    def load(cls) -> AppConfig:
        """Load config from TOML file, falling back to defaults."""
        cfg = cls()
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                data = tomllib.load(f)
            cfg._apply_toml(data)
        # Environment variable overrides (per-product: RSPLOT_DATA_DIR_NO2, etc.)
        for product in list(cfg.data_dirs):
            env_key = f"RSPLOT_DATA_DIR_{product.upper()}"
            if v := os.environ.get(env_key):
                cfg.data_dirs[product] = v
        if v := os.environ.get("RSPLOT_GEOJSON_DIR"):
            cfg.geojson_dir = v
        if v := os.environ.get("RSPLOT_TIANDITU_KEY"):
            cfg.tianditu_key = v
        return cfg

    def get_data_dir(self, product: str) -> str:
        """Return data directory for a product, or raise if not configured."""
        key = product.lower()
        if key in self.data_dirs:
            return self.data_dirs[key]
        available = ", ".join(self.data_dirs)
        raise ValueError(
            f"No data directory configured for product '{product}'. "
            f"Available: {available}"
        )

    def _apply_toml(self, data: dict[str, Any]) -> None:
        paths = data.get("paths", {})
        data_dirs = paths.get("data_dirs", {})
        for product, dir_path in data_dirs.items():
            self.data_dirs[product.lower()] = dir_path
        if v := paths.get("geojson_dir"):
            self.geojson_dir = v
        if v := paths.get("font_dir"):
            self.font_dir = v

        td = data.get("tianditu", {})
        if v := td.get("api_key"):
            self.tianditu_key = v

        defaults = data.get("defaults", {})
        if v := defaults.get("dpi"):
            self.dpi = int(v)
        if v := defaults.get("qa_threshold"):
            self.qa_threshold = float(v)

        kr = data.get("key_regions", {})
        for name, provinces in kr.items():
            self.key_regions[name] = provinces
