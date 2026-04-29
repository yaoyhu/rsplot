"""Abstract base class for satellite data readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

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


class BaseReader(ABC):
    """Interface for reading a single-day satellite product."""

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
