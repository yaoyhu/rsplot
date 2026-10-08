"""Radius user scenarios; see RADIUS_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from radius_support import RadiusWorkspace
from raster_support import assert_failed, schema_errors, zone_wording

HOUR = ("--station-datetime", "2026010113")
VALUES = ("--station-var", "NO2", *HOUR)


def layer(payload: dict, layer_id: str) -> dict:
    return next(item for item in payload["layers"] if item["id"] == layer_id)


def flags(payload: dict) -> dict[str, str]:
    return {
        item["code"]: item["severity"] for item in payload["quality"]["flags"]
    }


class RadiusE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-radius-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = RadiusWorkspace(Path(self.temp.name))

    def standard_inputs(self):
        self.workspace.write_swath("20260101", 2, orbit=1)
        self.workspace.write_swath("20260101", 4, orbit=2)
        self.workspace.write_radius_stations("2026010113")

    def assert_plot(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with Image.open(self.workspace.output) as image:
            self.assertEqual(image.format, "PNG")
            rgb = np.asarray(image.convert("RGB"), dtype=int)
            self.assertGreater(np.count_nonzero(np.ptp(rgb, axis=2) > 30), 500)
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["command"], "radius")
        self.assertEqual(zone_wording(result, payload), [])
        self.assertEqual(
            [item["id"] for item in payload["layers"]],
            ["satellite", "station"],
        )
        return payload

    def assert_rejected(self, result, message, code, option=None):
        return assert_failed(
            self, self.workspace, result, message, code, option
        )

    def test_user_maps_a_square_around_a_station_with_values(self):
        """Given orbits and stations, when mapping, then both layers agree."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        region = payload["region"]
        self.assertEqual(region["kind"], "station_radius")
        self.assertEqual(
            [
                region["radius"]["center_station"],
                region["radius"]["km"],
                region["radius"]["side_length_km"],
            ],
            ["C001A", 20, 40],
        )
        self.assertEqual(layer(payload, "satellite")["stats"]["mean"], 3)
        station = layer(payload, "station")
        self.assertEqual(station["time"]["at"], "2026010113")
        self.assertEqual(station["coverage"]["total"], 2)
        self.assertEqual(station["stats"]["mean"], 60)

    def test_user_reads_a_compact_radius_title(self):
        """Given a day and hour, when mapping, then show compact dates."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        self.assertEqual(
            payload["render"]["title"],
            "C001A 上下左右各 20 km\n"
            "TROPOMI NO2 · 2026-01-01 单日\n"
            "站点 NO2 · 2026-01-01 13:00",
        )

    def test_user_maps_station_locations_only(self):
        """Given no station variable, when mapping, then show positions only."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *HOUR))
        station = layer(payload, "station")
        self.assertEqual(station["quantity"]["name"], "location")
        self.assertEqual(station["coverage"]["total"], 2)
        self.assertEqual(station["stats"]["n"], 0)
        self.assertEqual(payload["relations"], {})
        self.assertEqual(
            [f["layer"] for f in payload["quality"]["flags"] if "layer" in f],
            [],
        )

    def test_user_reads_the_radius_station_table(self):
        """Given two stations in the square, when mapping, then list them."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        with open(
            layer(payload, "station")["data"], encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(
            [(row["id"], row["is_center"]) for row in rows],
            [("C001A", "1"), ("N002A", "0")],
        )
        self.assertEqual(rows[0]["distance_km"], "0")
        self.assertAlmostEqual(float(rows[1]["distance_km"]), 7.3, delta=0.3)
        self.assertGreater(float(rows[1]["dx_km"]), 4)
        self.assertGreater(float(rows[1]["dy_km"]), 5)

    def test_user_sees_satellite_values_at_stations(self):
        """Given two stations in valid cells, when mapping, then pair them."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        colocation = payload["relations"]["colocation"]
        self.assertEqual(colocation["pairs"], 2)
        self.assertIsNone(colocation["spearman"])
        self.assertFalse(colocation["comparable_units"])

    def test_user_sees_how_the_day_meets_the_station_hour(self):
        """Given a TROPOMI day, when mapping values, then record the pairing."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        self.assertEqual(
            payload["relations"]["time_matching"],
            {
                "layers": ["satellite", "station"],
                "reference": "period_mean_with_explicit_station_hour",
                "difference_minutes": None,
                "manual_override": True,
            },
        )

    def test_user_reads_what_the_comparison_pairs(self):
        """Given a day and an hour, when mapping values, then record both."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        relations = payload["relations"]
        self.assertEqual(
            [
                relations["time_matching"]["difference_minutes"],
                relations["colocation"]["comparable_units"],
            ],
            [None, False],
        )
        self.assertNotIn("column_vs_surface", flags(payload))
        self.assertNotIn("daily_vs_hourly", flags(payload))

    def test_user_records_the_administrative_context(self):
        """Given a centre in FixtureCity, when mapping, then name the city."""
        self.standard_inputs()
        payload = self.assert_plot(self.workspace.radius("20260101", *VALUES))
        context = payload["region"]["radius"]["administrative_context"]
        self.assertEqual(context["center_cities"], ["FixtureCity"])

    def test_user_matches_a_gems_scan_to_the_nearest_station_hour(self):
        """Given a noon scan, when mapping values, then use noon stations."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_radius_stations("2026010112")
        payload = self.assert_plot(
            self.workspace.radius(
                "202601011200",
                "--sensor",
                "gems",
                "--station-var",
                "NO2",
            )
        )
        self.assertEqual(layer(payload, "station")["time"]["at"], "2026010112")
        matching = payload["relations"]["time_matching"]
        self.assertEqual(
            [matching["reference"], matching["difference_minutes"]],
            ["nominal_scan_time", 0],
        )

    def test_user_names_the_station_hour_for_a_daily_mean_with_values(self):
        """Given values for a day, when omitting the hour, then reject."""
        self.standard_inputs()
        self.assert_rejected(
            self.workspace.radius("20260101", "--station-var", "NO2"),
            "--station-datetime",
            "invalid_argument",
            "--station-datetime",
        )

    def test_user_learns_the_center_station_is_unknown(self):
        """Given an unknown station, when mapping, then report it."""
        self.standard_inputs()
        self.assert_rejected(
            self.workspace.radius("20260101", *VALUES, station_id="ZZZ9A"),
            "ZZZ9A",
            "region_not_found",
        )

    def test_user_rejects_a_non_positive_square(self):
        """Given --km 0, when mapping, then require a positive distance."""
        self.standard_inputs()
        self.assert_rejected(
            self.workspace.radius("20260101", *VALUES, km="0"),
            "--km",
            "invalid_argument",
            "--km",
        )

    def test_user_learns_the_station_variable_is_unknown(self):
        """Given an unknown variable, when mapping, then reject it."""
        self.standard_inputs()
        self.assert_rejected(
            self.workspace.radius("20260101", "--station-var", "XYZ", *HOUR),
            "XYZ",
            "invalid_argument",
            "--station-var",
        )


if __name__ == "__main__":
    unittest.main()
