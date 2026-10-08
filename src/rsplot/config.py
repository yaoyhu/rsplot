"""Configuration management for rsplot.

Runtime paths are intentionally configured outside the package. The loader
merges safe built-in defaults, TOML config files, environment variables, and
finally CLI overrides handled by command functions.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rsplot.errors import RsplotError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


# ---------------------------------------------------------------------------
# Safe built-in path defaults
# ---------------------------------------------------------------------------
KNOWN_DATA_PRODUCTS = (
    "tropomi_nrti_no2",
    "tropomi_nrti_hcho",
    "tropomi_nrti_o3",
    "tropomi_nrti_o3pr",
    "gems_no2",
    "gems_hcho",
    "gems_o3",
    "no2",
    "o3",
    "o3pr",
    "hcho",
    "guokong",
    "era5",
    "forecast",
    "reconstruct",
)

DEFAULT_DATA_DIRS: dict[str, str] = {}
DEFAULT_GEOJSON_DIR = None
DEFAULT_FONT_DIR = None
DEFAULT_TIANDITU_KEY = None


CONFIG_PATH = Path.home() / ".config" / "rsplot" / "config.toml"
CONFIG_ENV_VAR = "RSPLOT_CONFIG"


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


@dataclass(frozen=True)
class SubdivisionSource:
    """External boundary source replacing a city's county-level layer."""

    path: str
    name_field: str = "name"
    level: str = "township"


LEVEL_DEFAULTS: dict[str, LevelParams] = {
    "country": LevelParams(
        res=0.1,
        basemap=False,
        smooth_sigma=None,
        grid_step=5.0,
        pad=0.5,
        boundary_linewidth=0.5,
        label_fontsize=6,
        zoom=5,
    ),
    "key_region": LevelParams(
        res=0.05,
        basemap=False,
        smooth_sigma=None,
        grid_step=2.0,
        pad=0.2,
        boundary_linewidth=1.0,
        label_fontsize=7,
        zoom=7,
    ),
    "province": LevelParams(
        res=0.05,
        basemap=False,
        smooth_sigma=None,
        grid_step=1.0,
        pad=0.15,
        boundary_linewidth=0.8,
        label_fontsize=7,
        zoom=8,
    ),
    "city": LevelParams(
        res=0.03,
        basemap=True,
        smooth_sigma=1.5,
        grid_step=0.5,
        pad=0.15,
        boundary_linewidth=1.5,
        label_fontsize=8,
        zoom=10,
    ),
    "county": LevelParams(
        res=0.01,
        basemap=True,
        smooth_sigma=1.5,
        grid_step=0.2,
        pad=0.05,
        boundary_linewidth=1.5,
        label_fontsize=9,
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
    """Merged configuration from files and environment variables."""

    # paths (per-product data directories)
    data_dirs: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_DATA_DIRS)
    )
    geojson_dir: str | None = DEFAULT_GEOJSON_DIR
    font_dir: str | None = DEFAULT_FONT_DIR
    tianditu_key: str | None = DEFAULT_TIANDITU_KEY
    config_files: list[str] = field(default_factory=list)
    subdivision_overrides: dict[str, SubdivisionSource] = field(
        default_factory=dict
    )

    # plotting defaults
    dpi: int = 300
    qa_threshold: float = 0.5

    # key regions
    key_regions: dict[str, list[str]] = field(
        default_factory=lambda: dict(DEFAULT_KEY_REGIONS)
    )

    @classmethod
    def load(cls) -> AppConfig:
        """Load config from TOML files and environment variables.

        Merge order:
        1. safe built-in defaults
        2. ~/.config/rsplot/config.toml, if present
        3. RSPLOT_CONFIG, if set
        4. environment variable path/API-key overrides
        """
        cfg = cls()
        for path in _config_paths():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            cfg._apply_toml(data)
            cfg.config_files.append(str(path))

        cfg._apply_env()
        return cfg

    def _apply_env(self) -> None:
        """Apply environment variable overrides."""
        products = set(KNOWN_DATA_PRODUCTS) | set(self.data_dirs)
        for product in sorted(products):
            env_key = f"RSPLOT_DATA_DIR_{product.upper()}"
            if v := os.environ.get(env_key):
                self.data_dirs[product] = _normalize_path(v)
        if v := os.environ.get("RSPLOT_GEOJSON_DIR"):
            self.geojson_dir = _normalize_path(v)
        if v := os.environ.get("RSPLOT_FONT_DIR"):
            self.font_dir = _normalize_path(v)
        if v := os.environ.get("TIANDITU_API_KEY"):
            self.tianditu_key = v

    def get_data_dir(self, product: str) -> str:
        """Return data directory for a product, or raise if not configured."""
        key = product.lower()
        dir_path = self.data_dirs.get(key)
        if dir_path:
            return dir_path

        configured = (
            ", ".join(sorted(k for k, v in self.data_dirs.items() if v))
            or "none"
        )
        raise RsplotError(
            "data_not_configured",
            f"No data directory configured for product '{product}'. "
            f"Set [paths.data_dirs].{key} in {CONFIG_PATH}, set "
            f"RSPLOT_DATA_DIR_{key.upper()}, or point {CONFIG_ENV_VAR} to a "
            "TOML config file. "
            f"Known products: {', '.join(KNOWN_DATA_PRODUCTS)}. "
            f"Configured products: {configured}.",
            details={"config_key": key},
        )

    def require_geojson_dir(self) -> str:
        """Return the boundary GeoJSON directory, or raise with guidance."""
        if self.geojson_dir:
            return self.geojson_dir
        raise RsplotError(
            "data_not_configured",
            "GeoJSON boundary directory is not configured. Set "
            f"[paths].geojson_dir in {CONFIG_PATH}, set RSPLOT_GEOJSON_DIR, "
            f"or point {CONFIG_ENV_VAR} to a TOML config file.",
            details={"config_key": "geojson_dir"},
        )

    def _apply_toml(self, data: dict[str, Any]) -> None:
        paths = data.get("paths", {})
        data_dirs = paths.get("data_dirs", {})
        for product, dir_path in data_dirs.items():
            if dir_path:
                self.data_dirs[product.lower()] = _normalize_path(dir_path)
        if v := paths.get("geojson_dir"):
            self.geojson_dir = _normalize_path(v)
        if v := paths.get("font_dir"):
            self.font_dir = _normalize_path(v)

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

        overrides = data.get("subdivision_overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError("[subdivision_overrides] 必须是 TOML 表。")
        for parent, raw_source in overrides.items():
            if isinstance(raw_source, str):
                source = SubdivisionSource(path=_normalize_path(raw_source))
            elif isinstance(raw_source, dict):
                path = raw_source.get("path")
                if not path:
                    raise ValueError(
                        f"subdivision_overrides.{parent} 缺少 path。"
                    )
                name_field = str(raw_source.get("name_field", "name")).strip()
                level = str(raw_source.get("level", "township")).strip()
                if not name_field:
                    raise ValueError(
                        f"subdivision_overrides.{parent}.name_field 不能为空。"
                    )
                if not level:
                    raise ValueError(
                        f"subdivision_overrides.{parent}.level 不能为空。"
                    )
                source = SubdivisionSource(
                    path=_normalize_path(path),
                    name_field=name_field,
                    level=level,
                )
            else:
                raise ValueError(
                    f"subdivision_overrides.{parent} 必须是路径或 TOML 表。"
                )
            self.subdivision_overrides[str(parent)] = source


def _config_paths() -> list[Path]:
    """Return config files to load in priority order."""
    paths: list[Path] = []
    if CONFIG_PATH.exists():
        paths.append(CONFIG_PATH)

    if raw := os.environ.get(CONFIG_ENV_VAR):
        path = Path(_normalize_path(raw))
        if not path.exists():
            raise RsplotError(
                "config_invalid",
                f"{CONFIG_ENV_VAR} points to a missing config file: {path}",
                details={"path": str(path)},
            )
        try:
            already_loaded = path.resolve() in {p.resolve() for p in paths}
        except OSError:
            already_loaded = path in paths
        if not already_loaded:
            paths.append(path)

    return paths


def _normalize_path(value: Any) -> str:
    """Expand ~ and environment variables in configured path values."""
    return os.path.expanduser(os.path.expandvars(str(value)))


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
    (50, "#00e400"),  # 优 / green
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

STATION_VAR_LABELS: dict[str, str] = {
    "O3_8h": "8h O3",
    "O3_8h_24h": "MDA8 O3",
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


@dataclass(frozen=True)
class StationColorScale:
    """Fixed concentration scale for O3 and NO2 station map layers."""

    threshold: float
    vmax: float
    vmin: float = 0.0
    cmap: str = "rsplot_station_threshold"
    exceedance_color: str = "#ff0000"


def get_station_color_scale(var_name: str) -> StationColorScale | None:
    """Use existing time-specific limits with 20 ug/m3 of red headroom."""
    meta = STATION_VAR_META.get(var_name)
    if meta is None or meta[1] not in ("O3", "NO2"):
        return None
    threshold = get_exceedance_threshold(var_name)
    if threshold is None:
        return None
    return StationColorScale(threshold=threshold, vmax=threshold + 20.0)
