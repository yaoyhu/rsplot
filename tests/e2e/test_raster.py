"""Raster user scenarios; see RASTER_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from PIL import Image
from raster_support import RasterWorkspace, schema_errors

SUPPORT_KEYS = ("valid", "total", "fraction")


def satellite(payload: dict) -> dict:
    return payload["layers"][0]


def flag_codes(payload: dict) -> list[str]:
    return [item["code"] for item in payload["quality"]["flags"]]


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
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["command"], "raster")
        self.assertEqual(
            payload["artifacts"]["image"], str(self.workspace.output)
        )
        self.assertEqual(
            payload["artifacts"]["sidecar"], str(self.workspace.sidecar)
        )
        return payload

    def assert_rejected(self, result, message, code):
        self.assertNotEqual(
            result.returncode, 0, result.stdout + result.stderr
        )
        self.assertIn(message, result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.exists())
        self.assertEqual(
            sorted(p.name for p in self.workspace.output.parent.iterdir()),
            [self.workspace.sidecar.name],
        )
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], code)
        return payload

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
        layer = satellite(self.assert_plot(self.workspace.raster("20260101")))
        self.assertEqual(
            layer["time"],
            {
                "aggregation": "daily",
                "start": "20260101",
                "end": "20260101",
                "timezone": "UTC",
                "basis": "filename_start_date_utc",
            },
        )
        self.assertEqual(layer["source"]["files_total"], 2)
        self.assertEqual(layer["stats"]["mean"], 3)

    def test_user_finds_every_input_file(self):
        """Given two orbits, when plotting, then both files are listed."""
        first = self.workspace.write_swath("20260101", 2, orbit=1)
        second = self.workspace.write_swath("20260101", 4, orbit=2)
        layer = satellite(self.assert_plot(self.workspace.raster("20260101")))
        self.assertEqual(
            layer["source"]["data_root"], str(self.workspace.data)
        )
        self.assertEqual(
            layer["source"]["files"], sorted([first.name, second.name])
        )
        self.assertEqual(layer["source"]["sensor"], "tropomi")
        self.assertEqual(layer["source"]["processing"], "offl")

    def test_user_loads_the_statistical_grid(self):
        """Given one day, when plotting, then the data file holds the stats."""
        self.two_days()
        payload = self.assert_plot(self.workspace.raster("20260101"))
        layer = satellite(payload)
        entry = payload["artifacts"]["data"][0]
        self.assertEqual(entry["path"], layer["data"])
        self.assertGreater(entry["bytes"], 0)
        with Dataset(layer["data"]) as dataset:
            values = dataset["value"][:].filled(np.nan)
            counted = dataset["counted"][:].astype(bool)
        self.assertEqual(round(float(np.nanmean(values[counted])), 2), 3.0)
        self.assertEqual(int(counted.sum()), layer["coverage"]["total"])

    def test_user_reads_grouped_products(self):
        """Given PRODUCT-group data, when plotting, then mean is 4."""
        self.workspace.write_swath("20260101", 4, grouped=True)
        payload = self.assert_plot(self.workspace.raster("20260101"))
        self.assertEqual(satellite(payload)["stats"]["mean"], 4)

    def test_user_plots_hcho(self):
        """Given HCHO columns, when plotting HCHO, then units and mean agree."""
        self.workspace.write_swath("20260101", 6, product="hcho")
        layer = satellite(
            self.assert_plot(self.workspace.raster("20260101", "-p", "hcho"))
        )
        self.assertEqual(layer["stats"]["mean"], 6)
        self.assertEqual(
            layer["quantity"],
            {
                "name": "tropospheric_hcho_column",
                "unit": "molec/cm2",
                "scale": 1e15,
                "label": "HCHO VCD (x10^15 molec/cm2)",
            },
        )

    def test_user_plots_total_ozone(self):
        """Given total ozone, when plotting O3, then mean is 300 DU."""
        self.workspace.write_swath("20260101", 300, product="o3")
        layer = satellite(
            self.assert_plot(self.workspace.raster("20260101", "-p", "o3"))
        )
        self.assertEqual(layer["stats"]["mean"], 300)
        self.assertEqual(layer["quantity"]["unit"], "DU")
        self.assertEqual(layer["quantity"]["scale"], 1)

    def test_user_plots_profile_ozone(self):
        """Given profile ozone, when plotting O3PR, then mean is 30 DU."""
        self.workspace.write_swath("20260101", 30, product="o3pr")
        layer = satellite(
            self.assert_plot(self.workspace.raster("20260101", "-p", "o3pr"))
        )
        self.assertEqual(layer["stats"]["mean"], 30)
        self.assertEqual(layer["quantity"]["unit"], "DU")

    def test_user_averages_days_equally(self):
        """Given unequal orbit counts, when averaging two days, then mean is 6."""
        self.two_days()
        layer = satellite(
            self.assert_plot(self.workspace.raster("20260102", "--days", "2"))
        )
        self.assertEqual(layer["stats"]["mean"], 6)
        self.assertEqual(layer["time"]["start"], "20260101")
        self.assertEqual(layer["time"]["end"], "20260102")
        self.assertEqual(layer["time"]["days"]["n_min"], 2)
        self.assertEqual(layer["method"]["day_weighting"], "equal_days")

    def test_user_includes_both_range_endpoints(self):
        """Given two days, when selecting a closed range, then both contribute."""
        self.two_days()
        layer = satellite(
            self.assert_plot(self.workspace.raster("20260101-20260102"))
        )
        self.assertEqual(layer["time"]["days"]["found"], 2)
        self.assertEqual(layer["stats"]["mean"], 6)

    def test_user_requests_a_one_day_window(self):
        """Given Jan 1 orbits, when using --days 1, then n-min is clamped to 1."""
        self.two_days()
        layer = satellite(
            self.assert_plot(self.workspace.raster("20260101", "--days", "1"))
        )
        self.assertEqual(layer["time"]["days"]["n_min"], 1)
        self.assertEqual(layer["time"]["days"]["requested"], 1)
        self.assertEqual(layer["stats"]["mean"], 3)

    def test_user_distinguishes_gap_filling(self):
        """Given sparse input, when selecting a window, then holes remain."""
        self.workspace.write_swath("20260101", 4, sparse=True)
        daily = satellite(self.assert_plot(self.workspace.raster("20260101")))
        window = satellite(
            self.assert_plot(self.workspace.raster("20260101", "--days", "1"))
        )
        self.assertEqual(window["coverage"]["valid"], 1)
        self.assertGreater(daily["coverage"]["valid"], 1)

    def test_user_keeps_observed_support_while_smoothing(self):
        """Given one observed cell, when smoothing, then support is unchanged."""
        self.workspace.write_swath("20260101", 4, sparse=True)
        plain = satellite(self.assert_plot(self.workspace.raster("20260101")))
        smoothed = satellite(
            self.assert_plot(
                self.workspace.raster("20260101", "--smooth", "1.5")
            )
        )
        self.assertEqual(
            [plain["coverage"][key] for key in SUPPORT_KEYS],
            [smoothed["coverage"][key] for key in SUPPORT_KEYS],
        )

    def test_user_learns_values_were_smoothed(self):
        """Given smoothing, when plotting, then an info flag explains it."""
        self.workspace.write_swath("20260101", 4)
        payload = self.assert_plot(
            self.workspace.raster("20260101", "--smooth", "1")
        )
        self.assertEqual(flag_codes(payload), ["values_smoothed"])
        self.assertEqual(payload["quality"]["grade"], "good")

    def test_user_is_warned_when_coverage_is_too_low(self):
        """Given one valid cell of 16, when plotting, then grade unreliable."""
        self.workspace.write_swath("20260101", 4, sparse=True)
        payload = self.assert_plot(
            self.workspace.raster("20260101", "--days", "1")
        )
        self.assertEqual(payload["quality"]["grade"], "unreliable")
        self.assertIn("very_low_coverage", flag_codes(payload))

    def test_user_sees_missing_day_diagnostics(self):
        """Given Jan 1 missing, when permitting one valid day, then report it."""
        self.workspace.write_swath("20260102", 9)
        layer = satellite(
            self.assert_plot(
                self.workspace.raster(
                    "20260102", "--days", "2", "--n-min", "1"
                )
            )
        )
        self.assertEqual(layer["stats"]["mean"], 9)
        self.assertEqual(layer["time"]["days"]["found"], 1)
        self.assertIn("20260101", layer["time"]["days"]["failed"])

    def test_user_is_warned_about_missing_days(self):
        """Given Jan 1 missing, when averaging two days, then grade limited."""
        self.workspace.write_swath("20260102", 9)
        payload = self.assert_plot(
            self.workspace.raster("20260102", "--days", "2", "--n-min", "1")
        )
        self.assertEqual(flag_codes(payload), ["missing_days"])
        self.assertEqual(payload["quality"]["grade"], "limited")

    def test_user_enforces_minimum_valid_days(self):
        """Given one missing day, when requiring both, then no map is emitted."""
        self.workspace.write_swath("20260102", 9)
        self.assert_rejected(
            self.workspace.raster("20260102", "--days", "2"),
            "--n-min",
            "no_valid_data",
        )

    def test_user_filters_qa_and_clouds(self):
        """Given rejected outliers, when filtering, then only value 2 remains."""
        self.workspace.write_swath("20260101", 2, cloud=0.5)
        self.workspace.write_swath("20260101", 100, orbit=2, qa=0.5)
        self.workspace.write_swath("20260101", 100, orbit=3, cloud=0.6)
        layer = satellite(
            self.assert_plot(
                self.workspace.raster("20260101", "--qa", "0.5", "--cf", "0.5")
            )
        )
        self.assertEqual(layer["stats"]["mean"], 2)
        self.assertEqual(layer["method"]["pixels_used"], 16)
        self.assertEqual(layer["method"]["qa_min_exclusive"], 0.5)
        self.assertEqual(layer["method"]["cloud_fraction_max"], 0.5)

    def test_user_sees_partial_unreadable_inputs(self):
        """Given one corrupt orbit, when plotting, then report partial input."""
        self.workspace.write_swath("20260101", 4)
        bad_file = self.workspace.write_swath("20260101", 100, orbit=2)
        bad_file.write_bytes(b"not a NetCDF file")
        layer = satellite(self.assert_plot(self.workspace.raster("20260101")))
        self.assertEqual(layer["stats"]["mean"], 4)
        self.assertEqual(
            list(layer["source"]["failed_files"]), [bad_file.name]
        )

    def test_user_is_warned_about_unreadable_inputs(self):
        """Given one corrupt orbit, when plotting, then grade limited."""
        self.workspace.write_swath("20260101", 4)
        bad_file = self.workspace.write_swath("20260101", 100, orbit=2)
        bad_file.write_bytes(b"not a NetCDF file")
        payload = self.assert_plot(self.workspace.raster("20260101"))
        self.assertEqual(flag_codes(payload), ["failed_files"])
        self.assertEqual(payload["quality"]["grade"], "limited")

    def test_user_reproduces_a_request(self):
        """Given defaults from CLI and config, when plotting, then record them."""
        self.workspace.write_swath("20260101", 4)
        payload = self.assert_plot(self.workspace.raster("20260101"))
        resolved = payload["request"]["resolved"]
        self.assertEqual(
            payload["request"]["argv"][:3],
            ["raster", "FixtureCity", "20260101"],
        )
        self.assertEqual(resolved["res"], {"value": 0.25, "source": "cli"})
        self.assertEqual(resolved["qa"], {"value": 0.5, "source": "config"})
        self.assertEqual(
            resolved["sensor"], {"value": "tropomi", "source": "built_in"}
        )

    def test_user_selects_multiple_regions(self):
        """Given adjacent regions, when selecting both, then retain members."""
        self.workspace.write_swath("20260101", 4)
        payload = self.assert_plot(
            self.workspace.raster("20260101", region="FixtureCity,EastCity")
        )
        self.assertEqual(len(payload["region"]["members"]), 2)
        self.assertEqual(len(satellite(payload)["by_member"]), 2)

    def test_user_selects_nrti_processing(self):
        """Given overlapping NRTI versions, when plotting, then use latest."""
        self.workspace.write_swath(
            "20260101", 2, nrti=True, production="120000"
        )
        self.workspace.write_swath(
            "20260101", 4, nrti=True, production="130000"
        )
        layer = satellite(
            self.assert_plot(
                self.workspace.raster("20260101", "--processing", "nrti")
            )
        )
        self.assertEqual(layer["stats"]["mean"], 4)
        self.assertEqual(layer["source"]["processing"], "nrti")
        self.assertEqual(layer["method"]["duplicates_removed"], 16)
        self.assertEqual(layer["time"]["basis"], "filename_start_date_utc")

    def test_user_rejects_competing_window_selectors(self):
        """Given a range, when also supplying --days, then reject ambiguity."""
        self.two_days()
        payload = self.assert_rejected(
            self.workspace.raster("20260101-20260102", "--days", "7"),
            "--days",
            "invalid_argument",
        )
        self.assertEqual(payload["error"]["option"], "--days")

    def test_user_rejects_hourly_tropomi_input(self):
        """Given TROPOMI, when supplying an hour, then require a date."""
        self.assert_rejected(
            self.workspace.raster("2026010112"), "YYYYMMDD", "invalid_time"
        )

    def test_user_rejects_invalid_calendar_dates(self):
        """Given Feb 30, when plotting, then reject the nonexistent date."""
        self.assert_rejected(
            self.workspace.raster("20260230"), "日期无效", "invalid_time"
        )

    def test_user_rejects_reversed_ranges(self):
        """Given reversed dates, when plotting, then reject the range."""
        self.assert_rejected(
            self.workspace.raster("20260102-20260101"), "颠倒", "invalid_time"
        )

    def test_user_rejects_zero_day_windows(self):
        """Given --days 0, when plotting, then require a positive window."""
        self.assert_rejected(
            self.workspace.raster("20260101", "--days", "0"),
            "--days",
            "invalid_argument",
        )

    def test_user_rejects_n_min_outside_a_window(self):
        """Given a single date, when supplying --n-min, then require a window."""
        self.assert_rejected(
            self.workspace.raster("20260101", "--n-min", "1"),
            "--n-min",
            "invalid_argument",
        )

    def test_user_rejects_impossible_n_min(self):
        """Given two days, when requiring three valid days, then reject."""
        self.assert_rejected(
            self.workspace.raster("20260102", "--days", "2", "--n-min", "3"),
            "大于窗口天数",
            "invalid_argument",
        )

    def test_user_receives_useful_single_day_coverage_guidance(self):
        """Given exterior data, when plotting one day, then explain that day."""
        self.workspace.write_swath("20260101", 4, outside=True)
        result = self.workspace.raster("20260101")
        payload = self.assert_rejected(result, "20260101", "no_valid_data")
        self.assertNotIn("窗口均值", payload["error"]["message"])
        self.assertNotIn("--n-min", payload["error"]["message"])

    def test_user_learns_a_region_does_not_exist(self):
        """Given an unknown region, when plotting, then report region_not_found."""
        self.workspace.write_swath("20260101", 4)
        self.assert_rejected(
            self.workspace.raster("20260101", region="Atlantis"),
            "Atlantis",
            "region_not_found",
        )

    def test_user_learns_data_is_missing(self):
        """Given no files for the day, when plotting, then data_not_found."""
        self.workspace.write_swath("20260102", 4)
        self.assert_rejected(
            self.workspace.raster("20260101"), "20260101", "data_not_found"
        )

    def test_user_selects_a_gems_scan_in_china_time(self):
        """Given UTC scans, when selecting noon China time, then mean is 2."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        layer = satellite(
            self.assert_plot(
                self.workspace.raster("202601011200", "--sensor", "gems")
            )
        )
        self.assertEqual(layer["stats"]["mean"], 2)
        self.assertEqual(
            layer["time"],
            {
                "aggregation": "scan",
                "at": "202601011200",
                "timezone": "Asia/Shanghai",
                "basis": "nominal_scan_time",
                "archive_time_utc": "202601010400",
            },
        )
        self.assertEqual(layer["method"]["scans_found"], 1)

    def test_user_averages_gems_scans_equally(self):
        """Given two scans, when requesting a daily mean, then mean is 4."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        layer = satellite(
            self.assert_plot(
                self.workspace.raster("20260101", "--sensor", "gems")
            )
        )
        self.assertEqual(layer["stats"]["mean"], 4)
        self.assertEqual(layer["method"]["scans_valid"], 2)
        self.assertEqual(layer["time"]["aggregation"], "daily_scan_mean")

    def test_user_averages_gems_days_equally(self):
        """Given unequal scan counts, when averaging two days, then mean is 7."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        self.workspace.write_gems_scan("202601020400", 10)
        layer = satellite(
            self.assert_plot(
                self.workspace.raster(
                    "20260102", "--sensor", "gems", "--days", "2"
                )
            )
        )
        self.assertEqual(layer["stats"]["mean"], 7)
        self.assertEqual(layer["method"]["scan_weighting"], "equal_scans")
        self.assertEqual(layer["method"]["day_weighting"], "equal_days")
        self.assertEqual(layer["time"]["basis"], "asia_shanghai_calendar_day")

    def test_user_preserves_gems_statistics_while_styling(self):
        """Given one scan, when changing display settings, then stats persist."""
        self.workspace.write_gems_scan("202601010400", 6)
        plain = satellite(
            self.assert_plot(
                self.workspace.raster("202601011200", "--sensor", "gems")
            )
        )
        styled = satellite(
            self.assert_plot(
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
        )
        self.assertEqual(plain["stats"], styled["stats"])

    def test_user_rejects_tropomi_qa_for_gems(self):
        """Given GEMS, when using TROPOMI QA, then reject the option."""
        self.assert_rejected(
            self.workspace.raster(
                "20260101", "--sensor", "gems", "--qa", "0.5"
            ),
            "--qa",
            "invalid_argument",
        )

    def test_user_rejects_a_scan_window(self):
        """Given an exact scan, when requesting a window, then reject."""
        self.assert_rejected(
            self.workspace.raster(
                "202601011200", "--sensor", "gems", "--days", "1"
            ),
            "单次扫描",
            "invalid_argument",
        )

    def test_user_rejects_a_scan_valid_day_threshold(self):
        """Given an exact scan, when requesting valid-day filtering, then reject."""
        self.assert_rejected(
            self.workspace.raster(
                "202601011200", "--sensor", "gems", "--n-min", "1"
            ),
            "单次扫描",
            "invalid_argument",
        )


if __name__ == "__main__":
    unittest.main()
