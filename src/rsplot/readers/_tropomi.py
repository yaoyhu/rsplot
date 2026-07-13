"""Shared implementation for TROPOMI swath readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np
from rich.progress import track

from rsplot.readers.base import (
    BaseReader,
    SwathData,
    read_tropomi_product_arrays_with_cloud,
)

CLOUD_FRACTION_MAX = 0.5


@dataclass(frozen=True)
class TropomiReaderSpec:
    """Product-specific details for the common TROPOMI read workflow."""

    filename_patterns: tuple[str, ...]
    value_name: str
    unit_conversion: float
    progress_description: str
    not_found_message: str
    no_valid_data_message: str


class TropomiReader(BaseReader):
    """Base implementation shared by concrete TROPOMI products."""

    spec: ClassVar[TropomiReaderSpec]
    cloud_fraction_max: float = CLOUD_FRACTION_MAX

    def read(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> SwathData:
        """Read, filter, and concatenate one day of product swaths."""
        spec = self.spec
        root = Path(data_dir)
        relative_patterns = [
            pattern.format(date=date) for pattern in spec.filename_patterns
        ]
        patterns = [str(root / pattern) for pattern in relative_patterns]
        files = sorted(
            {
                str(path)
                for pattern in relative_patterns
                for path in root.glob(pattern)
            }
        )
        if not files:
            raise FileNotFoundError(
                spec.not_found_message.format(
                    date=date,
                    patterns="\n  ".join(patterns),
                )
            )

        lon_min, lon_max, lat_min, lat_max = extent
        all_lon: list[np.ndarray] = []
        all_lat: list[np.ndarray] = []
        all_values: list[np.ndarray] = []
        broken = 0
        broken_examples: list[str] = []

        for path in track(files, description=spec.progress_description):
            try:
                lon, lat, values, qa, cloud_fraction = (
                    read_tropomi_product_arrays_with_cloud(
                        path,
                        spec.value_name,
                    )
                )
            except (OSError, ValueError, KeyError) as error:
                broken += 1
                if len(broken_examples) < 3:
                    broken_examples.append(
                        f"{Path(path).name}: {str(error).splitlines()[0]}"
                    )
                continue

            mask = (
                (qa > qa_threshold)
                & np.isfinite(cloud_fraction)
                & (cloud_fraction <= self.cloud_fraction_max)
                & (lon >= lon_min)
                & (lon <= lon_max)
                & (lat >= lat_min)
                & (lat <= lat_max)
                & np.isfinite(values)
                & (values < 1e30)
            )
            if mask.sum() > 0:
                all_lon.append(lon[mask])
                all_lat.append(lat[mask])
                all_values.append(values[mask] * spec.unit_conversion)

        if not all_lon:
            broken_message = (
                "\n损坏/不可读示例:\n  " + "\n  ".join(broken_examples)
                if broken_examples
                else ""
            )
            raise ValueError(
                spec.no_valid_data_message.format(
                    date=date,
                    extent=extent,
                    n_files=len(files),
                    n_broken=broken,
                )
                + broken_message
            )

        return SwathData(
            lon=np.concatenate(all_lon),
            lat=np.concatenate(all_lat),
            values=np.concatenate(all_values),
            n_pixels=sum(len(values) for values in all_lon),
            n_files=len(files),
            n_broken=broken,
        )
