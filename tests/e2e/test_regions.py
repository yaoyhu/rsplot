"""Region-naming user scenarios; see REGION_SCENARIOS.md."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from raster_support import ANY_OPTION, assert_failed, schema_errors
from region_support import RegionWorkspace


class RegionE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-region-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = RegionWorkspace(Path(self.temp.name))
        self.workspace.write_swath("20260101", 4)

    def region(self, name: str) -> list[str]:
        """Map NAME and return the resolved region name and level."""
        result = self.workspace.raster("20260101", region=name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        return [payload["region"]["name"], payload["region"]["level"]]

    def rejection(self, name: str, code: str) -> dict:
        """Map NAME, expect rejection CODE, and return the error line."""
        result = self.workspace.raster("20260101", region=name)
        return assert_failed(
            self, self.workspace, result, name, code, ANY_OPTION
        )

    def test_user_maps_a_city_whose_short_name_is_also_a_province(self):
        """Given 双名省 and 双名市, when mapping 双名市, then get the city."""
        self.assertEqual(self.region("双名市"), ["双名市", "city"])

    def test_user_maps_the_province_of_that_name(self):
        """Given 双名省 and 双名市, when mapping 双名省, then get it."""
        self.assertEqual(self.region("双名省"), ["双名省", "province"])

    def test_user_is_told_a_short_name_is_ambiguous(self):
        """Given 双名省 and 双名市, when mapping 双名, then reject it."""
        error = self.rejection("双名", "region_ambiguous")
        self.assertEqual(error["details"]["candidates"], ["双名省", "双名市"])

    def test_user_maps_beijing_as_a_city(self):
        """Given 北京市 in both files, when mapping 北京, then a city."""
        self.assertEqual(self.region("北京"), ["北京市", "city"])

    def test_user_reads_a_chinese_command_line_as_typed(self):
        """Given 北京, when mapping, then the request keeps it unquoted."""
        self.region("北京")
        self.assertTrue(
            self.workspace.payload()["request"].startswith(
                "rsplot raster 北京 20260101 --product no2 "
            )
        )

    def test_user_maps_chongqing_as_a_province(self):
        """Given 重庆市 in both files, when mapping 重庆, then a province."""
        self.assertEqual(self.region("重庆"), ["重庆市", "province"])

    def test_user_maps_guangxi_by_its_short_name(self):
        """Given 广西壮族自治区, when mapping 广西, then get the province."""
        self.assertEqual(self.region("广西"), ["广西壮族自治区", "province"])

    def test_user_maps_xinjiang_by_its_short_name(self):
        """Given 新疆维吾尔自治区, when mapping 新疆, then the province."""
        self.assertEqual(self.region("新疆"), ["新疆维吾尔自治区", "province"])

    def test_user_maps_an_autonomous_prefecture_by_its_short_name(self):
        """Given 楚雄彝族自治州, when mapping 楚雄, then get the city."""
        self.assertEqual(self.region("楚雄"), ["楚雄彝族自治州", "city"])

    def test_user_maps_a_prefecture_named_for_two_groups(self):
        """Given 黔东南苗族侗族自治州, when mapping 黔东南, then get it."""
        self.assertEqual(
            self.region("黔东南"), ["黔东南苗族侗族自治州", "city"]
        )

    def test_user_is_told_hainan_is_ambiguous(self):
        """Given 海南省 and 海南藏族自治州, when mapping 海南, then reject."""
        error = self.rejection("海南", "region_ambiguous")
        self.assertEqual(
            error["details"]["candidates"], ["海南省", "海南藏族自治州"]
        )

    def test_user_maps_hainan_province_by_its_full_name(self):
        """Given both 海南 places, when mapping 海南省, then the province."""
        self.assertEqual(self.region("海南省"), ["海南省", "province"])

    def test_user_cannot_use_a_pinyin_name(self):
        """Given Chinese boundary names, when mapping pinyin, then reject."""
        self.rejection("shuangming", "region_not_found")


if __name__ == "__main__":
    unittest.main()
