"""TROPOMI OFFL L2 HCHO reader.

Reads ``S5P_OFFL_L2__HCHO___`` per-orbit swath files, applies QA
filtering, spatial subsetting, and unit conversion to ``10^15 molec/cm²``.

Filename pattern (one file per orbit, ~16 files per day)::

    S5P_OFFL_L2__HCHO___{YYYYMMDD}T{HHMMSS}_{end}_{orbit}_{coll}_{proc}_{tstamp}.nc.zip

Two structural differences from the NO2 / O3 NRTI readers:

1. **Real NetCDF groups, not flat names.** OFFL files keep the
   ``/PRODUCT`` group hierarchy intact, so xarray's root-level dataset
   is empty. We open the ``PRODUCT`` group explicitly and address
   variables by their plain name (``longitude``, ``qa_value`` …) rather
   than the underscore-flattened ``PRODUCT_longitude`` form the NRTI
   readers use.
2. **Misleading ``.nc.zip`` extension.** ``file(1)`` reports each as
   native HDF5 / NetCDF4, so xarray reads them directly without any
   unzip step. We also accept plain ``.nc`` in case files are
   re-distributed without the suffix.

Unit: the source attribute on the variable is ``mol m-2``. We convert
to ``10^15 molec/cm²`` so HCHO matches the NO2 colorbar units and so
FNR = HCHO / NO2 is a dimensionless ratio directly comparable with the
literature.
"""

from __future__ import annotations

import glob
import os

import numpy as np
from rich.progress import track

from rsplot.readers.base import (
    BaseReader,
    SwathData,
    read_tropomi_product_arrays,
)

# mol/m² -> 10^15 molec/cm² (same convention as the NO2 reader)
UNIT_CONVERSION = 6.02214076e23 * 1e-4 * 1e-15

VALUE_NAME = "formaldehyde_tropospheric_vertical_column"


class TropomiHCHOReader(BaseReader):
    """Reader for TROPOMI OFFL L2 HCHO tropospheric column files."""

    def read(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> SwathData:
        # Match both `.nc` and `.nc.zip` (the latter is HDF5 underneath
        # despite the misleading extension in this archive).
        patterns = [
            os.path.join(data_dir, f"S5P_*_L2__HCHO___{date}T*.nc"),
            os.path.join(data_dir, f"S5P_*_L2__HCHO___{date}T*.nc.zip"),
        ]
        files: list[str] = []
        for p in patterns:
            files.extend(glob.glob(p))
        files = sorted(set(files))
        if not files:
            raise FileNotFoundError(
                f"未找到匹配文件: \n  "
                + "\n  ".join(patterns)
                + f"\n请检查 --hcho-dir / --data-dir 和 --date={date}。"
            )

        lon_min, lon_max, lat_min, lat_max = extent
        all_lon, all_lat, all_hcho = [], [], []
        broken = 0
        broken_examples: list[str] = []

        for f in track(files, description="[cyan]读取 HCHO 轨道..."):
            try:
                lon, lat, hcho, qa = read_tropomi_product_arrays(f, VALUE_NAME)
            except (OSError, ValueError, KeyError) as e:
                broken += 1
                if len(broken_examples) < 3:
                    broken_examples.append(
                        f"{os.path.basename(f)}: {str(e).splitlines()[0]}"
                    )
                continue

            mask = (
                (qa > qa_threshold)
                & (lon >= lon_min)
                & (lon <= lon_max)
                & (lat >= lat_min)
                & (lat <= lat_max)
                & np.isfinite(hcho)
                & (hcho < 1e30)
            )
            if mask.sum() > 0:
                all_lon.append(lon[mask])
                all_lat.append(lat[mask])
                all_hcho.append(hcho[mask] * UNIT_CONVERSION)

        if not all_lon:
            broken_msg = (
                "\n损坏/不可读示例:\n  " + "\n  ".join(broken_examples)
                if broken_examples
                else ""
            )
            raise ValueError(
                f"{date} 当天 HCHO 无有效数据覆盖目标区域 {extent}。\n"
                f"共扫描 {len(files)} 个文件，损坏 {broken} 个；"
                f"可尝试放宽 --qa 阈值。"
                f"{broken_msg}"
            )

        return SwathData(
            lon=np.concatenate(all_lon),
            lat=np.concatenate(all_lat),
            values=np.concatenate(all_hcho),
            n_pixels=sum(len(a) for a in all_lon),
            n_files=len(files),
            n_broken=broken,
        )
