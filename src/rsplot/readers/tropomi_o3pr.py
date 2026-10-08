"""TROPOMI O3 profile reader.

Reads S5P_*_L2__O3__PR files, applies QA filtering, spatial subsetting,
and converts the profile-derived tropospheric ozone column to DU.
"""

from __future__ import annotations

from rsplot.readers._tropomi import TropomiReader, TropomiReaderSpec

# mol/m2 -> DU, from the product attribute
# multiplication_factor_to_convert_to_DU = 2241.15
UNIT_CONVERSION = 2241.15

VALUE_NAME = "ozone_tropospheric_column"

_SPEC = TropomiReaderSpec(
    filename_patterns=(
        "S5P_*_L2__O3__PR_{date}T*.nc",
        "S5P_*_L2__O3__PR_{date}T*.nc.zip",
    ),
    value_name=VALUE_NAME,
    unit_conversion=UNIT_CONVERSION,
    progress_description="[cyan]读取 O3PR 轨道...",
    not_found_message="未找到匹配文件:\n  {patterns}\n请检查配置 [paths.data_dirs] 中的数据目录和日期。",
    no_valid_data_message="{date} 当天 O3PR 无有效数据覆盖目标区域 {extent}。\n共扫描 {n_files} 个文件，损坏 {n_broken} 个。",
)


class TropomiO3PRReader(TropomiReader):
    """Reader for TROPOMI L2 O3 profile tropospheric-column files."""

    spec = _SPEC
