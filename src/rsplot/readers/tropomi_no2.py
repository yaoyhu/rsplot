"""TROPOMI NRT NO2 reader.

Reads S5P_NRTI_L2__NO2____ files, applies QA filtering, spatial subsetting,
and unit conversion to 10^15 molec/cm2.
"""

from __future__ import annotations

import glob
import os

import numpy as np
import xarray as xr
from rich.progress import track

from rsplot.readers.base import BaseReader, SwathData

# mol/m2 -> 10^15 molec/cm2
UNIT_CONVERSION = 6.02214076e23 * 1e-4 * 1e-15

# Variable name prefix in NRT products
PREFIX = "PRODUCT_"


class TropomiNO2Reader(BaseReader):
    """Reader for TROPOMI NRT L2 NO2 tropospheric column files."""

    def read(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> SwathData:
        pattern = os.path.join(data_dir, f"S5P_NRTI_L2__NO2____{date}*.nc")
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(
                f"未找到匹配文件: {pattern}\n请检查 --data-dir 和 --date 参数。"
            )

        lon_min, lon_max, lat_min, lat_max = extent
        all_lon, all_lat, all_no2 = [], [], []
        broken = 0

        for f in track(files, description="[cyan]读取轨道数据..."):
            try:
                ds = xr.open_dataset(f, engine="netcdf4")
            except OSError:
                broken += 1
                continue

            try:
                lon = ds[f"{PREFIX}longitude"].squeeze().values
                lat = ds[f"{PREFIX}latitude"].squeeze().values
                no2 = (
                    ds[f"{PREFIX}nitrogendioxide_tropospheric_column"]
                    .squeeze()
                    .values
                )
                qa = ds[f"{PREFIX}qa_value"].squeeze().values
            finally:
                ds.close()

            mask = (
                (qa > qa_threshold)
                & (lon >= lon_min)
                & (lon <= lon_max)
                & (lat >= lat_min)
                & (lat <= lat_max)
                & np.isfinite(no2)
                & (no2 < 1e30)
            )
            if mask.sum() > 0:
                all_lon.append(lon[mask])
                all_lat.append(lat[mask])
                all_no2.append(no2[mask] * UNIT_CONVERSION)

        if not all_lon:
            raise ValueError(
                f"{date} 当天无有效数据覆盖目标区域 {extent}。\n"
                f"共扫描 {len(files)} 个文件，损坏 {broken} 个。"
            )

        return SwathData(
            lon=np.concatenate(all_lon),
            lat=np.concatenate(all_lat),
            values=np.concatenate(all_no2),
            n_pixels=sum(len(a) for a in all_lon),
            n_files=len(files),
            n_broken=broken,
        )
