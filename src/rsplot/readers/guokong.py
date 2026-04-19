"""National ground monitoring station (国控站点) reader.

Reads hourly combined NC files from /home/zzgsg/data/guokong_combine/.
File naming: {YYYYMMDDHH}.nc, e.g. 2026041415.nc.

Accepts both YYYYMMDDHH (exact hour) and YYYYMMDD (auto-picks latest hour).
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

import numpy as np
import xarray as xr


@dataclass
class StationData:
    """Filtered station observations for one variable."""

    id: np.ndarray       # 1-D string array
    lon: np.ndarray      # 1-D float
    lat: np.ndarray      # 1-D float
    values: np.ndarray   # 1-D float (NaN where invalid)
    var_name: str
    n_stations: int
    n_valid: int


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
    if len(datetime_str) == 8:
        pattern = os.path.join(data_dir, f"{datetime_str}??.nc")
        matches = sorted(glob.glob(pattern))
        if not matches:
            raise FileNotFoundError(
                f"未找到 {datetime_str} 当天的站点数据文件: {pattern}\n"
                f"请检查日期和 --data-dir 路径。"
            )
        path = matches[-1]  # latest hour
        datetime_str = os.path.basename(path).removesuffix(".nc")
    else:
        path = os.path.join(data_dir, f"{datetime_str}.nc")

    try:
        ds = xr.open_dataset(path)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"未找到站点数据文件: {path}\n"
            f"请检查 datetime 参数和 --data-dir 路径。"
        )

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
