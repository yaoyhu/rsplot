"""Observation identity and provenance for TROPOMI NRTI granules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

_FILENAME = re.compile(
    r"^S5P_NRTI_L2__.{7}(\d{8}T\d{6})_(\d{8}T\d{6})_"
    r"(\d{5})_\d{2}_\d{6}_(\d{8}T\d{6})\.nc(?:\.zip)?$"
)
IDENTITY_DTYPE = np.dtype(
    [("orbit", "i8"), ("time_ms", "i8"), ("ground_pixel", "i8")]
)


class NrtiReadError(ValueError):
    """A failed day whose per-file diagnostics can still reach sidecars."""

    def __init__(self, message: str, metadata: dict[str, Any]):
        super().__init__(message)
        self.metadata = metadata


def granule_identity(path: str) -> tuple[int, str]:
    """Return orbit and production timestamp from the standard filename."""
    match = _FILENAME.fullmatch(Path(path).name)
    if match is None:
        raise ValueError(
            f"NRTI 文件名无法识别轨道与生成时间: {Path(path).name}"
        )
    for value in (match[1], match[2], match[4]):
        datetime.strptime(value, "%Y%m%dT%H%M%S")
    return int(match[3]), match[4]


def _utc_milliseconds(values: np.ndarray, units: str) -> np.ndarray:
    match = re.fullmatch(r"(milliseconds|seconds) since (.+)", units)
    if match is None:
        raise ValueError(f"NRTI delta_time 单位不支持: {units}")
    origin = datetime.fromisoformat(match[2].replace("Z", "+00:00"))
    if origin.tzinfo is None:
        origin = origin.replace(tzinfo=timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    offset_ms = round((origin - epoch).total_seconds() * 1000)
    factor = 1 if match[1] == "milliseconds" else 1000
    milliseconds = np.asarray(values, dtype=float) * factor + offset_ms
    if not np.all(np.isfinite(milliseconds)):
        raise ValueError("NRTI 观测时间包含缺失或非有限值")
    if np.any(np.abs(milliseconds) >= np.iinfo(np.int64).max):
        raise ValueError("NRTI 观测时间超出范围")
    return np.rint(milliseconds).astype(np.int64)


@dataclass
class NrtiObservations:
    keys: np.ndarray
    processor_version: str | None
    product_version: str | None


def read_nrti_observations(
    path: str, shape: tuple[int, ...]
) -> NrtiObservations:
    """Read real pixel IDs; never substitute file-local scanline indices.

    delta_time is either per scanline (NO2/O3PR) or per pixel (HCHO/O3).
    Its CF units already contain the UTC reference epoch, so adding the
    separate PRODUCT/time value again would double-count that epoch.
    """
    orbit, _ = granule_identity(path)
    errors = []
    with xr.open_dataset(path, decode_times=False) as root:
        processor = root.attrs.get("processor_version")
        version = root.attrs.get("product_version")
    for group, prefix in ((None, "PRODUCT_"), ("PRODUCT", "")):
        try:
            kwargs = {} if group is None else {"group": group}
            with xr.open_dataset(path, decode_times=False, **kwargs) as ds:
                delta = ds[f"{prefix}delta_time"]
                times = _utc_milliseconds(
                    delta.values.squeeze(), delta.attrs.get("units", "")
                )
                columns = ds[f"{prefix}ground_pixel"].values.squeeze()
                if len(shape) == 2 and times.ndim == 1:
                    times = times[:, None]
                times = np.broadcast_to(times, shape)
                columns = np.broadcast_to(columns, shape)
                if not np.all(np.isfinite(columns)) or np.any(
                    columns != np.floor(columns)
                ):
                    raise ValueError("NRTI ground_pixel 索引无效")
                keys = np.empty(shape, dtype=IDENTITY_DTYPE)
                keys["orbit"] = orbit
                keys["time_ms"] = times
                keys["ground_pixel"] = columns
                return NrtiObservations(keys, processor, version)
        except (OSError, ValueError, KeyError) as error:
            errors.append(str(error).splitlines()[0])
    raise ValueError("无法读取 NRTI 观测身份: " + "; ".join(errors))


def observation_range(keys: np.ndarray) -> dict[str, str] | None:
    if not keys.size:
        return None
    times = keys["time_ms"]
    return {
        label: str(np.datetime64(int(value), "ms")) + "Z"
        for label, value in (("start", times.min()), ("end", times.max()))
    }
