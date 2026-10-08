"""Shared ERA5 scalar-grid reading and temperature support."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from rsplot.errors import RsplotError
from rsplot.readers.netcdf import open_netcdf
from rsplot.temporal import DEFAULT_INPUT_TIMEZONE, adapt_hourly_time

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


PRESSURE_LEVELS = ("1000", "925", "850", "700", "500")
TEMPERATURE_LEVELS = ("2m", *PRESSURE_LEVELS)
# CDS files written since the 2024 backend change use `valid_time`.
TIME_NAMES = ("valid_time", "time")


@dataclass(frozen=True)
class Era5FieldData:
    """One spatially subset and display-ready ERA5 scalar field."""

    lon: np.ndarray
    lat: np.ndarray
    values: np.ndarray
    variable: str
    level: str
    unit: str
    input_datetime: str
    input_timezone: str
    datetime_utc: str
    source_file: str
    n_cells: int
    n_valid: int


def read_era5_temperature(
    data_dir: str,
    input_datetime: str,
    level: str,
    extent: tuple[float, float, float, float],
    *,
    input_timezone: str = DEFAULT_INPUT_TIMEZONE,
) -> Era5FieldData:
    """Read 2 m or pressure-level temperature for a local CLI hour."""
    normalized_level = normalize_temperature_level(level)
    time_match = adapt_hourly_time(
        input_datetime,
        input_timezone=input_timezone,
        data_timezone="UTC",
        label="气象时次",
    )
    path, variable = _temperature_path(
        Path(data_dir),
        time_match.data_time,
        normalized_level,
    )
    lon, lat, values, source_unit = read_era5_grid(
        path,
        variable,
        time_match.data_time,
        extent,
        field_label="ERA5 温度",
    )
    if source_unit not in {"K", "kelvin", "Kelvin"}:
        raise ValueError(
            f"ERA5 温度单位应为 K，文件 {path} 实际为 {source_unit!r}。"
        )
    values = values - 273.15
    valid = np.isfinite(values)
    return Era5FieldData(
        lon=lon,
        lat=lat,
        values=np.where(valid, values, np.nan),
        variable="temperature",
        level=normalized_level,
        unit="°C",
        input_datetime=input_datetime,
        input_timezone=input_timezone,
        datetime_utc=time_match.data_datetime,
        source_file=str(path),
        n_cells=int(values.size),
        n_valid=int(valid.sum()),
    )


def mask_era5_field_to_region(
    data: Era5FieldData,
    geometry: BaseGeometry,
) -> Era5FieldData:
    """Mask a scalar ERA5 field to an exact administrative geometry."""
    from shapely import contains_xy

    inside = contains_xy(geometry.buffer(1e-9), data.lon, data.lat)
    valid = inside & np.isfinite(data.values)
    return replace(
        data,
        values=np.where(valid, data.values, np.nan),
        n_cells=int(inside.sum()),
        n_valid=int(valid.sum()),
    )


def normalize_temperature_level(level: str) -> str:
    """Normalize and validate a supported ERA5 temperature level."""
    value = level.strip().lower().removesuffix("hpa")
    if value in {"2", "2m"}:
        return "2m"
    if value in PRESSURE_LEVELS:
        return value
    available = ", ".join(TEMPERATURE_LEVELS)
    raise ValueError(f"不支持的温度层次 '{level}'。可用: {available}")


def read_era5_grid(
    path: Path,
    variable: str,
    data_datetime: datetime,
    extent: tuple[float, float, float, float],
    *,
    field_label: str = "ERA5 数据",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """Read one exact UTC hour from a standard ERA5 lat/lon grid."""
    if not path.exists():
        before, after = nearest_era5_hours(path, data_datetime)
        raise RsplotError(
            "data_not_found",
            f"未找到 {field_label}文件: {path}；{_nearest_label(before, after)}",
            details={
                "path": str(path),
                "nearest_before": before,
                "nearest_after": after,
                "search_hours": NEAREST_HOURS,
            },
        )

    with open_netcdf(path) as ds:
        time_name = next(
            (name for name in TIME_NAMES if name in ds.variables), None
        )
        required = {"latitude", "longitude", variable}
        missing = sorted(required - set(ds.variables))
        if time_name is None:
            missing.insert(0, " / ".join(TIME_NAMES))
        if missing:
            raise ValueError(
                f"{field_label}文件 {path} 缺少变量: {', '.join(missing)}"
            )

        target = np.datetime64(data_datetime.replace(tzinfo=None), "ns")
        times = np.asarray(ds[time_name].values).astype("datetime64[ns]")
        time_indices = np.flatnonzero(times == target)
        if len(time_indices) == 0:
            target_label = data_datetime.strftime("%Y-%m-%d %H:%M UTC")
            before, after = nearest_era5_hours(path, data_datetime)
            raise RsplotError(
                "data_not_found",
                f"{field_label}文件 {path} 中没有时次 {target_label}；"
                + _nearest_label(before, after),
                details={
                    "path": str(path),
                    "time_utc": target_label,
                    "nearest_before": before,
                    "nearest_after": after,
                    "search_hours": NEAREST_HOURS,
                },
            )

        lon_raw = np.asarray(ds["longitude"].values, dtype=float)
        lat_raw = np.asarray(ds["latitude"].values, dtype=float)
        lon_normalized = (lon_raw + 180.0) % 360.0 - 180.0
        lon_min, lon_max, lat_min, lat_max = extent
        if lon_min > lon_max:
            raise ValueError("暂不支持跨日期变更线的 ERA5 区域。")

        lon_indices = np.flatnonzero(
            (lon_normalized >= lon_min) & (lon_normalized <= lon_max)
        )
        lat_indices = np.flatnonzero(
            (lat_raw >= lat_min) & (lat_raw <= lat_max)
        )
        if len(lon_indices) == 0 or len(lat_indices) == 0:
            raise ValueError(
                f"{field_label}文件 {path} 在目标区域内没有网格点。"
            )

        values = np.asarray(
            ds[variable]
            .isel(
                {
                    time_name: int(time_indices[0]),
                    "latitude": lat_indices,
                    "longitude": lon_indices,
                }
            )
            .values,
            dtype=float,
        )
        unit = str(ds[variable].attrs.get("units", ""))

    lon_values = lon_normalized[lon_indices]
    lat_values = lat_raw[lat_indices]
    lon_order = np.argsort(lon_values)
    lat_order = np.argsort(lat_values)
    values = values[np.ix_(lat_order, lon_order)]
    lon, lat = np.meshgrid(
        lon_values[lon_order],
        lat_values[lat_order],
    )
    return lon, lat, values, unit


# How far either side of a missing hour to look for available ERA5 hours.
# ERA5 normally arrives about five days late, so a 48-hour window would
# find nothing for a recent request.
NEAREST_HOURS = 240


def nearest_era5_hours(
    path: Path, data_datetime: datetime
) -> tuple[str | None, str | None]:
    """Nearest available hours, as CLI ``YYYYMMDDHH``, around a missing one.

    ERA5 keeps one file per UTC day, so this probes the same layout day by
    day outward and reads the time axis of the nearest existing file in
    each direction only. Reports only; never selects.
    """
    from datetime import timedelta

    day = data_datetime.strftime("%Y%m%d")
    parts = path.parts
    if day not in parts:
        return None, None
    index = len(parts) - 1 - parts[::-1].index(day)
    target = np.datetime64(data_datetime.replace(tzinfo=None), "ns")
    window = np.timedelta64(NEAREST_HOURS, "h")

    def day_times(offset: int) -> np.ndarray | None:
        stamp = (data_datetime + timedelta(days=offset)).strftime("%Y%m%d")
        candidate = Path(*parts[:index], stamp, *parts[index + 1 :])
        if not candidate.exists():
            return None
        try:
            with open_netcdf(candidate) as ds:
                name = next((n for n in TIME_NAMES if n in ds.variables), None)
                if name is None:
                    return None
                times = np.asarray(ds[name].values).astype("datetime64[ns]")
        except RsplotError:
            return None
        return times[(times != target) & (abs(times - target) <= window)]

    def nearest(step: int) -> str | None:
        for distance in range(NEAREST_HOURS // 24 + 1):
            times = day_times(step * distance)
            if times is None:
                continue
            side = times[times < target] if step < 0 else times[times > target]
            if len(side):
                return _cli_hour(side.max() if step < 0 else side.min())
        return None

    return nearest(-1), nearest(1)


def _cli_hour(utc: np.datetime64) -> str:
    """Format a UTC archive time as the China-time CLI ``YYYYMMDDHH``."""
    from zoneinfo import ZoneInfo

    moment = utc.astype("datetime64[s]").item().replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(ZoneInfo(DEFAULT_INPUT_TIMEZONE)).strftime(
        "%Y%m%d%H"
    )


def _nearest_label(before: str | None, after: str | None) -> str:
    return (
        f"{NEAREST_HOURS // 24} 天内最近可用 DATETIME: 之前 {before or '无'}，"
        f"之后 {after or '无'}。"
    )


def _temperature_path(
    root: Path,
    dt_utc: datetime,
    level: str,
) -> tuple[Path, str]:
    day_root = root / dt_utc.strftime("%Y%m%d")
    if level == "2m":
        return (
            day_root / "single_level" / "2m_temperature" / "surface.nc",
            "t2m",
        )
    return day_root / "pressure_level" / "temperature" / f"{level}.nc", "t"
