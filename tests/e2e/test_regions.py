"""Region-naming user scenarios; see REGION_SCENARIOS.md."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from raster_support import schema_errors
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

    def rejection(self, name: str) -> dict:
        """Map NAME, expect exit 1, and return the error block."""
        result = self.workspace.raster("20260101", region=name)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.exists())
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        return payload["error"]

    def test_user_maps_a_city_whose_short_name_is_also_a_province(self):
        """Given 双名省 and 双名市, when mapping 双名市, then get the city."""
        self.assertEqual(self.region("双名市"), ["双名市", "city"])

    def test_user_maps_the_province_of_that_name(self):
        """Given 双名省 and 双名市, when mapping 双名省, then get it."""
        self.assertEqual(self.region("双名省"), ["双名省", "province"])

    def test_user_is_told_a_short_name_is_ambiguous(self):
        """Given 双名省 and 双名市, when mapping 双名, then reject it."""
        error = self.rejection("双名")
        self.assertEqual(
            [error["code"], error["details"]["candidates"]],
            ["region_ambiguous", ["双名省", "双名市"]],
        )

    def test_user_maps_beijing_as_a_city(self):
        """Given 北京市 in both files, when mapping 北京, then a city."""
        self.assertEqual(self.region("北京"), ["北京市", "city"])

    def test_user_maps_chongqing_as_a_province(self):
        """Given 重庆市 in both files, when mapping 重庆, then a province."""
        self.assertEqual(self.region("重庆"), ["重庆市", "province"])

    def test_user_cannot_use_a_pinyin_name(self):
        """Given Chinese boundary names, when mapping pinyin, then reject."""
        self.assertEqual(
            self.rejection("shuangming")["code"], "region_not_found"
        )


if __name__ == "__main__":
    unittest.main()
