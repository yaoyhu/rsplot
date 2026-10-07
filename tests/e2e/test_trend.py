"""Trend user scenarios; see TREND_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from PIL import Image
from raster_support import assert_failed, schema_errors
from trend_support import TrendWorkspace


def layer(payload: dict, layer_id: str) -> dict:
    return next(item for item in payload["layers"] if item["id"] == layer_id)


def flags(payload: dict) -> dict[str, str]:
    return {
        item["code"]: item["severity"] for item in payload["quality"]["flags"]
    }


class TrendE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-trend-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = TrendWorkspace(Path(self.temp.name))

    def assert_plot(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with Image.open(self.workspace.output) as image:
            self.assertEqual(image.format, "PNG")
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["command"], "trend")
        return payload

    def assert_rejected(self, result, message, code, option=None):
        return assert_failed(
            self, self.workspace, result, message, code, option
        )

    def series_file(self, payload, layer_id):
        return Dataset(layer(payload, layer_id)["data"])

    def test_user_plots_one_station_s_hours(self):
        """Given 24 hours, when trending one station, then summarize them."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(self.workspace.trend("S001A", "20260101"))
        station = layer(payload, "station")
        self.assertIsNone(payload["region"])
        self.assertEqual(
            [station["kind"], station["subject"]],
            ["series", {"station_id": "S001A"}],
        )
        self.assertEqual(
            [station["coverage"]["valid"], station["coverage"]["total"]],
            [24, 24],
        )
        self.assertEqual(station["stats"]["mean"], 21.5)
        self.assertEqual(
            station["time"],
            {
                "aggregation": "hourly_series",
                "start": "20260101",
                "end": "20260101",
                "timezone": "Asia/Shanghai",
                "basis": "station_hour",
            },
        )

    def test_user_loads_the_hourly_series(self):
        """Given 24 hours, when trending, then the NetCDF holds them."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(self.workspace.trend("S001A", "20260101"))
        with self.series_file(payload, "station") as dataset:
            values = dataset["value"][:].filled(np.nan)
            first_hour = str(dataset["time_cst"][0])
        self.assertEqual(values.shape, (1, 24))
        self.assertEqual([first_hour, float(values[0, 0])], ["2026010100", 10])

    def test_user_is_warned_about_missing_hours(self):
        """Given 12 of 24 hours, when trending, then grade limited."""
        self.workspace.write_hours("20260101", hours=range(12))
        payload = self.assert_plot(self.workspace.trend("S001A", "20260101"))
        coverage = layer(payload, "station")["coverage"]
        self.assertEqual([coverage["valid"], coverage["total"]], [12, 24])
        self.assertEqual(flags(payload)["missing_hours"], "warning")
        self.assertEqual(payload["quality"]["grade"], "limited")

    def test_user_overrides_the_exceedance_threshold(self):
        """Given --threshold 30, when trending, then count 3 hours above."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(
            self.workspace.trend("S001A", "20260101", "--threshold", "30")
        )
        exceedance = layer(payload, "station")["exceedance"]
        self.assertEqual(
            [
                exceedance["threshold"],
                exceedance["count"],
                exceedance["standard"],
            ],
            [30, 3, "--threshold"],
        )

    def test_user_plots_a_regional_trend(self):
        """Given two in-region stations, when trending, then average them."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(
            self.workspace.trend("FixtureCity", "20260101", "--region")
        )
        self.assertEqual(payload["region"]["name"], "FixtureCity")
        mean = layer(payload, "regional_mean")
        self.assertEqual(
            [mean["stats"]["mean"], mean["coverage"]["valid"]], [26.5, 24]
        )
        self.assertEqual(layer(payload, "station")["coverage"]["total"], 2)

    def test_user_loads_every_station_s_hours(self):
        """Given a regional trend, when loading data, then 2 x 24 values."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(
            self.workspace.trend("FixtureCity", "20260101", "--region")
        )
        with self.series_file(payload, "station") as dataset:
            shape = dataset["value"].shape
            first_mean = float(dataset["regional_mean"][0])
        self.assertEqual([shape, first_mean], [(2, 24), 15])

    def test_user_highlights_a_focus_station(self):
        """Given --focus-station, when trending, then record the highlight."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(
            self.workspace.trend(
                "FixtureCity",
                "20260101",
                "--region",
                "--focus-station",
                "S002A",
            )
        )
        self.assertEqual(
            payload["render"]["layers"]["station"]["focus_station_ids"],
            ["S002A"],
        )

    def test_user_is_warned_about_few_stations(self):
        """Given two stations, when trending a region, then grade limited."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(
            self.workspace.trend("FixtureCity", "20260101", "--region")
        )
        self.assertEqual(flags(payload)["few_stations"], "warning")
        self.assertEqual(payload["quality"]["grade"], "limited")

    def test_user_learns_a_focus_station_is_outside_the_region(self):
        """Given an outside focus station, when trending, then reject it."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend(
                "FixtureCity",
                "20260101",
                "--region",
                "--focus-station",
                "S003A",
            ),
            "S003A",
            "invalid_argument",
            "--focus-station",
        )

    def test_user_learns_the_station_does_not_exist(self):
        """Given an unknown station, when trending, then report it."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend("ZZZ9A", "20260101"),
            "ZZZ9A",
            "region_not_found",
        )

    def test_user_learns_the_region_does_not_exist(self):
        """Given an unknown region, when trending, then report it."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend("Atlantis", "20260101", "--region"),
            "Atlantis",
            "region_not_found",
        )

    def test_user_trends_one_region_at_a_time(self):
        """Given two regions, when trending, then ask for one per run."""
        self.workspace.write_hours("20260101")
        error = self.assert_rejected(
            self.workspace.trend(
                "FixtureCity，EastCity", "20260101", "--region"
            ),
            "分别运行",
            "invalid_argument",
        )
        self.assertEqual(
            error["details"], {"regions": ["FixtureCity", "EastCity"]}
        )

    def test_user_learns_no_files_exist(self):
        """Given no hourly files, when trending, then report missing data."""
        self.assert_rejected(
            self.workspace.trend("S001A", "20260101"),
            "20260101",
            "data_not_found",
        )

    def test_user_rejects_an_invalid_date(self):
        """Given Feb 30, when trending, then reject the date."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend("S001A", "20260230"),
            "20260230",
            "invalid_time",
        )

    def test_user_rejects_a_regional_view_for_one_station(self):
        """Given one station, when asking for --view mean, then reject it."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend("S001A", "20260101", "--view", "mean"),
            "--view",
            "invalid_argument",
            "--view",
        )

    def test_user_names_the_window_for_a_single_date(self):
        """Given one end date, when omitting --days, then reject it."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend("S001A", "20260101", days=None),
            "--days",
            "invalid_argument",
            "--days",
        )

    def test_user_plots_an_explicit_date_range(self):
        """Given a date range, when omitting --days, then plot the range."""
        self.workspace.write_hours("20260101")
        payload = self.assert_plot(
            self.workspace.trend("S001A", "20260101-20260101", days=None)
        )
        self.assertEqual(
            [payload["layers"][0]["time"][k] for k in ("start", "end")],
            ["20260101", "20260101"],
        )

    def test_user_cannot_combine_a_date_range_with_days(self):
        """Given a date range, when adding --days, then reject it."""
        self.workspace.write_hours("20260101")
        self.assert_rejected(
            self.workspace.trend("S001A", "20260101-20260101"),
            "--days",
            "invalid_argument",
            "--days",
        )


if __name__ == "__main__":
    unittest.main()
