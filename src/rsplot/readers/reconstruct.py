"""Hourly reconstructed surface air-quality grid reader.

Archive files are named ``YYYYMMDDHH.nc`` in UTC. User-facing CLI hours are
China standard time and are converted before lookup, matching the forecast and
ERA5 command conventions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from rsplot.readers.forecast import (
    ForecastVarInfo,
    get_forecast_var_info,
    normalize_forecast_var,
)
from rsplot.temporal import (
    DEFAULT_INPUT_TIMEZONE,
    adapt_hourly_time,
    parse_yyyymmdd,
)

RECONSTRUCT_ARCHIVE_TIMEZONE = "UTC"


class ReconstructFileNotReadyError(ValueError):
    """Raised when an archive file exists but cannot yet be read."""


@dataclass
class ReconstructData:
    """One spatially subset reconstructed pollutant field."""

    lon: np.ndarray
    lat: np.ndarray
    values: np.ndarray
    variable: str
    label: str
    unit: str
    datetime: str
    source_file: str
    archive_datetime: str
    native_resolution_deg: float
    output_resolution_deg: float
    n_source_cells: int
    n_source_valid: int
    n_output_cells: int
    n_output_valid: int
    timezone: str = DEFAULT_INPUT_TIMEZONE
    archive_timezone: str = RECONSTRUCT_ARCHIVE_TIMEZONE


def normalize_reconstruct_var(value: str) -> str:
    """Normalize reconstructed pollutant names using the forecast aliases."""
    try:
        return normalize_forecast_var(value)
    except ValueError as e:
        raise ValueError(str(e).replace("预报变量", "重构变量")) from e


def get_reconstruct_var_info(value: str) -> ForecastVarInfo:
    """Return shared surface-pollutant display metadata."""
    return get_forecast_var_info(normalize_reconstruct_var(value))


def read_reconstruct(
    data_dir: str,
    datetime_str: str,
    variable: str,
    extent: tuple[float, float, float, float],
    resolution: float,
) -> tuple[ReconstructData, str]:
    """Read one reconstructed field.

    ``datetime_str`` accepts an exact China-time hour or a China-time date.
    Date-only input chooses the latest readable UTC archive file within that
    local calendar day, skipping a newest file that is still being written.
    """
    var_name = normalize_reconstruct_var(variable)
    var_info = get_reconstruct_var_info(var_name)
    root = Path(data_dir)
    candidates = _candidate_hours(root, datetime_str)
    pending_errors: list[str] = []

    for path, local_datetime, archive_datetime in candidates:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        try:
            grid = _read_reconstruct_grid(
                path,
                var_name,
                extent,
                resolution,
            )
        except ReconstructFileNotReadyError as e:
            if len(datetime_str) == 10:
                raise
            pending_errors.append(str(e))
            continue

        (
            lon,
            lat,
            values,
            native_resolution,
            output_resolution,
            n_source_cells,
            n_source_valid,
        ) = grid
        finite = np.isfinite(values)
        return (
            ReconstructData(
                lon=lon,
                lat=lat,
                values=np.where(finite, values, np.nan),
                variable=var_name,
                label=var_info.label,
                unit=var_info.unit,
                datetime=local_datetime,
                source_file=str(path),
                archive_datetime=archive_datetime,
                native_resolution_deg=native_resolution,
                output_resolution_deg=output_resolution,
                n_source_cells=n_source_cells,
                n_source_valid=n_source_valid,
                n_output_cells=int(values.size),
                n_output_valid=int(finite.sum()),
            ),
            local_datetime,
        )

    if len(datetime_str) == 10:
        path, _, archive_datetime = candidates[0]
        raise FileNotFoundError(
            f"未找到重构文件: {path}\n"
            f"输入时次 {datetime_str} ({DEFAULT_INPUT_TIMEZONE}) "
            f"对应归档时次 {archive_datetime} "
            f"({RECONSTRUCT_ARCHIVE_TIMEZONE})。"
        )

    detail = (
        f"；跳过 {len(pending_errors)} 个未完成文件" if pending_errors else ""
    )
    raise FileNotFoundError(
        f"未找到 {datetime_str} 当天 ({DEFAULT_INPUT_TIMEZONE}) "
        f"可读取的重构文件: {root}{detail}"
    )


def _candidate_hours(
    root: Path,
    datetime_str: str,
) -> list[tuple[Path, str, str]]:
    if not datetime_str.isdigit() or len(datetime_str) not in (8, 10):
        raise ValueError(
            f"datetime 参数 '{datetime_str}' 格式不正确，"
            "请使用 YYYYMMDD 或 YYYYMMDDHH。"
        )

    if len(datetime_str) == 8:
        parse_yyyymmdd(datetime_str, "重构日期")
        local_hours = [
            f"{datetime_str}{hour:02d}" for hour in range(23, -1, -1)
        ]
    else:
        local_hours = [datetime_str]

    candidates: list[tuple[Path, str, str]] = []
    for local_datetime in local_hours:
        match = adapt_hourly_time(
            local_datetime,
            data_timezone=RECONSTRUCT_ARCHIVE_TIMEZONE,
            label="重构时次",
        )
        archive_datetime = match.data_datetime
        candidates.append(
            (
                root / f"{archive_datetime}.nc",
                local_datetime,
                archive_datetime,
            )
        )
    return candidates


def _read_reconstruct_grid(
    path: Path,
    variable: str,
    extent: tuple[float, float, float, float],
    resolution: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float, int, int]:
    try:
        ds = Dataset(path)
    except OSError as e:
        raise ReconstructFileNotReadyError(
            f"重构文件正在生成或已损坏，暂时无法打开: {path}"
        ) from e

    try:
        required = {"lat", "lon", variable}
        missing = sorted(required - set(ds.variables))
        if missing:
            raise ValueError(f"重构文件 {path} 缺少变量: {', '.join(missing)}")

        lon_raw = _read_coordinate(ds, "lon", path)
        lat_raw = _read_coordinate(ds, "lat", path)
        lon_values, lon_slice, reverse_lon = _subset_coordinate(
            lon_raw,
            extent[0],
            extent[1],
            "经度",
            path,
        )
        lat_values, lat_slice, reverse_lat = _subset_coordinate(
            lat_raw,
            extent[2],
            extent[3],
            "纬度",
            path,
        )

        lon_step = _coordinate_step(np.sort(lon_raw), "经度", path)
        lat_step = _coordinate_step(np.sort(lat_raw), "纬度", path)
        native_resolution = (lon_step + lat_step) / 2.0
        factor = _resolution_factor(resolution, lon_step, lat_step)

        lon_values, lon_slice = _align_subset(
            lon_raw,
            lon_slice,
            reverse_lon,
            factor,
        )
        lat_values, lat_slice = _align_subset(
            lat_raw,
            lat_slice,
            reverse_lat,
            factor,
        )

        data_var = ds.variables[variable]
        if data_var.dimensions != ("lat", "lon"):
            raise ValueError(
                f"重构变量 {variable} 维度应为 (lat, lon)，"
                f"实际为 {data_var.dimensions}: {path}"
            )
        data_var.set_auto_maskandscale(False)
        try:
            raw = np.asarray(data_var[lat_slice, lon_slice])
        except OSError as e:
            raise ReconstructFileNotReadyError(
                f"重构文件正在生成或已损坏，读取失败: {path}"
            ) from e
        if reverse_lat:
            raw = raw[::-1, :]
        if reverse_lon:
            raw = raw[:, ::-1]

        fill_value = getattr(data_var, "_FillValue", None)
        scale = float(getattr(data_var, "scale_factor", 1.0))
        offset = float(getattr(data_var, "add_offset", 0.0))
        values, n_source_valid = _decode_and_coarsen(
            raw,
            fill_value,
            scale,
            offset,
            factor,
        )
        if factor > 1:
            lon_values = _block_coordinate_mean(lon_values, factor)
            lat_values = _block_coordinate_mean(lat_values, factor)
        lon, lat = np.meshgrid(lon_values, lat_values)
        return (
            lon,
            lat,
            values,
            round(native_resolution, 4),
            round(resolution, 6),
            int(raw.size),
            n_source_valid,
        )
    finally:
        ds.close()


def _read_coordinate(ds: Dataset, name: str, path: Path) -> np.ndarray:
    variable = ds.variables[name]
    values = np.asarray(variable[:], dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError(f"重构文件 {path} 的 {name} 坐标无效。")
    diffs = np.diff(values)
    if not (np.all(diffs > 0) or np.all(diffs < 0)):
        raise ValueError(f"重构文件 {path} 的 {name} 坐标不是单调序列。")
    return values


def _subset_coordinate(
    values: np.ndarray,
    lower: float,
    upper: float,
    label: str,
    path: Path,
) -> tuple[np.ndarray, slice, bool]:
    if lower > upper:
        raise ValueError(f"暂不支持跨日期变更线的重构区域: {lower} > {upper}")
    indices = np.flatnonzero((values >= lower) & (values <= upper))
    if len(indices) == 0:
        raise ValueError(f"重构文件 {path} 在目标{label}范围内没有网格点。")
    start = int(indices.min())
    stop = int(indices.max()) + 1
    reverse = bool(values[0] > values[-1])
    selected = values[start:stop]
    if reverse:
        selected = selected[::-1]
    return selected, slice(start, stop), reverse


def _coordinate_step(values: np.ndarray, label: str, path: Path) -> float:
    diffs = np.diff(values)
    step = float(np.median(diffs))
    if not np.allclose(diffs, step, rtol=1e-3, atol=1e-6):
        raise ValueError(f"重构文件 {path} 的{label}网格不是规则间隔。")
    return step


def _resolution_factor(
    resolution: float,
    lon_step: float,
    lat_step: float,
) -> int:
    native = (lon_step + lat_step) / 2.0
    if resolution < native * 0.999:
        raise ValueError(
            f"--res ({resolution}) 不能小于原生分辨率 ({native:.4f})。"
        )
    factor = max(1, round(resolution / native))
    if not (
        np.isclose(factor * lon_step, resolution, rtol=0.01, atol=1e-6)
        and np.isclose(factor * lat_step, resolution, rtol=0.01, atol=1e-6)
    ):
        raise ValueError(
            f"--res ({resolution}) 必须是原生分辨率 ({native:.4f}) 的整数倍。"
        )
    return factor


def _align_subset(
    full_values: np.ndarray,
    selected_slice: slice,
    reverse: bool,
    factor: int,
) -> tuple[np.ndarray, slice]:
    size = len(full_values)
    source_start = int(selected_slice.start or 0)
    source_stop = int(selected_slice.stop or size)
    if reverse:
        sorted_start = size - source_stop
        sorted_stop = size - source_start
    else:
        sorted_start = source_start
        sorted_stop = source_stop
    aligned_start = (sorted_start // factor) * factor
    aligned_stop = min(
        size,
        ((sorted_stop + factor - 1) // factor) * factor,
    )
    sorted_values = full_values[::-1] if reverse else full_values
    selected = sorted_values[aligned_start:aligned_stop]
    if reverse:
        source_slice = slice(size - aligned_stop, size - aligned_start)
    else:
        source_slice = slice(aligned_start, aligned_stop)
    return selected, source_slice


def _decode_and_coarsen(
    raw: np.ndarray,
    fill_value: object,
    scale: float,
    offset: float,
    factor: int,
) -> tuple[np.ndarray, int]:
    valid = np.isfinite(raw)
    if fill_value is not None:
        valid &= raw != fill_value
    n_source_valid = int(valid.sum())

    if factor == 1:
        values = raw.astype(float) * scale + offset
        values[~valid] = np.nan
        return values, n_source_valid

    pad_rows = (-raw.shape[0]) % factor
    pad_cols = (-raw.shape[1]) % factor
    if pad_rows or pad_cols:
        raw = np.pad(
            raw,
            ((0, pad_rows), (0, pad_cols)),
            constant_values=0,
        )
        valid = np.pad(
            valid,
            ((0, pad_rows), (0, pad_cols)),
            constant_values=False,
        )
    shape = (
        raw.shape[0] // factor,
        factor,
        raw.shape[1] // factor,
        factor,
    )
    raw_blocks = raw.reshape(shape)
    valid_blocks = valid.reshape(shape)
    sums = np.sum(
        raw_blocks,
        axis=(1, 3),
        dtype=float,
        where=valid_blocks,
    )
    counts = valid_blocks.sum(axis=(1, 3))
    means = np.full(sums.shape, np.nan, dtype=float)
    np.divide(sums, counts, out=means, where=counts > 0)
    means = means * scale + offset
    return means, n_source_valid


def _block_coordinate_mean(values: np.ndarray, factor: int) -> np.ndarray:
    return np.array(
        [
            float(np.mean(values[start : start + factor]))
            for start in range(0, len(values), factor)
        ]
    )
