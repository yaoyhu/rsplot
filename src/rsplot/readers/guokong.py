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

from rsplot.errors import RsplotError
from rsplot.readers.netcdf import open_netcdf

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


@dataclass
class RegionStationSeries:
    """Hourly observations for every station inside one region."""

    station_ids: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    timestamps: list[str]
    values: np.ndarray  # shape: (n_stations, n_hours)
    var_name: str
    source_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    failed_files: dict[str, str] = field(default_factory=dict)

    @property
    def n_stations(self) -> int:
        return len(self.station_ids)

    @property
    def n_hours(self) -> int:
        return len(self.timestamps)

    @property
    def n_valid(self) -> int:
        return int(np.isfinite(self.values).sum())

    @property
    def hourly_valid_counts(self) -> np.ndarray:
        return np.isfinite(self.values).sum(axis=0).astype(np.int32)

    @property
    def hourly_mean(self) -> np.ndarray:
        counts = self.hourly_valid_counts
        totals = np.nansum(self.values, axis=0)
        mean = np.full(self.n_hours, np.nan, dtype=float)
        np.divide(totals, counts, out=mean, where=counts > 0)
        return mean

    def station_index(self, station_id: str) -> int | None:
        """Return a case-insensitive station index when present."""
        target = station_id.strip().upper()
        normalized = np.char.upper(self.station_ids.astype(str))
        matches = np.flatnonzero(normalized == target)
        return int(matches[0]) if len(matches) else None


def resolve_station_file(data_dir: str, datetime_str: str) -> Path:
    """Resolve an exact local hour or the latest file on a local date."""
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
            raise RsplotError(
                "data_not_found",
                f"未找到 {datetime_str} 当天的站点数据文件: {pattern}\n"
                "请检查日期和配置 [paths.data_dirs].guokong 路径。",
                details={"path": pattern},
            )
        datetime_str = path.stem
    else:
        path = root / f"{datetime_str}.nc"
        if not path.exists():
            raise RsplotError(
                "data_not_found",
                f"未找到站点数据文件: {path}\n"
                "请检查日期时间和配置 [paths.data_dirs].guokong 路径。",
                details={"path": str(path)},
            )

    return path


@dataclass(frozen=True)
class StationLocations:
    """Station coordinates from one hourly snapshot, without observations."""

    id: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    source_file: str
    datetime: str


def read_station_locations(
    data_dir: str,
    datetime_str: str,
) -> StationLocations:
    """Read locations even when pollutant variables are absent or missing."""
    path = resolve_station_file(data_dir, datetime_str)
    with open_netcdf(path) as ds:
        for name in ("id", "lon", "lat"):
            if name not in ds:
                raise ValueError(f"站点文件缺少 {name}: {path}")
        ids = np.char.upper(_normalize_station_ids(ds["id"].values))
        lon = ds["lon"].values.astype(float).ravel()
        lat = ds["lat"].values.astype(float).ravel()
    if not (len(ids) == len(lon) == len(lat)):
        raise ValueError(f"站点 ID 与坐标数量不一致: {path}")
    return StationLocations(ids, lon, lat, str(path), path.stem)


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
    path = resolve_station_file(data_dir, datetime_str)
    datetime_str = path.stem

    ds = open_netcdf(path)

    try:
        lon = ds["lon"].values.astype(float)
        lat = ds["lat"].values.astype(float)
        station_id = ds["id"].values

        # Read variable — xarray auto-applies scale_factor/add_offset for CO
        if var_name not in ds:
            raise ValueError(f"站点文件缺少变量 {var_name}: {path}")
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
            with open_netcdf(path) as ds:
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
        raise RsplotError(
            "data_not_found",
            f"窗口 {dates[0]}~{dates[-1]} 内未找到可读取的站点文件: "
            f"{root}/YYYYMMDDHH.nc",
            details={"path": f"{root}/YYYYMMDDHH.nc"},
        )
    if canonical_id is None or station_lon is None or station_lat is None:
        if failed_files and not station_missing_hours:
            examples = "; ".join(
                f"{timestamp}: {message}"
                for timestamp, message in list(failed_files.items())[:3]
            )
            raise RsplotError(
                "read_failed",
                f"窗口 {dates[0]}~{dates[-1]} 内无法读取变量 "
                f"'{var_name}': {examples}",
            )
        raise RsplotError(
            "region_not_found",
            f"窗口 {dates[0]}~{dates[-1]} 内未找到站点 '{station_id}'",
            details={"station_id": station_id},
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


def read_region_station_series(
    data_dir: str,
    dates: list[str],
    var_name: str,
    geometry: BaseGeometry,
) -> RegionStationSeries:
    """Read an aligned station-by-hour matrix inside ``geometry``.

    Each hourly file is opened at most once, regardless of the number of
    stations in the selected region. Stations appearing or disappearing
    during the window are aligned by their normalized station ID.
    """
    if not dates:
        raise ValueError("日期窗口不能为空")

    from shapely import contains_xy

    root = Path(data_dir)
    timestamps = [f"{date}{hour:02d}" for date in dates for hour in range(24)]
    hourly_values: list[dict[str, float]] = []
    station_meta: dict[str, tuple[float, float]] = {}
    source_files: list[str] = []
    missing_files: list[str] = []
    failed_files: dict[str, str] = {}
    existing_files = 0
    region_geometry = geometry.buffer(1e-9)

    for timestamp in timestamps:
        path = root / f"{timestamp}.nc"
        if not path.exists():
            missing_files.append(timestamp)
            hourly_values.append({})
            continue

        existing_files += 1
        try:
            with open_netcdf(path) as ds:
                required = ("id", "lon", "lat", var_name)
                missing_vars = [name for name in required if name not in ds]
                if missing_vars:
                    raise KeyError(f"缺少变量: {', '.join(missing_vars)}")

                ids = _normalize_station_ids(ds["id"].values)
                lon = np.asarray(ds["lon"].values, dtype=float).ravel()
                lat = np.asarray(ds["lat"].values, dtype=float).ravel()
                raw = (
                    np.asarray(ds[var_name].values)
                    .astype(
                        float,
                        copy=True,
                    )
                    .ravel()
                )
                if not (len(ids) == len(lon) == len(lat) == len(raw)):
                    raise ValueError("站点 ID、经纬度和变量数组长度不一致")

                raw[raw >= 65534] = np.nan
                inside = contains_xy(region_geometry, lon, lat)
                row: dict[str, float] = {}
                for index in np.flatnonzero(inside):
                    station_id = str(ids[index])
                    key = station_id.upper()
                    if key in row:
                        continue
                    row[key] = float(raw[index])
                    station_meta.setdefault(
                        key,
                        (float(lon[index]), float(lat[index])),
                    )
                hourly_values.append(row)
                source_files.append(str(path))
        except (OSError, KeyError, ValueError, IndexError) as error:
            failed_files[timestamp] = str(error).splitlines()[0]
            hourly_values.append({})

    if existing_files == 0:
        raise RsplotError(
            "data_not_found",
            f"窗口 {dates[0]}~{dates[-1]} 内未找到可读取的站点文件: "
            f"{root}/YYYYMMDDHH.nc",
            details={"path": f"{root}/YYYYMMDDHH.nc"},
        )
    if not source_files:
        examples = "; ".join(
            f"{timestamp}: {message}"
            for timestamp, message in list(failed_files.items())[:3]
        )
        raise ValueError(
            f"窗口 {dates[0]}~{dates[-1]} 内无法读取变量 "
            f"'{var_name}': {examples}"
        )
    if not station_meta:
        raise ValueError(f"窗口 {dates[0]}~{dates[-1]} 内目标区域没有国控站点")

    station_ids = np.asarray(sorted(station_meta), dtype=str)
    station_lookup = {
        station_id: index for index, station_id in enumerate(station_ids)
    }
    values = np.full((len(station_ids), len(timestamps)), np.nan, dtype=float)
    for hour_index, row in enumerate(hourly_values):
        for station_id, value in row.items():
            values[station_lookup[station_id], hour_index] = value

    lon = np.asarray([station_meta[key][0] for key in station_ids])
    lat = np.asarray([station_meta[key][1] for key in station_ids])
    return RegionStationSeries(
        station_ids=station_ids,
        lon=lon,
        lat=lat,
        timestamps=timestamps,
        values=values,
        var_name=var_name,
        source_files=source_files,
        missing_files=missing_files,
        failed_files=failed_files,
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
