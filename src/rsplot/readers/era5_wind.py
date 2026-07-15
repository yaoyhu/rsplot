"""ERA5 horizontal wind-field reader.

The local archive stores each day and component in a separate NetCDF file.
Station timestamps are converted to UTC before selecting the matching ERA5
hour, including the previous-day rollover for early local hours.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from rsplot.readers.era5 import PRESSURE_LEVELS as ERA5_PRESSURE_LEVELS
from rsplot.readers.era5 import read_era5_grid
from rsplot.temporal import DEFAULT_INPUT_TIMEZONE, adapt_hourly_time

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


PRESSURE_LEVELS = {int(level) for level in ERA5_PRESSURE_LEVELS}
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
    input_timezone: str = DEFAULT_INPUT_TIMEZONE


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
        input_timezone=station_timezone,
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
    return adapt_hourly_time(
        station_datetime,
        input_timezone=station_timezone,
        data_timezone="UTC",
        label="风场时次",
    ).data_time


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
    return read_era5_grid(
        path,
        variable,
        dt_utc,
        extent,
        field_label="ERA5 风场",
    )
