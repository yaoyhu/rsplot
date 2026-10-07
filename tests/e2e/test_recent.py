"""Recent user scenarios; see RECENT_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from raster_support import assert_failed, schema_errors
from recent_support import RecentWorkspace


def series(payload: dict) -> dict:
    return payload["layers"][0]


def flags(payload: dict) -> dict[str, str]:
    return {
        item["code"]: item["severity"] for item in payload["quality"]["flags"]
    }


class RecentE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-recent-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = RecentWorkspace(Path(self.temp.name))

    def three_days(self):
        for day, value in (("20260101", 2), ("20260102", 4), ("20260103", 6)):
            self.workspace.write_swath(day, value)

    def station_days(self):
        for day, offset in (
            ("20260101", 0),
            ("20260102", 10),
            ("20260103", 20),
        ):
            self.workspace.write_station_day(day, offset)

    def assert_summary(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["command"], "recent")
        return payload

    def assert_rejected(self, result, message, code, option=None):
        return assert_failed(
            self, self.workspace, result, message, code, option
        )

    def table(self, payload):
        with open(series(payload)["data"], encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_user_summarizes_recent_satellite_days(self):
        """Given three days, when summarizing, then report daily means."""
        self.three_days()
        payload = self.assert_summary(self.workspace.raster_recent("20260103"))
        layer = series(payload)
        self.assertEqual([layer["id"], layer["kind"]], ["satellite", "series"])
        self.assertEqual(
            layer["time"],
            {
                "aggregation": "daily_series",
                "start": "20260101",
                "end": "20260103",
                "timezone": "UTC",
                "basis": "filename_start_date_utc",
            },
        )
        self.assertEqual(
            [layer["coverage"]["valid"], layer["coverage"]["total"]], [3, 3]
        )
        self.assertEqual(layer["stats"]["mean"], 4)
        self.assertEqual(
            [payload["artifacts"]["image"], payload["render"]], [None, None]
        )

    def test_user_loads_the_daily_table(self):
        """Given three days, when summarizing, then the CSV has each day."""
        self.three_days()
        rows = self.table(
            self.assert_summary(self.workspace.raster_recent("20260103"))
        )
        self.assertEqual(
            [(row["date"], row["value"], row["ok"]) for row in rows],
            [
                ("20260101", "2", "1"),
                ("20260102", "4", "1"),
                ("20260103", "6", "1"),
            ],
        )

    def test_user_sees_the_recent_trend(self):
        """Given rising days, when summarizing, then report the slope."""
        self.three_days()
        payload = self.assert_summary(self.workspace.raster_recent("20260103"))
        trend = series(payload)["temporal_summary"]["trend"]
        self.assertEqual(
            [trend["slope_per_day"], trend["direction"]], [2, "up"]
        )

    def test_user_is_warned_about_missing_days(self):
        """Given Jan 2 missing, when summarizing, then grade limited."""
        self.workspace.write_swath("20260101", 2)
        self.workspace.write_swath("20260103", 6)
        payload = self.assert_summary(self.workspace.raster_recent("20260103"))
        coverage = series(payload)["coverage"]
        self.assertEqual([coverage["valid"], coverage["total"]], [2, 3])
        self.assertEqual(flags(payload)["missing_days"], "warning")
        self.assertEqual(payload["quality"]["grade"], "limited")
        jan2 = self.table(payload)[1]
        self.assertEqual(jan2["ok"], "0")
        self.assertNotEqual(jan2["error"], "")

    def test_user_finds_every_input_file(self):
        """Given three swaths, when summarizing, then list all three."""
        self.three_days()
        payload = self.assert_summary(self.workspace.raster_recent("20260103"))
        self.assertEqual(series(payload)["source"]["files_total"], 3)

    def test_user_summarizes_recent_station_days(self):
        """Given two hours a day, when summarizing, then mean is 80."""
        self.station_days()
        payload = self.assert_summary(
            self.workspace.station_recent("20260103")
        )
        layer = series(payload)
        self.assertEqual(
            [
                layer["id"],
                layer["quantity"]["name"],
                layer["quantity"]["unit"],
            ],
            ["station", "NO2", "ug/m3"],
        )
        self.assertEqual(layer["stats"]["mean"], 80)
        self.assertEqual(
            layer["method"]["station_daily_value"], "mean_of_available_hours"
        )

    def test_user_reads_each_station_day(self):
        """Given two hours a day, when summarizing, then days are means."""
        self.station_days()
        rows = self.table(
            self.assert_summary(self.workspace.station_recent("20260103"))
        )
        self.assertEqual(
            [(row["value"], row["hours"]) for row in rows],
            [("70", "2"), ("80", "2"), ("90", "2")],
        )

    def test_user_summarizes_a_day_with_missing_hours(self):
        """Given only 13:00 on Jan 3, when summarizing, then use that hour."""
        self.workspace.write_station_day("20260101", 0)
        self.workspace.write_station_day("20260102", 10)
        self.workspace.write_station_day("20260103", 20, hours=(13,))
        rows = self.table(
            self.assert_summary(self.workspace.station_recent("20260103"))
        )
        self.assertEqual(
            [(row["value"], row["hours"]) for row in rows],
            [("70", "2"), ("80", "2"), ("80", "1")],
        )

    def test_user_is_warned_about_a_day_without_station_files(self):
        """Given no Jan 2 files, when summarizing, then that day is missing."""
        self.workspace.write_station_day("20260101", 0)
        self.workspace.write_station_day("20260103", 20)
        payload = self.assert_summary(
            self.workspace.station_recent("20260103")
        )
        self.assertEqual(series(payload)["coverage"]["valid"], 2)
        self.assertEqual(flags(payload)["missing_days"], "warning")
        self.assertEqual(
            [row["ok"] for row in self.table(payload)], ["1", "0", "1"]
        )

    def test_user_counts_daily_exceedances_against_the_daily_limit(self):
        """Given daily means 50-110, when summarizing, then one per day."""
        self.station_days()
        payload = self.assert_summary(
            self.workspace.station_recent("20260103")
        )
        self.assertEqual(series(payload)["method"]["daily_limit"], 80)
        self.assertEqual(
            [row["n_exceed"] for row in self.table(payload)],
            ["1", "1", "1"],
        )

    def test_user_is_told_no_station_files_exist(self):
        """Given no station files, when summarizing, then grade it."""
        payload = self.assert_summary(
            self.workspace.station_recent("20260103")
        )
        self.assertEqual(series(payload)["coverage"]["valid"], 0)
        self.assertEqual(flags(payload)["no_valid_data"], "critical")

    def test_user_is_told_nothing_was_found(self):
        """Given no swaths, when summarizing, then grade unreliable."""
        payload = self.assert_summary(self.workspace.raster_recent("20260103"))
        self.assertEqual(series(payload)["coverage"]["valid"], 0)
        self.assertEqual(flags(payload)["no_valid_data"], "critical")
        self.assertEqual(payload["quality"]["grade"], "unreliable")

    def test_user_rejects_an_invalid_end_date(self):
        """Given Feb 30, when summarizing, then reject the date."""
        self.three_days()
        self.assert_rejected(
            self.workspace.raster_recent("20260230"),
            "20260230",
            "invalid_time",
        )

    def test_user_rejects_an_unknown_source(self):
        """Given --source radar, when summarizing, then reject it."""
        self.three_days()
        self.assert_rejected(
            self.workspace.recent("20260103", source="radar"),
            "--source",
            "invalid_argument",
            "--source",
        )

    def test_user_rejects_gems_for_station_summaries(self):
        """Given station source, when asking for GEMS, then reject it."""
        self.station_days()
        self.assert_rejected(
            self.workspace.station_recent("20260103", "--sensor", "gems"),
            "--sensor",
            "invalid_argument",
            "--sensor",
        )

    def test_user_learns_the_station_variable_is_unknown(self):
        """Given --var XYZ, when summarizing stations, then reject it."""
        self.station_days()
        self.assert_rejected(
            self.workspace.recent(
                "20260103", "--var", "XYZ", source="station"
            ),
            "XYZ",
            "invalid_argument",
            "--var",
        )

    def test_user_learns_the_region_does_not_exist(self):
        """Given an unknown region, when summarizing, then report it."""
        self.three_days()
        result = self.workspace.invoke(
            "recent",
            "Atlantis",
            "20260103",
            "--days",
            "3",
            "--product",
            "no2",
            "--output",
            str(self.workspace.output),
        )
        self.assert_rejected(result, "Atlantis", "region_not_found")

    def test_user_names_the_product_for_satellite_summaries(self):
        """Given swaths, when omitting --product, then reject it."""
        self.three_days()
        self.assert_rejected(
            self.workspace.recent("20260103", "--res", "0.25"),
            "--product",
            "invalid_argument",
            "--product",
        )

    def test_user_names_the_variable_for_station_summaries(self):
        """Given station files, when omitting --var, then reject it."""
        self.station_days()
        self.assert_rejected(
            self.workspace.recent("20260103", source="station"),
            "--var",
            "invalid_argument",
            "--var",
        )


if __name__ == "__main__":
    unittest.main()
