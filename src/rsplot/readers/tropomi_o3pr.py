"""TROPOMI O3 profile tropospheric-column reader.

Reads ``S5P_*_L2__O3__PR`` ozone profile products and uses the provided
``ozone_tropospheric_column`` variable directly. Values are converted from
``mol m-2`` to DU.
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

VALUE_NAME = "ozone_tropospheric_column"

# mol/m2 -> DU, from the product attribute
# multiplication_factor_to_convert_to_DU = 2241.15
UNIT_CONVERSION = 2241.15


class TropomiO3PRReader(BaseReader):
    """Reader for TROPOMI L2 O3 profile tropospheric-column files."""

    def read(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> SwathData:
        patterns = [
            os.path.join(data_dir, f"S5P_*_L2__O3__PR_{date}T*.nc"),
            os.path.join(data_dir, f"S5P_*_L2__O3__PR_{date}T*.nc.zip"),
        ]
        files: list[str] = []
        for p in patterns:
            files.extend(glob.glob(p))
        files = sorted(set(files))
        if not files:
            raise FileNotFoundError(
                f"未找到匹配文件:\n  "
                + "\n  ".join(patterns)
                + "\n请检查 --data-dir 和 --date 参数。"
            )

        lon_min, lon_max, lat_min, lat_max = extent
        all_lon, all_lat, all_o3 = [], [], []
        broken = 0
        broken_examples: list[str] = []

        for f in track(files, description="[cyan]读取 O3PR 轨道..."):
            try:
                lon, lat, o3, qa = read_tropomi_product_arrays(f, VALUE_NAME)
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
                & np.isfinite(o3)
                & (o3 < 1e30)
            )
            if mask.sum() > 0:
                all_lon.append(lon[mask])
                all_lat.append(lat[mask])
                all_o3.append(o3[mask] * UNIT_CONVERSION)

        if not all_lon:
            broken_msg = (
                "\n损坏/不可读示例:\n  " + "\n  ".join(broken_examples)
                if broken_examples
                else ""
            )
            raise ValueError(
                f"{date} 当天 O3PR 无有效数据覆盖目标区域 {extent}。\n"
                f"共扫描 {len(files)} 个文件，损坏 {broken} 个。"
                f"{broken_msg}"
            )

        return SwathData(
            lon=np.concatenate(all_lon),
            lat=np.concatenate(all_lat),
            values=np.concatenate(all_o3),
            n_pixels=sum(len(a) for a in all_lon),
            n_files=len(files),
            n_broken=broken,
        )
