"""TROPOMI O3 reader.

Reads S5P_*_L2__O3_____ files, applies QA filtering, spatial subsetting,
and unit conversion to DU (Dobson Units). Supports both flattened NRT-style
variables and official PRODUCT-group files.
"""

from __future__ import annotations

from rsplot.readers._tropomi import TropomiReader, TropomiReaderSpec

# mol/m2 -> DU
# 1 DU = 2.6867e16 molec/cm2
# mol/m2 * Avogadro * 1e-4 (m2->cm2) / 2.6867e16 = DU
UNIT_CONVERSION = 6.02214076e23 * 1e-4 / 2.6867e16

VALUE_NAME = "ozone_total_vertical_column"

_SPEC = TropomiReaderSpec(
    filename_patterns=(
        "S5P_*_L2__O3_____{date}*.nc",
        "S5P_*_L2__O3_____{date}*.nc.zip",
    ),
    value_name=VALUE_NAME,
    unit_conversion=UNIT_CONVERSION,
    progress_description="[cyan]读取轨道数据...",
    not_found_message="未找到匹配文件:\n  {patterns}\n请检查 --data-dir 和 --date 参数。",
    no_valid_data_message="{date} 当天无有效数据覆盖目标区域 {extent}。\n共扫描 {n_files} 个文件，损坏 {n_broken} 个。",
)


class TropomiO3Reader(TropomiReader):
    """Reader for TROPOMI L2 O3 total column files."""

    spec = _SPEC
