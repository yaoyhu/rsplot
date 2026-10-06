"""Station user scenarios; see STATION_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from raster_support import schema_errors
from station_support import StationWorkspace


def station(payload: dict) -> dict:
    return payload["layers"][0]


def flags(payload: dict) -> dict[str, str]:
    return {
        item["code"]: item["severity"] for item in payload["quality"]["flags"]
    }


class StationE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-station-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = StationWorkspace(Path(self.temp.name))
        self.workspace.write_stations("2026010113")

    def assert_plot(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with Image.open(self.workspace.output) as image:
            self.assertEqual(image.format, "PNG")
            rgb = np.asarray(image.convert("RGB"), dtype=int)
            self.assertGreater(np.count_nonzero(np.ptp(rgb, axis=2) > 30), 50)
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["command"], "station")
        self.assertEqual(
            [item["id"] for item in payload["layers"]], ["station"]
        )
        return payload

    def assert_rejected(self, result, message, code, option=None):
        self.assertNotEqual(
            result.returncode, 0, result.stdout + result.stderr
        )
        self.assertIn(message, result.stdout + result.stderr)
        self.assertEqual(
            sorted(p.name for p in self.workspace.output.parent.iterdir()),
            [self.workspace.sidecar.name],
        )
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(payload["error"].get("option"), option)

    def test_user_maps_one_station_hour(self):
        """Given one hour, when mapping NO2, then summarize the region."""
        payload = self.assert_plot(self.workspace.station("2026010113"))
        layer = station(payload)
        self.assertEqual(
            [layer["quantity"]["name"], layer["quantity"]["unit"]],
            ["NO2", "ug/m3"],
        )
        self.assertEqual(
            layer["time"],
            {
                "aggregation": "hourly",
                "at": "2026010113",
                "timezone": "Asia/Shanghai",
                "basis": "station_hour",
            },
        )
        self.assertEqual(layer["stats"]["mean"], 60)
        self.assertEqual(layer["coverage"]["total"], 2)
        self.assertEqual(payload["relations"], {})

    def test_user_reads_the_station_table(self):
        """Given three stations read, when mapping, then list all three."""
        payload = self.assert_plot(self.workspace.station("2026010113"))
        with open(station(payload)["data"], encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        self.assertNotIn("satellite_value", reader.fieldnames)
        self.assertEqual(
            [(row["id"], row["value"], row["in_region"]) for row in rows],
            [
                ("S001A", "40", "1"),
                ("S002A", "80", "1"),
                ("S003A", "999", "0"),
            ],
        )

    def test_user_counts_exceedances_only_inside_the_region(self):
        """Given 999 outside the region, when mapping, then count none."""
        payload = self.assert_plot(self.workspace.station("2026010113"))
        exceedance = station(payload)["exceedance"]
        self.assertEqual(
            [exceedance["threshold"], exceedance["count"]], [200, 0]
        )

    def test_user_sees_aqi_categories(self):
        """Given AQI 40 and 80, when mapping AQI, then count both bands."""
        payload = self.assert_plot(
            self.workspace.station("2026010113", var="AQI")
        )
        categories = station(payload)["categories"]
        self.assertEqual([categories["优"], categories["良"]], [1, 1])

    def test_user_is_warned_about_few_stations(self):
        """Given two valid stations, when mapping, then grade limited."""
        payload = self.assert_plot(self.workspace.station("2026010113"))
        self.assertEqual(flags(payload)["few_stations"], "warning")
        self.assertEqual(payload["quality"]["grade"], "limited")

    def test_user_reproduces_a_request(self):
        """Given explicit options, when mapping, then record their sources."""
        payload = self.assert_plot(self.workspace.station("2026010113"))
        resolved = payload["request"]["resolved"]
        self.assertEqual(resolved["var"], {"value": "NO2", "source": "cli"})
        self.assertEqual(
            resolved["datetime"], {"value": "2026010113", "source": "cli"}
        )
        self.assertEqual(
            resolved["data_dir"]["value"], str(self.workspace.stations)
        )

    def test_user_rejects_a_date_only_hour(self):
        """Given a date, when mapping, then require an exact hour."""
        self.assert_rejected(
            self.workspace.station("20260101"), "YYYYMMDDHH", "invalid_time"
        )

    def test_user_rejects_an_impossible_hour(self):
        """Given hour 25, when mapping, then reject it."""
        self.assert_rejected(
            self.workspace.station("2026010125"), "YYYYMMDDHH", "invalid_time"
        )

    def test_user_learns_the_variable_is_unknown(self):
        """Given an unknown variable, when mapping, then reject --var."""
        self.assert_rejected(
            self.workspace.station("2026010113", var="XYZ"),
            "XYZ",
            "invalid_argument",
            "--var",
        )

    def test_user_never_gets_another_hour(self):
        """Given only 23:00 on disk, when mapping 13:00, then report it."""
        self.workspace.write_stations("2026010123")
        (self.workspace.stations / "2026010113.nc").unlink()
        self.assert_rejected(
            self.workspace.station("2026010113"),
            "2026010113",
            "data_not_found",
        )

    def test_user_learns_a_region_does_not_exist(self):
        """Given an unknown region, when mapping, then report it."""
        self.assert_rejected(
            self.workspace.station("2026010113", region="Atlantis"),
            "Atlantis",
            "region_not_found",
        )


if __name__ == "__main__":
    unittest.main()
