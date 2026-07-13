"""Gridded air-quality forecast reader.

Forecast files are grouped by lead time:

``forecast{lead}/{YYYYMMDDHH}_forecast{lead}.nc``

The timestamp in the filename is treated as the model initialization time.
The valid time is computed as initialization time plus the forecast lead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

FORECAST_LEADS = (6, 12, 24, 48, 72)


@dataclass(frozen=True)
class ForecastVarInfo:
    """Display metadata for a forecast pollutant variable."""

    name: str
    label: str
    unit: str
    min_range: float

    @property
    def colorbar_label(self) -> str:
        return f"{self.label} forecast ({self.unit})"


@dataclass
class ForecastData:
    """Spatially subset forecast field on the native model grid."""

    lon: np.ndarray  # 2-D degrees east
    lat: np.ndarray  # 2-D degrees north
    values: np.ndarray  # 2-D, decoded display units
    variable: str
    label: str
    unit: str
    init_datetime: str
    valid_datetime: str
    lead_hour: int
    source_file: str
    n_cells: int
    n_valid: int


FORECAST_VAR_META: dict[str, ForecastVarInfo] = {
    "pm25": ForecastVarInfo("pm25", "PM2.5", "ug/m3", 20.0),
    "pm10": ForecastVarInfo("pm10", "PM10", "ug/m3", 30.0),
    "so2": ForecastVarInfo("so2", "SO2", "ug/m3", 10.0),
    "no2": ForecastVarInfo("no2", "NO2", "ug/m3", 10.0),
    "co": ForecastVarInfo("co", "CO", "mg/m3", 0.5),
    "o3": ForecastVarInfo("o3", "O3", "ug/m3", 20.0),
}

_FORECAST_VAR_ALIASES = {
    "pm2.5": "pm25",
    "pm2_5": "pm25",
    "pm_25": "pm25",
    "pm25": "pm25",
    "pm10": "pm10",
    "so2": "so2",
    "no2": "no2",
    "co": "co",
    "o3": "o3",
}


def normalize_forecast_var(value: str) -> str:
    """Return the NetCDF variable name for a user-facing pollutant name."""
    key = value.strip().lower()
    if key in _FORECAST_VAR_ALIASES:
        return _FORECAST_VAR_ALIASES[key]
    available = ", ".join(info.label for info in FORECAST_VAR_META.values())
    raise ValueError(f"未知预报变量 '{value}'。可用: {available}")


def get_forecast_var_info(value: str) -> ForecastVarInfo:
    """Return display metadata for a forecast pollutant."""
    return FORECAST_VAR_META[normalize_forecast_var(value)]


def read_forecast(
    data_dir: str,
    datetime_str: str,
    lead: int | str,
    variable: str,
    extent: tuple[float, float, float, float],
) -> tuple[ForecastData, str]:
    """Read one gridded forecast field.

    ``datetime_str`` accepts either ``YYYYMMDDHH`` for an exact model
    initialization hour or ``YYYYMMDD`` to auto-pick the latest file for that
    date and lead.
    """
    lead_hour = _normalize_lead(lead)
    var_name = normalize_forecast_var(variable)
    var_info = FORECAST_VAR_META[var_name]
    path, resolved_init = _resolve_forecast_path(
        Path(data_dir), datetime_str, lead_hour
    )

    if path.stat().st_size == 0:
        raise ValueError(f"预报文件为空: {path}")

    LON, LAT, values = _read_forecast_grid(path, var_name, extent)
    init_dt = datetime.strptime(resolved_init, "%Y%m%d%H")
    valid_dt = init_dt + timedelta(hours=lead_hour)
    valid = np.isfinite(values)

    return (
        ForecastData(
            lon=LON,
            lat=LAT,
            values=np.where(valid, values, np.nan),
            variable=var_name,
            label=var_info.label,
            unit=var_info.unit,
            init_datetime=resolved_init,
            valid_datetime=valid_dt.strftime("%Y%m%d%H"),
            lead_hour=lead_hour,
            source_file=str(path),
            n_cells=int(values.size),
            n_valid=int(valid.sum()),
        ),
        resolved_init,
    )


def auto_forecast_vrange(
    grid: np.ndarray, var_info: ForecastVarInfo
) -> tuple[float, float]:
    """Compute a readable color range from finite forecast pixels."""
    finite = grid[np.isfinite(grid)]
    if len(finite) == 0:
        raise ValueError("预报网格没有有效值，无法自动确定色标范围。")

    p2 = float(np.nanpercentile(finite, 2))
    p98 = float(np.nanpercentile(finite, 98))
    span = p98 - p2
    if span < var_info.min_range:
        center = (p2 + p98) / 2
        p2 = center - var_info.min_range / 2
        p98 = center + var_info.min_range / 2
        span = var_info.min_range

    if span < 1:
        step = 0.1
    elif span < 5:
        step = 0.5
    elif span < 10:
        step = 1.0
    elif span < 50:
        step = 5.0
    elif span < 100:
        step = 10.0
    else:
        step = 20.0

    vmin = max(0.0, np.floor(p2 / step) * step)
    vmax = np.ceil(p98 / step) * step
    return float(vmin), float(vmax)


def _normalize_lead(value: int | str) -> int:
    lead = int(str(value).strip().removeprefix("forecast"))
    if lead not in FORECAST_LEADS:
        available = ", ".join(str(v) for v in FORECAST_LEADS)
        raise ValueError(f"不支持的预报时效 '{value}'。可用: {available}")
    return lead


def _resolve_forecast_path(
    root: Path, datetime_str: str, lead_hour: int
) -> tuple[Path, str]:
    if not datetime_str.isdigit() or len(datetime_str) not in (8, 10):
        raise ValueError(
            f"datetime 参数 '{datetime_str}' 格式不正确，"
            "请使用 YYYYMMDD 或 YYYYMMDDHH。"
        )

    lead_dir = root / f"forecast{lead_hour}"
    if len(datetime_str) == 8:
        relative_pattern = f"{datetime_str}??_forecast{lead_hour}.nc"
        pattern = str(lead_dir / relative_pattern)
        matches = [
            path
            for path in sorted(lead_dir.glob(relative_pattern))
            if path.stat().st_size > 0
        ]
        if not matches:
            raise FileNotFoundError(
                f"未找到 {datetime_str} 当天 forecast{lead_hour} 预报文件: "
                f"{pattern}"
            )
        path = matches[-1]
        resolved = path.name.split("_", 1)[0]
        return path, resolved

    path = lead_dir / f"{datetime_str}_forecast{lead_hour}.nc"
    if not path.exists():
        raise FileNotFoundError(
            f"未找到预报文件: {path}\n请检查 datetime、--lead 和 --data-dir。"
        )
    return path, datetime_str


def _read_forecast_grid(
    path: Path,
    variable: str,
    extent: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    try:
        ds = xr.open_dataset(path)
    except OSError as e:
        raise ValueError(f"无法打开预报文件 {path}: {e}") from e

    try:
        required = {"lat", "lon", variable}
        missing = sorted(required - set(ds.variables))
        if missing:
            raise ValueError(f"预报文件 {path} 缺少变量: {', '.join(missing)}")

        lon_raw = np.asarray(ds["lon"].values, dtype=float)
        lat_raw = np.asarray(ds["lat"].values, dtype=float)
        lon_min, lon_max, lat_min, lat_max = extent
        if lon_min > lon_max:
            raise ValueError("暂不支持跨日期变更线的预报区域。")

        lon_idx = np.flatnonzero((lon_raw >= lon_min) & (lon_raw <= lon_max))
        lat_idx = np.flatnonzero((lat_raw >= lat_min) & (lat_raw <= lat_max))
        if len(lon_idx) == 0 or len(lat_idx) == 0:
            raise ValueError(f"预报文件 {path} 在目标区域内没有网格点。")

        values = np.asarray(
            ds[variable].isel(lat=lat_idx, lon=lon_idx).values,
            dtype=float,
        )
    finally:
        ds.close()

    lon_values = lon_raw[lon_idx]
    lat_values = lat_raw[lat_idx]
    lon_order = np.argsort(lon_values)
    lat_order = np.argsort(lat_values)
    values = values[np.ix_(lat_order, lon_order)]
    LON, LAT = np.meshgrid(lon_values[lon_order], lat_values[lat_order])
    return LON, LAT, values
