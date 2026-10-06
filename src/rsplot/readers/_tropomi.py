"""Shared implementation for TROPOMI swath readers."""

from __future__ import annotations

from collections.abc import Iterator
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

    def __init__(self, *, processing: str | None = None) -> None:
        if processing not in (None, "nrti"):
            raise ValueError("TROPOMI processing 仅支持 nrti 或 None")
        self.processing = processing

    def iter_scans(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> Iterator[SwathData]:
        """Keep failed NRTI days diagnosable in window results."""
        if self.processing is None:
            yield self.read(data_dir, date, extent, qa_threshold)
            return

        from rsplot.readers.tropomi_nrti import NrtiReadError

        try:
            yield self.read(data_dir, date, extent, qa_threshold)
        except NrtiReadError as error:
            yield SwathData(
                lon=np.array([]),
                lat=np.array([]),
                values=np.array([]),
                n_pixels=0,
                n_files=error.metadata["n_files"],
                n_broken=error.metadata["n_broken"],
                metadata=error.metadata,
            )

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
        if self.processing == "nrti":
            relative_patterns = [
                pattern.replace("S5P_*_", "S5P_NRTI_")
                for pattern in relative_patterns
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

        if self.processing == "nrti":
            from rsplot.readers.tropomi_nrti import (
                NrtiReadError,
                granule_identity,
                observation_range,
                read_nrti_observations,
            )

        lon_min, lon_max, lat_min, lat_max = extent
        all_lon: list[np.ndarray] = []
        all_lat: list[np.ndarray] = []
        all_values: list[np.ndarray] = []
        broken = 0
        broken_examples: list[str] = []
        failed_files: dict[str, str] = {}
        all_keys: list[np.ndarray] = []
        priorities: list[tuple[str, str, int]] = []
        processor_versions: set[str] = set()
        product_versions: set[str] = set()

        for path in track(files, description=spec.progress_description):
            try:
                lon, lat, values, qa, cloud_fraction = (
                    read_tropomi_product_arrays_with_cloud(
                        path,
                        spec.value_name,
                    )
                )
                if self.processing == "nrti":
                    observations = read_nrti_observations(path, values.shape)
                    _, production = granule_identity(path)
                    if observations.processor_version:
                        processor_versions.add(observations.processor_version)
                    if observations.product_version:
                        product_versions.add(observations.product_version)
            except (OSError, ValueError, KeyError) as error:
                broken += 1
                failed_files[path] = str(error).splitlines()[0]
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
                if self.processing == "nrti":
                    priorities.append((production, path, len(all_keys)))
                    all_keys.append(observations.keys[mask])
                all_lon.append(lon[mask])
                all_lat.append(lat[mask])
                all_values.append(values[mask] * spec.unit_conversion)

        # Every stream records its inputs; NRTI adds deduplication details.
        metadata: dict = {
            "source_files": files,
            "failed_files": failed_files,
        }
        if self.processing == "nrti":
            metadata = {
                "sensor": "tropomi",
                "processing": "nrti",
                "date_basis": "filename_start_date_utc",
                "aggregation": "deduplicated_pixel_mean",
                "source_files": files,
                "failed_files": failed_files,
                "processor_versions": sorted(processor_versions),
                "product_versions": sorted(product_versions),
                "deduplication": {
                    "key": ["orbit", "time_utc_ms", "ground_pixel"],
                    "selection": "latest_valid_production_then_filename",
                },
                "n_files": len(files),
                "n_broken": broken,
                "n_pixels": 0,
                "n_pixels_before_dedup": 0,
                "n_duplicates_removed": 0,
                "observation_time_range_utc": None,
            }

        if not all_lon:
            broken_message = (
                "\n损坏/不可读示例:\n  " + "\n  ".join(broken_examples)
                if broken_examples
                else ""
            )
            message = (
                spec.no_valid_data_message.format(
                    date=date,
                    extent=extent,
                    n_files=len(files),
                    n_broken=broken,
                )
                + broken_message
            )
            if self.processing == "nrti":
                raise NrtiReadError(message, metadata)
            raise ValueError(message)

        if self.processing == "nrti":
            # Stable sorts give newest production first, filename ascending
            # for ties. np.unique's first index then selects the valid winner.
            priorities.sort(key=lambda item: item[1])
            priorities.sort(key=lambda item: item[0], reverse=True)
            order = [item[2] for item in priorities]
            keys = np.concatenate([all_keys[index] for index in order])
            _, selected = np.unique(keys, return_index=True)
            selected.sort()
            before = len(keys)
            all_lon = [np.concatenate([all_lon[i] for i in order])[selected]]
            all_lat = [np.concatenate([all_lat[i] for i in order])[selected]]
            all_values = [
                np.concatenate([all_values[i] for i in order])[selected]
            ]
            metadata.update(
                n_pixels=len(selected),
                n_pixels_before_dedup=before,
                n_duplicates_removed=before - len(selected),
                observation_time_range_utc=observation_range(keys[selected]),
            )

        return SwathData(
            lon=np.concatenate(all_lon),
            lat=np.concatenate(all_lat),
            values=np.concatenate(all_values),
            n_pixels=sum(len(values) for values in all_lon),
            n_files=len(files),
            n_broken=broken,
            metadata=metadata,
        )
