"""National ground monitoring station (国控站点) reader.

Reads hourly combined NC files from the configured GuoKong data directory.
File naming: {YYYYMMDDHH}.nc, e.g. 2026041415.nc.

Accepts both YYYYMMDDHH (exact hour) and YYYYMMDD (auto-picks latest hour).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


@dataclass
class StationData:
    """Filtered station observations for one variable."""

    id: np.ndarray  # 1-D string array
    lon: np.ndarray  # 1-D float
    lat: np.ndarray  # 1-D float
    values: np.ndarray  # 1-D float (NaN where invalid)
    var_name: str
    n_stations: int
    n_valid: int


@dataclass
class StationSeries:
    """Hourly observations for one station and one variable."""

    station_id: str
    lon: float
    lat: float
    timestamps: list[str]
    values: np.ndarray
    var_name: str
    source_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    failed_files: dict[str, str] = field(default_factory=dict)
    station_missing_hours: list[str] = field(default_factory=list)

    @property
    def n_hours(self) -> int:
        return len(self.timestamps)

    @property
    def n_valid(self) -> int:
        return int(np.isfinite(self.values).sum())


def read_stations(
    data_dir: str,
    datetime_str: str,
    var_name: str,
    extent: tuple[float, float, float, float] | None = None,
) -> tuple[StationData, str]:
    """Read station data for a given hour and variable.

    Parameters
    ----------
    data_dir : directory containing {YYYYMMDDHH}.nc files.
    datetime_str : YYYYMMDDHH (exact hour) or YYYYMMDD (latest hour).
    var_name : variable name in the NC file (e.g. "AQI", "PM2.5", "O3").
    extent : optional (lon_min, lon_max, lat_min, lat_max) for spatial filter.

    Returns
    -------
    tuple of (StationData, resolved_datetime_str).
    """
    if not datetime_str.isdigit() or len(datetime_str) not in (8, 10):
        raise ValueError(
            f"datetime 参数 '{datetime_str}' 格式不正确，"
            f"请使用 YYYYMMDD 或 YYYYMMDDHH，如 20260414 或 2026041415。"
        )

    # If 8-digit date, find the latest available hourly file for that day
    root = Path(data_dir)
    if len(datetime_str) == 8:
        relative_pattern = f"{datetime_str}??.nc"
        pattern = str(root / relative_pattern)
        path = next(
            (
                candidate
                for hour in range(23, -1, -1)
                if (
                    candidate := root / f"{datetime_str}{hour:02d}.nc"
                ).exists()
            ),
            None,
        )
        if path is None:
            raise FileNotFoundError(
                f"未找到 {datetime_str} 当天的站点数据文件: {pattern}\n"
                f"请检查日期和 --data-dir 路径。"
            )
        datetime_str = path.stem
    else:
        path = root / f"{datetime_str}.nc"

    try:
        ds = xr.open_dataset(path)
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"未找到站点数据文件: {path}\n"
            f"请检查 datetime 参数和 --data-dir 路径。"
        ) from e

    try:
        lon = ds["lon"].values.astype(float)
        lat = ds["lat"].values.astype(float)
        station_id = ds["id"].values

        # Read variable — xarray auto-applies scale_factor/add_offset for CO
        raw = ds[var_name].values.astype(float)
    finally:
        ds.close()

    # Fill values (65535 for ushort) → NaN
    raw[raw >= 65534] = np.nan

    # Spatial filter
    if extent is not None:
        lon_min, lon_max, lat_min, lat_max = extent
        mask = (
            (lon >= lon_min)
            & (lon <= lon_max)
            & (lat >= lat_min)
            & (lat <= lat_max)
        )
        lon = lon[mask]
        lat = lat[mask]
        raw = raw[mask]
        station_id = station_id[mask]

    n_valid = int(np.isfinite(raw).sum())

    return StationData(
        id=station_id,
        lon=lon,
        lat=lat,
        values=raw,
        var_name=var_name,
        n_stations=len(lon),
        n_valid=n_valid,
    ), datetime_str


def read_station_series(
    data_dir: str,
    station_id: str,
    dates: list[str],
    var_name: str,
) -> StationSeries:
    """Read a complete hourly series for one station over the given dates.

    Missing, unreadable, or station-less hours remain NaN so plotting retains
    visible gaps instead of connecting observations across missing data.
    """
    if not station_id.strip():
        raise ValueError("站点 ID 不能为空")
    if not dates:
        raise ValueError("日期窗口不能为空")

    root = Path(data_dir)
    timestamps = [f"{date}{hour:02d}" for date in dates for hour in range(24)]
    values = np.full(len(timestamps), np.nan, dtype=float)
    target = station_id.strip().upper()
    source_files: list[str] = []
    missing_files: list[str] = []
    failed_files: dict[str, str] = {}
    station_missing_hours: list[str] = []
    canonical_id: str | None = None
    station_lon: float | None = None
    station_lat: float | None = None
    opened_files = 0

    for index, timestamp in enumerate(timestamps):
        path = root / f"{timestamp}.nc"
        if not path.exists():
            missing_files.append(timestamp)
            continue

        try:
            with xr.open_dataset(path) as ds:
                opened_files += 1
                required = ("id", "lon", "lat", var_name)
                missing_vars = [name for name in required if name not in ds]
                if missing_vars:
                    raise KeyError(f"缺少变量: {', '.join(missing_vars)}")

                ids = _normalize_station_ids(ds["id"].values)
                matches = np.flatnonzero(
                    np.char.upper(ids.astype(str)) == target
                )
                if len(matches) == 0:
                    station_missing_hours.append(timestamp)
                    continue

                station_index = int(matches[0])
                canonical_id = str(ids[station_index])
                station_lon = float(
                    np.asarray(ds["lon"].values)[station_index]
                )
                station_lat = float(
                    np.asarray(ds["lat"].values)[station_index]
                )
                raw = float(
                    np.asarray(ds[var_name].values, dtype=float)[station_index]
                )
                if np.isfinite(raw) and raw < 65534:
                    values[index] = raw
                source_files.append(str(path))
        except (OSError, KeyError, ValueError, IndexError) as error:
            failed_files[timestamp] = str(error).splitlines()[0]

    if opened_files == 0:
        raise FileNotFoundError(
            f"窗口 {dates[0]}~{dates[-1]} 内未找到可读取的站点文件: "
            f"{root}/YYYYMMDDHH.nc"
        )
    if canonical_id is None or station_lon is None or station_lat is None:
        if failed_files and not station_missing_hours:
            examples = "; ".join(
                f"{timestamp}: {message}"
                for timestamp, message in list(failed_files.items())[:3]
            )
            raise ValueError(
                f"窗口 {dates[0]}~{dates[-1]} 内无法读取变量 "
                f"'{var_name}': {examples}"
            )
        raise ValueError(
            f"窗口 {dates[0]}~{dates[-1]} 内未找到站点 '{station_id}'"
        )

    return StationSeries(
        station_id=canonical_id,
        lon=station_lon,
        lat=station_lat,
        timestamps=timestamps,
        values=values,
        var_name=var_name,
        source_files=source_files,
        missing_files=missing_files,
        failed_files=failed_files,
        station_missing_hours=station_missing_hours,
    )


def mask_stations_to_region(
    data: StationData, geometry: BaseGeometry
) -> StationData:
    """Keep only stations inside the focus region geometry."""
    from shapely import contains_xy

    inside = contains_xy(geometry.buffer(1e-9), data.lon, data.lat)
    return _subset_stations(data, inside)


def _subset_stations(data: StationData, mask: np.ndarray) -> StationData:
    values = data.values[mask]
    return StationData(
        id=np.asarray(data.id)[mask],
        lon=data.lon[mask],
        lat=data.lat[mask],
        values=values,
        var_name=data.var_name,
        n_stations=int(mask.sum()),
        n_valid=int(np.isfinite(values).sum()),
    )


def _normalize_station_ids(values: np.ndarray) -> np.ndarray:
    """Return stripped text IDs for string, byte, and object arrays."""
    normalized = []
    for value in np.asarray(values).ravel():
        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace")
        else:
            text = str(value)
        normalized.append(text.strip())
    return np.asarray(normalized, dtype=str)
