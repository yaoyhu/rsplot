"""Abstract base class for satellite data readers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


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
