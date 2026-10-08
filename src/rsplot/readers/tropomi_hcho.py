"""TROPOMI HCHO reader.

Reads S5P_*_L2__HCHO___ files, applies QA filtering and spatial
subsetting, and converts columns to 10^15 molec/cm2.
"""

from __future__ import annotations

from rsplot.readers._tropomi import TropomiReader, TropomiReaderSpec

# mol/m² -> 10^15 molec/cm² (same convention as the NO2 reader)
UNIT_CONVERSION = 6.02214076e23 * 1e-4 * 1e-15

VALUE_NAME = "formaldehyde_tropospheric_vertical_column"

_SPEC = TropomiReaderSpec(
    filename_patterns=(
        "S5P_*_L2__HCHO___{date}T*.nc",
        "S5P_*_L2__HCHO___{date}T*.nc.zip",
    ),
    value_name=VALUE_NAME,
    unit_conversion=UNIT_CONVERSION,
    progress_description="[cyan]读取 HCHO 轨道...",
    not_found_message="未找到匹配文件: \n  {patterns}\n请检查配置 [paths.data_dirs] 中的数据目录和日期 {date}。",
    no_valid_data_message="{date} 当天 HCHO 无有效数据覆盖目标区域 {extent}。\n共扫描 {n_files} 个文件，损坏 {n_broken} 个；可尝试放宽 --qa 阈值。",
)


class TropomiHCHOReader(TropomiReader):
    """Reader for TROPOMI OFFL L2 HCHO tropospheric column files."""

    spec = _SPEC
