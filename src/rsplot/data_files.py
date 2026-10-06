"""Data files written next to images for agents' further analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rsplot.result_builders.envelope import SCHEMA


def data_path(output: str, layer: str, suffix: str) -> Path:
    """Return ``<base>.<layer><suffix>`` next to the image."""
    image = Path(output)
    return image.with_name(f"{image.stem}.{layer}{suffix}")


def write_grid_netcdf(
    path: Path,
    lon: np.ndarray,
    lat: np.ndarray,
    values: np.ndarray,
    counted: np.ndarray,
    *,
    extent: tuple[float, float, float, float],
    layer: str,
    attrs: dict[str, Any],
    valid_days: np.ndarray | None = None,
    extra: dict[str, np.ndarray] | None = None,
    content: str = "statistical_grid",
) -> dict[str, Any]:
    """Write a statistical grid cropped to the region extent.

    ``extra`` adds same-shaped float variables, e.g. ``u``/``v`` for wind.

    ``lon``/``lat`` are regular 2-D cell-centre grids. ``values`` is the
    exact grid statistics were computed from (NaN = invalid) and
    ``counted`` marks cells whose centres count toward statistics.
    """
    from netCDF4 import Dataset

    lons = np.asarray(lon)[0, :]
    lats = np.asarray(lat)[:, 0]
    half_x = abs(float(lons[1] - lons[0])) / 2 if lons.size > 1 else 0.0
    half_y = abs(float(lats[1] - lats[0])) / 2 if lats.size > 1 else 0.0
    columns = np.flatnonzero(
        (lons >= extent[0] - half_x) & (lons <= extent[1] + half_x)
    )
    rows = np.flatnonzero(
        (lats >= extent[2] - half_y) & (lats <= extent[3] + half_y)
    )
    window = np.ix_(rows, columns)

    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w", format="NETCDF4") as dataset:
        # setncattr: netCDF4 reserves some Python attribute names.
        dataset.setncattr("schema", SCHEMA)
        dataset.setncattr("layer", layer)
        for key, value in attrs.items():
            if value is not None:
                dataset.setncattr(key, value)
        dataset.createDimension("lat", len(rows))
        dataset.createDimension("lon", len(columns))
        compression = {"zlib": True, "complevel": 4, "shuffle": True}
        lat_var = dataset.createVariable("lat", "f8", ("lat",))
        lat_var.units = "degrees_north"
        lat_var[:] = lats[rows]
        lon_var = dataset.createVariable("lon", "f8", ("lon",))
        lon_var.units = "degrees_east"
        lon_var[:] = lons[columns]
        value = dataset.createVariable(
            "value",
            "f4",
            ("lat", "lon"),
            fill_value=np.float32(np.nan),
            **compression,
        )
        value.setncattr("units", attrs.get("unit", ""))
        value.setncattr("scale_to_unit", attrs.get("scale", 1.0))
        value.setncattr(
            "description", "Statistical grid; NaN = no valid value."
        )
        value[:] = np.asarray(values, dtype=np.float32)[window]
        mask = dataset.createVariable(
            "counted", "u1", ("lat", "lon"), **compression
        )
        mask.description = (
            "1 = cell centre strictly inside the region; counts toward "
            "statistics."
        )
        mask[:] = np.asarray(counted, dtype=np.uint8)[window]
        if valid_days is not None:
            days = dataset.createVariable(
                "valid_days", "i2", ("lat", "lon"), **compression
            )
            days.description = "Valid days per cell in the window."
            days[:] = np.asarray(valid_days, dtype=np.int16)[window]
        for name, data in (extra or {}).items():
            variable = dataset.createVariable(
                name,
                "f4",
                ("lat", "lon"),
                fill_value=np.float32(np.nan),
                **compression,
            )
            variable.setncattr("units", attrs.get("unit", ""))
            variable[:] = np.asarray(data, dtype=np.float32)[window]
    return {
        "path": str(path),
        "format": "netcdf4",
        "content": content,
        "layer": layer,
        "shape": [len(rows), len(columns)],
        "bytes": path.stat().st_size,
    }


def write_source_manifest(
    path: Path, files: list[str], failed: dict[str, str]
) -> dict[str, Any]:
    """List every input file with its read status (JSON keeps 200)."""
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "status", "reason"])
        for name in files:
            reason = failed.get(name)
            writer.writerow([name, "failed" if reason else "ok", reason or ""])
    return {
        "path": str(path),
        "format": "csv",
        "content": "source_manifest",
        "rows": len(files),
        "bytes": path.stat().st_size,
    }


def format_number(value: float | None) -> str:
    """Compact CSV text: up to 4 decimals, no trailing zeros, '' for NaN."""
    if value is None or not np.isfinite(value):
        return ""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def write_table_csv(
    path: Path,
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    content: str,
    layer: str,
) -> dict[str, Any]:
    """Write one CSV row per item; floats use ``format_number``."""
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(
                [
                    format_number(row[column])
                    if isinstance(row[column], (float, np.floating))
                    else row[column]
                    for column in columns
                ]
            )
    return {
        "path": str(path),
        "format": "csv",
        "content": content,
        "layer": layer,
        "rows": len(rows),
        "bytes": path.stat().st_size,
    }


def write_series_netcdf(
    path: Path,
    *,
    station_ids: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    timestamps: list[str],
    values: np.ndarray,
    layer: str,
    attrs: dict[str, Any],
    regional_mean: np.ndarray | None = None,
    hourly_counts: np.ndarray | None = None,
) -> dict[str, Any]:
    """Write hourly station values as ``value(station, time)``.

    ``time`` is CF hours since 1970-01-01 UTC; ``time_cst`` keeps the
    China-time ``YYYYMMDDHH`` labels the CLI uses.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from netCDF4 import Dataset

    china = ZoneInfo("Asia/Shanghai")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    hours = [
        (
            datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=china) - epoch
        ).total_seconds()
        / 3600
        for stamp in timestamps
    ]
    matrix = np.atleast_2d(np.asarray(values, dtype=np.float32))
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w", format="NETCDF4") as dataset:
        dataset.setncattr("schema", SCHEMA)
        dataset.setncattr("layer", layer)
        for key, value in attrs.items():
            if value is not None:
                dataset.setncattr(key, value)
        dataset.createDimension("station", matrix.shape[0])
        dataset.createDimension("time", matrix.shape[1])
        compression = {"zlib": True, "complevel": 4, "shuffle": True}
        ids = dataset.createVariable("station_id", str, ("station",))
        for index, station_id in enumerate(station_ids):
            ids[index] = str(station_id)
        for name, data, units in (
            ("lon", lon, "degrees_east"),
            ("lat", lat, "degrees_north"),
        ):
            variable = dataset.createVariable(name, "f8", ("station",))
            variable.setncattr("units", units)
            variable[:] = np.atleast_1d(np.asarray(data, dtype=float))
        time = dataset.createVariable("time", "f8", ("time",))
        time.setncattr("units", "hours since 1970-01-01 00:00:00")
        time.setncattr("calendar", "standard")
        time[:] = hours
        labels = dataset.createVariable("time_cst", str, ("time",))
        labels.setncattr("description", "Asia/Shanghai hour, YYYYMMDDHH")
        for index, stamp in enumerate(timestamps):
            labels[index] = stamp
        value = dataset.createVariable(
            "value",
            "f4",
            ("station", "time"),
            fill_value=np.float32(np.nan),
            **compression,
        )
        value.setncattr("units", attrs.get("unit", ""))
        value.setncattr("description", "Hourly value; NaN = missing.")
        value[:] = matrix
        if regional_mean is not None:
            mean = dataset.createVariable(
                "regional_mean",
                "f4",
                ("time",),
                fill_value=np.float32(np.nan),
                **compression,
            )
            mean.setncattr("description", "Mean over stations with a value.")
            mean[:] = np.asarray(regional_mean, dtype=np.float32)
        if hourly_counts is not None:
            counts = dataset.createVariable(
                "n_stations", "i4", ("time",), **compression
            )
            counts.setncattr("description", "Stations with a value per hour.")
            counts[:] = np.asarray(hourly_counts, dtype=np.int32)
    return {
        "path": str(path),
        "format": "netcdf4",
        "content": "hourly_series",
        "layer": layer,
        "shape": [int(matrix.shape[0]), int(matrix.shape[1])],
        "bytes": path.stat().st_size,
    }
