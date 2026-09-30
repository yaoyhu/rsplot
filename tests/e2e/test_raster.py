"""Raster user scenarios; see RASTER_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from raster_support import RasterWorkspace

SUPPORT_KEYS = ("valid_region_pixels", "total_region_pixels", "coverage_pct")


class RasterE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-raster-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = RasterWorkspace(Path(self.temp.name))

    def assert_plot(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with Image.open(self.workspace.output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 100)
            self.assertGreater(image.height, 100)
            rgb = np.asarray(image.convert("RGB"), dtype=int)
            self.assertGreater(np.count_nonzero(np.ptp(rgb, axis=2) > 30), 500)
        payload = self.workspace.payload()
        self.assertEqual(payload["command"], "raster")
        self.assertEqual(payload["image"], str(self.workspace.output))
        self.assertEqual(payload["sidecar"], str(self.workspace.sidecar))
        return payload

    def assert_rejected(self, result, message):
        self.assertNotEqual(
            result.returncode, 0, result.stdout + result.stderr
        )
        self.assertIn(message, result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.exists())
        self.assertFalse(self.workspace.sidecar.exists())

    def two_days(self):
        self.workspace.write_swath("20260101", 2, orbit=1)
        self.workspace.write_swath("20260101", 4, orbit=2)
        self.workspace.write_swath("20260102", 9)

    def test_user_understands_raster_dates(self):
        """Given CLI, when requesting help, then date semantics are explicit."""
        result = self.workspace.invoke("raster", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("TROPOMI: YYYYMMDD", result.stdout)
        self.assertIn("轨道", result.stdout)
        self.assertIn("等权", result.stdout)
        self.assertIn("GEMS", result.stdout)
        self.assertNotIn("弹窗", result.stdout)

    def test_user_plots_one_tropomi_day(self):
        """Given multiple days/orbits, when selecting one day, then mean is 3."""
        self.two_days()
        payload = self.assert_plot(self.workspace.raster("20260101"))
        self.assertEqual(payload["date"], "20260101")
        self.assertNotIn("window", payload)
        self.assertEqual(payload["swath"]["n_files"], 2)
        self.assertEqual(payload["stats"]["mean"], 3)

    def test_user_reads_grouped_products(self):
        """Given PRODUCT-group data, when plotting, then mean is 4."""
        self.workspace.write_swath("20260101", 4, grouped=True)
        payload = self.assert_plot(self.workspace.raster("20260101"))
        self.assertEqual(payload["stats"]["mean"], 4)

    def test_user_plots_hcho(self):
        """Given HCHO columns, when plotting HCHO, then units and mean agree."""
        self.workspace.write_swath("20260101", 6, product="hcho")
        payload = self.assert_plot(
            self.workspace.raster("20260101", "-p", "hcho")
        )
        self.assertEqual(payload["stats"]["mean"], 6)
        self.assertIn("HCHO VCD", payload["unit"])

    def test_user_plots_total_ozone(self):
        """Given total ozone, when plotting O3, then mean is 300 DU."""
        self.workspace.write_swath("20260101", 300, product="o3")
        payload = self.assert_plot(
            self.workspace.raster("20260101", "-p", "o3")
        )
        self.assertEqual(payload["stats"]["mean"], 300)
        self.assertIn("DU", payload["unit"])

    def test_user_plots_profile_ozone(self):
        """Given profile ozone, when plotting O3PR, then mean is 30 DU."""
        self.workspace.write_swath("20260101", 30, product="o3pr")
        payload = self.assert_plot(
            self.workspace.raster("20260101", "-p", "o3pr")
        )
        self.assertEqual(payload["stats"]["mean"], 30)
        self.assertIn("DU", payload["unit"])

    def test_user_averages_days_equally(self):
        """Given unequal orbit counts, when averaging two days, then mean is 6."""
        self.two_days()
        payload = self.assert_plot(
            self.workspace.raster("20260102", "--days", "2")
        )
        self.assertEqual(payload["stats"]["mean"], 6)
        self.assertEqual(payload["window"]["start"], "20260101")
        self.assertEqual(payload["window"]["end"], "20260102")
        self.assertEqual(payload["window"]["n_min"], 2)

    def test_user_includes_both_range_endpoints(self):
        """Given two days, when selecting a closed range, then both contribute."""
        self.two_days()
        payload = self.assert_plot(self.workspace.raster("20260101-20260102"))
        self.assertEqual(payload["window"]["n_days_found"], 2)
        self.assertEqual(payload["stats"]["mean"], 6)

    def test_user_requests_a_one_day_window(self):
        """Given Jan 1 orbits, when using --days 1, then n-min is clamped to 1."""
        self.two_days()
        payload = self.assert_plot(
            self.workspace.raster("20260101", "--days", "1")
        )
        self.assertEqual(payload["window"]["n_min"], 1)
        self.assertEqual(payload["window"]["n_days_requested"], 1)
        self.assertEqual(payload["stats"]["mean"], 3)

    def test_user_distinguishes_gap_filling(self):
        """Given sparse input, when selecting a window, then holes remain."""
        self.workspace.write_swath("20260101", 4, sparse=True)
        daily = self.assert_plot(self.workspace.raster("20260101"))
        window = self.assert_plot(
            self.workspace.raster("20260101", "--days", "1")
        )
        self.assertEqual(window["stats"]["valid_region_pixels"], 1)
        self.assertGreater(daily["stats"]["valid_region_pixels"], 1)

    def test_user_keeps_observed_support_while_smoothing(self):
        """Given one observed cell, when smoothing, then support is unchanged."""
        self.workspace.write_swath("20260101", 4, sparse=True)
        plain = self.assert_plot(self.workspace.raster("20260101"))
        smoothed = self.assert_plot(
            self.workspace.raster("20260101", "--smooth", "1.5")
        )
        self.assertEqual(
            [plain["stats"][key] for key in SUPPORT_KEYS],
            [smoothed["stats"][key] for key in SUPPORT_KEYS],
        )

    def test_user_sees_missing_day_diagnostics(self):
        """Given Jan 1 missing, when permitting one valid day, then report it."""
        self.workspace.write_swath("20260102", 9)
        payload = self.assert_plot(
            self.workspace.raster("20260102", "--days", "2", "--n-min", "1")
        )
        self.assertEqual(payload["stats"]["mean"], 9)
        self.assertEqual(payload["window"]["n_days_found"], 1)
        self.assertIn("20260101", payload["window"]["dates_failed"])

    def test_user_enforces_minimum_valid_days(self):
        """Given one missing day, when requiring both, then no map is emitted."""
        self.workspace.write_swath("20260102", 9)
        self.assert_rejected(
            self.workspace.raster("20260102", "--days", "2"), "--n-min"
        )

    def test_user_filters_qa_and_clouds(self):
        """Given rejected outliers, when filtering, then only value 2 remains."""
        self.workspace.write_swath("20260101", 2, cloud=0.5)
        self.workspace.write_swath("20260101", 100, orbit=2, qa=0.5)
        self.workspace.write_swath("20260101", 100, orbit=3, cloud=0.6)
        payload = self.assert_plot(
            self.workspace.raster("20260101", "--qa", "0.5", "--cf", "0.5")
        )
        self.assertEqual(payload["stats"]["mean"], 2)
        self.assertEqual(payload["swath"]["n_pixels"], 16)

    def test_user_sees_partial_unreadable_inputs(self):
        """Given one corrupt orbit, when plotting, then report partial input."""
        self.workspace.write_swath("20260101", 4)
        bad_file = self.workspace.write_swath("20260101", 100, orbit=2)
        bad_file.write_bytes(b"not a NetCDF file")
        payload = self.assert_plot(self.workspace.raster("20260101"))
        self.assertEqual(payload["stats"]["mean"], 4)
        self.assertEqual(payload["swath"]["n_broken"], 1)

    def test_user_selects_multiple_regions(self):
        """Given adjacent regions, when selecting both, then retain members."""
        self.workspace.write_swath("20260101", 4)
        payload = self.assert_plot(
            self.workspace.raster("20260101", region="FixtureCity,EastCity")
        )
        self.assertEqual(len(payload["region"]["members"]), 2)
        self.assertEqual(len(payload["member_stats"]), 2)

    def test_user_selects_nrti_processing(self):
        """Given overlapping NRTI versions, when plotting, then use latest."""
        self.workspace.write_swath(
            "20260101", 2, nrti=True, production="120000"
        )
        self.workspace.write_swath(
            "20260101", 4, nrti=True, production="130000"
        )
        payload = self.assert_plot(
            self.workspace.raster("20260101", "--processing", "nrti")
        )
        self.assertEqual(payload["stats"]["mean"], 4)
        self.assertEqual(payload["swath"]["n_duplicates_removed"], 16)
        self.assertEqual(
            payload["swath"]["date_basis"], "filename_start_date_utc"
        )

    def test_user_rejects_competing_window_selectors(self):
        """Given a range, when also supplying --days, then reject ambiguity."""
        self.two_days()
        self.assert_rejected(
            self.workspace.raster("20260101-20260102", "--days", "7"), "--days"
        )

    def test_user_rejects_hourly_tropomi_input(self):
        """Given TROPOMI, when supplying an hour, then require a date."""
        self.assert_rejected(self.workspace.raster("2026010112"), "YYYYMMDD")

    def test_user_rejects_invalid_calendar_dates(self):
        """Given Feb 30, when plotting, then reject the nonexistent date."""
        self.assert_rejected(self.workspace.raster("20260230"), "日期无效")

    def test_user_rejects_reversed_ranges(self):
        """Given reversed dates, when plotting, then reject the range."""
        self.assert_rejected(
            self.workspace.raster("20260102-20260101"), "颠倒"
        )

    def test_user_rejects_zero_day_windows(self):
        """Given --days 0, when plotting, then require a positive window."""
        self.assert_rejected(
            self.workspace.raster("20260101", "--days", "0"), "--days"
        )

    def test_user_rejects_n_min_outside_a_window(self):
        """Given a single date, when supplying --n-min, then require a window."""
        self.assert_rejected(
            self.workspace.raster("20260101", "--n-min", "1"), "--n-min"
        )

    def test_user_rejects_impossible_n_min(self):
        """Given two days, when requiring three valid days, then reject."""
        self.assert_rejected(
            self.workspace.raster("20260102", "--days", "2", "--n-min", "3"),
            "大于窗口天数",
        )

    def test_user_receives_useful_single_day_coverage_guidance(self):
        """Given exterior data, when plotting one day, then explain that day."""
        self.workspace.write_swath("20260101", 4, outside=True)
        result = self.workspace.raster("20260101")
        self.assert_rejected(result, "20260101")
        self.assertNotIn("窗口均值", result.stdout)
        self.assertNotIn("--n-min", result.stdout)

    def test_user_selects_a_gems_scan_in_china_time(self):
        """Given UTC scans, when selecting noon China time, then mean is 2."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        payload = self.assert_plot(
            self.workspace.raster("202601011200", "--sensor", "gems")
        )
        self.assertEqual(payload["stats"]["mean"], 2)
        self.assertEqual(payload["swath"]["aggregation"], "scan")
        self.assertEqual(payload["swath"]["n_scans_found"], 1)
        self.assertEqual(payload["input_timezone"], "Asia/Shanghai")

    def test_user_averages_gems_scans_equally(self):
        """Given two scans, when requesting a daily mean, then mean is 4."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        payload = self.assert_plot(
            self.workspace.raster("20260101", "--sensor", "gems")
        )
        self.assertEqual(payload["stats"]["mean"], 4)
        self.assertEqual(payload["swath"]["n_scans_valid"], 2)

    def test_user_averages_gems_days_equally(self):
        """Given unequal scan counts, when averaging two days, then mean is 7."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        self.workspace.write_gems_scan("202601020400", 10)
        payload = self.assert_plot(
            self.workspace.raster(
                "20260102", "--sensor", "gems", "--days", "2"
            )
        )
        self.assertEqual(payload["stats"]["mean"], 7)
        self.assertEqual(
            payload["window"]["aggregation"],
            "equal_day_mean_of_equal_scan_means",
        )

    def test_user_preserves_gems_statistics_while_styling(self):
        """Given one scan, when changing display settings, then stats persist."""
        self.workspace.write_gems_scan("202601010400", 6)
        plain = self.assert_plot(
            self.workspace.raster("202601011200", "--sensor", "gems")
        )
        styled = self.assert_plot(
            self.workspace.raster(
                "202601011200",
                "--sensor",
                "gems",
                "--smooth",
                "1",
                "--dpi",
                "90",
            )
        )
        self.assertEqual(plain["stats"], styled["stats"])

    def test_user_rejects_tropomi_qa_for_gems(self):
        """Given GEMS, when using TROPOMI QA, then reject the option."""
        self.assert_rejected(
            self.workspace.raster(
                "20260101", "--sensor", "gems", "--qa", "0.5"
            ),
            "--qa",
        )

    def test_user_rejects_a_scan_window(self):
        """Given an exact scan, when requesting a window, then reject."""
        self.assert_rejected(
            self.workspace.raster(
                "202601011200", "--sensor", "gems", "--days", "1"
            ),
            "单次扫描",
        )

    def test_user_rejects_a_scan_valid_day_threshold(self):
        """Given an exact scan, when requesting valid-day filtering, then reject."""
        self.assert_rejected(
            self.workspace.raster(
                "202601011200", "--sensor", "gems", "--n-min", "1"
            ),
            "单次扫描",
        )


if __name__ == "__main__":
    unittest.main()
