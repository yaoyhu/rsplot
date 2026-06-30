"""ERA5 horizontal wind-field reader.

The local archive stores each day and component in a separate NetCDF file.
Station timestamps are converted to UTC before selecting the matching ERA5
hour, including the previous-day rollover for early local hours.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import xarray as xr

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


PRESSURE_LEVELS = {1000, 925, 850, 700, 500}
WIND_LEVELS = ("10m", "100m", "1000", "925", "850", "700", "500")


@dataclass
class WindFieldData:
    """A spatially subset ERA5 horizontal wind field."""

    lon: np.ndarray  # 2-D degrees east
    lat: np.ndarray  # 2-D degrees north
    u: np.ndarray  # 2-D eastward component
    v: np.ndarray  # 2-D northward component
    speed: np.ndarray  # 2-D magnitude
    level: str
    unit: str
    station_datetime: str
    datetime_utc: str
    source_files: tuple[str, str]
    n_cells: int
    n_valid: int


def read_era5_wind(
    data_dir: str,
    station_datetime: str,
    level: str,
    extent: tuple[float, float, float, float],
    *,
    station_timezone: str = "Asia/Shanghai",
) -> WindFieldData:
    """Read one ERA5 wind field matching a station observation hour."""
    normalized_level = _normalize_level(level)
    dt_utc = _to_utc(station_datetime, station_timezone)
    u_path, v_path, u_name, v_name = _component_paths(
        Path(data_dir), dt_utc, normalized_level
    )

    u_lon, u_lat, u, u_unit = _read_component(u_path, u_name, dt_utc, extent)
    v_lon, v_lat, v, v_unit = _read_component(v_path, v_name, dt_utc, extent)
    if u.shape != v.shape or not (
        np.allclose(u_lon, v_lon) and np.allclose(u_lat, v_lat)
    ):
        raise ValueError("ERA5 U/V 分量的经纬度网格不一致。")
    if u_unit != v_unit:
        raise ValueError(f"ERA5 U/V 分量单位不一致: {u_unit!r} / {v_unit!r}")

    valid = np.isfinite(u) & np.isfinite(v)
    u = np.where(valid, u, np.nan)
    v = np.where(valid, v, np.nan)
    speed = np.where(valid, np.hypot(u, v), np.nan)

    return WindFieldData(
        lon=u_lon,
        lat=u_lat,
        u=u,
        v=v,
        speed=speed,
        level=normalized_level,
        unit=_display_unit(u_unit),
        station_datetime=station_datetime,
        datetime_utc=dt_utc.strftime("%Y%m%d%H"),
        source_files=(str(u_path), str(v_path)),
        n_cells=int(speed.size),
        n_valid=int(valid.sum()),
    )


def mask_wind_to_region(
    data: WindFieldData, geometry: BaseGeometry
) -> WindFieldData:
    """Mask wind vectors to the same geometry used for station filtering."""
    from shapely import contains_xy

    inside = contains_xy(geometry.buffer(1e-9), data.lon, data.lat)
    valid = inside & np.isfinite(data.u) & np.isfinite(data.v)
    u = np.where(valid, data.u, np.nan)
    v = np.where(valid, data.v, np.nan)
    speed = np.where(valid, data.speed, np.nan)
    return replace(
        data,
        u=u,
        v=v,
        speed=speed,
        n_cells=int(inside.sum()),
        n_valid=int(valid.sum()),
    )


def _display_unit(unit: str) -> str:
    if unit in ("m s**-1", "m s-1"):
        return "m/s"
    return unit or "m/s"


def _normalize_level(level: str) -> str:
    value = level.strip().lower().removesuffix("hpa")
    if value in ("10", "10m"):
        return "10m"
    if value in ("100", "100m"):
        return "100m"
    if value.isdigit() and int(value) in PRESSURE_LEVELS:
        return value
    available = ", ".join(WIND_LEVELS)
    raise ValueError(f"不支持的风场层次 '{level}'。可用: {available}")


def _to_utc(station_datetime: str, station_timezone: str) -> datetime:
    if not station_datetime.isdigit() or len(station_datetime) != 10:
        raise ValueError(
            f"风场需要精确小时，收到 '{station_datetime}'，应为 YYYYMMDDHH。"
        )
    try:
        source_tz = ZoneInfo(station_timezone)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"未知时区 '{station_timezone}'。") from e
    try:
        local_dt = datetime.strptime(station_datetime, "%Y%m%d%H")
    except ValueError as e:
        raise ValueError(f"无效时次 '{station_datetime}'。") from e
    return local_dt.replace(tzinfo=source_tz).astimezone(timezone.utc)


def _component_paths(
    root: Path, dt_utc: datetime, level: str
) -> tuple[Path, Path, str, str]:
    day_root = root / dt_utc.strftime("%Y%m%d")
    if level in ("10m", "100m"):
        height = level.removesuffix("m")
        u_path = (
            day_root
            / "single_level"
            / f"{height}m_u_component_of_wind"
            / "surface.nc"
        )
        v_path = (
            day_root
            / "single_level"
            / f"{height}m_v_component_of_wind"
            / "surface.nc"
        )
        return u_path, v_path, f"u{height}", f"v{height}"

    u_path = (
        day_root / "pressure_level" / "u_component_of_wind" / f"{level}.nc"
    )
    v_path = (
        day_root / "pressure_level" / "v_component_of_wind" / f"{level}.nc"
    )
    return u_path, v_path, "u", "v"


def _read_component(
    path: Path,
    variable: str,
    dt_utc: datetime,
    extent: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    if not path.exists():
        raise FileNotFoundError(f"未找到 ERA5 风场文件: {path}")

    with xr.open_dataset(path) as ds:
        required = {"time", "latitude", "longitude", variable}
        missing = sorted(required - set(ds.variables))
        if missing:
            raise ValueError(
                f"ERA5 文件 {path} 缺少变量: {', '.join(missing)}"
            )

        target = np.datetime64(dt_utc.replace(tzinfo=None), "ns")
        times = np.asarray(ds["time"].values).astype("datetime64[ns]")
        time_indices = np.flatnonzero(times == target)
        if len(time_indices) == 0:
            target_label = dt_utc.strftime("%Y-%m-%d %H:%M UTC")
            raise ValueError(f"ERA5 文件 {path} 中没有时次 {target_label}。")

        lon_raw = np.asarray(ds["longitude"].values, dtype=float)
        lat_raw = np.asarray(ds["latitude"].values, dtype=float)
        lon_normalized = (lon_raw + 180.0) % 360.0 - 180.0
        lon_min, lon_max, lat_min, lat_max = extent
        if lon_min > lon_max:
            raise ValueError("暂不支持跨日期变更线的风场区域。")

        lon_indices = np.flatnonzero(
            (lon_normalized >= lon_min) & (lon_normalized <= lon_max)
        )
        lat_indices = np.flatnonzero(
            (lat_raw >= lat_min) & (lat_raw <= lat_max)
        )
        if len(lon_indices) == 0 or len(lat_indices) == 0:
            raise ValueError(f"ERA5 文件 {path} 在目标区域内没有网格点。")

        values = np.asarray(
            ds[variable]
            .isel(
                time=int(time_indices[0]),
                latitude=lat_indices,
                longitude=lon_indices,
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
    LON, LAT = np.meshgrid(lon_values[lon_order], lat_values[lat_order])
    return LON, LAT, values, unit
