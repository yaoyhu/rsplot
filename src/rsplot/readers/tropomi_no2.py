"""TROPOMI NO2 reader.

Reads S5P_*_L2__NO2____ files, applies QA filtering, spatial subsetting,
and unit conversion to 10^15 molec/cm2. Supports both flattened NRT-style
variables and official PRODUCT-group files.
"""

from __future__ import annotations

from rsplot.readers._tropomi import TropomiReader, TropomiReaderSpec

# mol/m2 -> 10^15 molec/cm2
UNIT_CONVERSION = 6.02214076e23 * 1e-4 * 1e-15

VALUE_NAME = "nitrogendioxide_tropospheric_column"

_SPEC = TropomiReaderSpec(
    filename_patterns=(
        "S5P_*_L2__NO2____{date}*.nc",
        "S5P_*_L2__NO2____{date}*.nc.zip",
    ),
    value_name=VALUE_NAME,
    unit_conversion=UNIT_CONVERSION,
    progress_description="[cyan]读取轨道数据...",
    not_found_message="未找到匹配文件:\n  {patterns}\n请检查 --data-dir 和 --date 参数。",
    no_valid_data_message="{date} 当天无有效数据覆盖目标区域 {extent}。\n共扫描 {n_files} 个文件，损坏 {n_broken} 个。",
)


class TropomiNO2Reader(TropomiReader):
    """Reader for TROPOMI L2 NO2 tropospheric column files."""

    spec = _SPEC
