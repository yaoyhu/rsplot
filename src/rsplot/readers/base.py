"""Abstract base class for satellite data readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import xarray as xr


@dataclass
class SwathData:
    """Raw swath data after QA filtering and spatial subsetting."""

    lon: np.ndarray  # 1-D
    lat: np.ndarray  # 1-D
    values: np.ndarray  # 1-D, in display units
    n_pixels: int
    n_files: int
    n_broken: int
    metadata: dict[str, Any] = field(default_factory=dict)
    corner_lon: np.ndarray | None = None  # (n_pixels, 4)
    corner_lat: np.ndarray | None = None  # (n_pixels, 4)


class BaseReader(ABC):
    """Interface for reading a single-day satellite product."""

    def iter_scans(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> Iterator[SwathData]:
        """Yield temporal batches; legacy readers supply one daily batch."""
        yield self.read(data_dir, date, extent, qa_threshold)

    @abstractmethod
    def read(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> SwathData:
        """Read and filter all orbits for a given date and spatial extent.

        Parameters
        ----------
        data_dir : root directory containing product files.
        date : date string, e.g. "20260208".
        extent : (lon_min, lon_max, lat_min, lat_max).
        qa_threshold : minimum QA value to keep.

        Returns
        -------
        SwathData with concatenated 1-D arrays.
        """
        ...


def read_tropomi_product_arrays(
    path: str, value_name: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Read lon/lat/value/qa from either flattened or grouped TROPOMI files.

    Some local archives flatten the ``/PRODUCT`` group into variables like
    ``PRODUCT_longitude``; official OFFL files usually keep a real PRODUCT
    NetCDF group with plain variable names. This helper accepts both layouts.
    """
    flat_names = {
        "lon": "PRODUCT_longitude",
        "lat": "PRODUCT_latitude",
        "value": f"PRODUCT_{value_name}",
        "qa": "PRODUCT_qa_value",
    }
    group_names = {
        "lon": "longitude",
        "lat": "latitude",
        "value": value_name,
        "qa": "qa_value",
    }

    errors: list[str] = []
    for group, names in ((None, flat_names), ("PRODUCT", group_names)):
        try:
            kwargs = {} if group is None else {"group": group}
            ds = xr.open_dataset(path, **kwargs)
        except (OSError, ValueError) as e:
            label = "root" if group is None else group
            errors.append(f"{label}: {e}")
            continue

        try:
            lon = ds[names["lon"]].squeeze().values
            lat = ds[names["lat"]].squeeze().values
            value = ds[names["value"]].squeeze().values
            qa = ds[names["qa"]].squeeze().values
            return lon, lat, value, qa
        except KeyError as e:
            label = "root" if group is None else group
            errors.append(f"{label}: missing {e}")
        finally:
            ds.close()

    msg = "; ".join(str(e).splitlines()[0] for e in errors)
    raise ValueError(f"无法读取 TROPOMI PRODUCT 变量: {msg}")


def read_tropomi_product_arrays_with_cloud(
    path: str,
    value_name: str,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Read core TROPOMI arrays plus the retrieval cloud fraction.

    OFFL products generally expose ``cloud_fraction_crb`` while some NRT
    products use ``cloud_fraction``. Both grouped official files and flattened
    local archives are supported. The original four-array helper remains
    unchanged for callers that do not need cloud filtering.
    """
    lon, lat, values, qa = read_tropomi_product_arrays(path, value_name)
    cloud_fraction = _read_tropomi_cloud_fraction(path)
    if cloud_fraction.shape != values.shape:
        raise ValueError(
            "TROPOMI 云量变量形状不匹配: "
            f"cloud={cloud_fraction.shape}, value={values.shape}"
        )
    return lon, lat, values, qa, cloud_fraction


def _read_tropomi_cloud_fraction(path: str) -> np.ndarray:
    """Read cloud fraction from known grouped and flattened layouts."""
    flat_names = (
        "PRODUCT_SUPPORT_DATA_INPUT_DATA_cloud_fraction_crb",
        "PRODUCT_SUPPORT_DATA_INPUT_DATA_cloud_fraction",
        "PRODUCT_cloud_fraction_crb",
        "PRODUCT_cloud_fraction",
        "cloud_fraction_crb",
        "cloud_fraction",
    )
    group_names = ("cloud_fraction_crb", "cloud_fraction")
    layouts = (
        (None, flat_names),
        ("PRODUCT/SUPPORT_DATA/INPUT_DATA", group_names),
    )

    errors: list[str] = []
    for group, names in layouts:
        try:
            kwargs = {} if group is None else {"group": group}
            ds = xr.open_dataset(path, **kwargs)
        except (OSError, ValueError) as error:
            label = "root" if group is None else group
            errors.append(f"{label}: {error}")
            continue

        try:
            for name in names:
                if name in ds:
                    return ds[name].squeeze().values
            label = "root" if group is None else group
            errors.append(f"{label}: missing {' / '.join(names)}")
        finally:
            ds.close()

    msg = "; ".join(str(error).splitlines()[0] for error in errors)
    raise ValueError(f"无法读取 TROPOMI 云量变量: {msg}")
