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
    "guokong": "/home/zzgsg/data/guokong_combine",
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
    "country": LevelParams(
        res=0.1,
        basemap=False,
        smooth_sigma=None,
        grid_step=5.0,
        pad=0.5,
        boundary_linewidth=0.5,
        label_fontsize=5,
        zoom=5,
    ),
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
    # 长三角（31）
    "YRD": ["上海市", "江苏省", "浙江省", "安徽省"],
    "长三角": ["上海市", "江苏省", "浙江省", "安徽省"],

    # 京津冀及周边（38）
    "BTH": ["北京市", "天津市", "河北省", "山东省", "河南省"],
    "京津冀": ["北京市", "天津市", "河北省", "山东省", "河南省"],
    "京津冀及周边": ["北京市", "天津市", "河北省", "山东省", "河南省"],

    # 汾渭平原（13）
    "FWP": ["山西省", "陕西省"],
    "汾渭平原": ["山西省", "陕西省"],

    # 成渝地区（16）
    "SCB": ["重庆市", "四川省"],
    "成渝": ["重庆市", "四川省"],
    "成渝地区": ["重庆市", "四川省"],

    # 长江中游城市群（21）
    "MYR": ["湖北省", "江西省", "湖南省"],
    "长江中游": ["湖北省", "江西省", "湖南省"],
    "长江中游城市群": ["湖北省", "江西省", "湖南省"],

    # 珠三角（9）
    "PRD": [
        "广州市",
        "深圳市",
        "珠海市",
        "佛山市",
        "江门市",
        "肇庆市",
        "惠州市",
        "东莞市",
        "中山市",
    ],
    "珠三角": [
        "广州市",
        "深圳市",
        "珠海市",
        "佛山市",
        "江门市",
        "肇庆市",
        "惠州市",
        "东莞市",
        "中山市",
    ],
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
    tianditu_key: str | None = DEFAULT_TIANDITU_KEY

    # plotting defaults
    dpi: int = 300
    qa_threshold: float = 0.5

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


# ---------------------------------------------------------------------------
# GB 3095-2026 Air Quality Limits (transitional phase, grade II)
# ---------------------------------------------------------------------------
AQ_LIMITS_2026: dict[str, dict[str, float]] = {
    "SO2": {"annual": 60, "daily": 150, "hourly": 500},
    "NO2": {"annual": 40, "daily": 80, "hourly": 200},
    "CO": {"daily": 4, "hourly": 10},
    "O3": {"8h": 160, "hourly": 200},
    "PM10": {"annual": 60, "daily": 120},
    "PM2_5": {"annual": 30, "daily": 60},
    "TSP": {"annual": 200, "daily": 300},
    "NOx": {"annual": 40, "daily": 70, "hourly": 250},
    "Pb": {"annual": 0.5, "seasonal": 1.0},
    "BaP": {"annual": 0.001, "daily": 0.0025},
}

# ---------------------------------------------------------------------------
# AQI Classification (official standard)
# ---------------------------------------------------------------------------
AQI_COLORS: list[tuple[int, str]] = [
    # (upper bound, hex color)
    (50, "#00e400"),   # 优 / green
    (100, "#ffff00"),  # 良 / yellow
    (150, "#ff7e00"),  # 轻度污染 / orange
    (200, "#ff0000"),  # 中度污染 / red
    (300, "#99004c"),  # 重度污染 / purple
    (500, "#7e0023"),  # 严重污染 / maroon
]

AQI_EXCEEDANCE_THRESHOLD = 100  # AQI > 100 considered exceeding

# ---------------------------------------------------------------------------
# Station variable metadata: nc_name -> (unit, limit_key, limit_time)
# limit_key maps into AQ_LIMITS_2026; limit_time selects which sub-key.
# None means no standard exceedance check for this variable.
# ---------------------------------------------------------------------------
STATION_VAR_META: dict[str, tuple[str, str | None, str | None]] = {
    "AQI": ("", None, None),
    "PM2.5": ("ug/m3", None, None),
    "PM2.5_24h": ("ug/m3", "PM2_5", "daily"),
    "PM10": ("ug/m3", None, None),
    "PM10_24h": ("ug/m3", "PM10", "daily"),
    "SO2": ("ug/m3", "SO2", "hourly"),
    "SO2_24h": ("ug/m3", "SO2", "daily"),
    "NO2": ("ug/m3", "NO2", "hourly"),
    "NO2_24h": ("ug/m3", "NO2", "daily"),
    "O3": ("ug/m3", "O3", "hourly"),
    "O3_24h": ("ug/m3", "O3", "hourly"),
    "O3_8h": ("ug/m3", "O3", "8h"),
    "O3_8h_24h": ("ug/m3", "O3", "8h"),
    "CO": ("mg/m3", "CO", "hourly"),
    "CO_24h": ("mg/m3", "CO", "daily"),
}


def get_exceedance_threshold(var_name: str) -> float | None:
    """Return the exceedance threshold for a station variable, or None."""
    if var_name == "AQI":
        return AQI_EXCEEDANCE_THRESHOLD
    meta = STATION_VAR_META.get(var_name)
    if meta is None:
        return None
    _, limit_key, limit_time = meta
    if limit_key is None or limit_time is None:
        return None
    limits = AQ_LIMITS_2026.get(limit_key)
    if limits is None:
        return None
    return limits.get(limit_time)
