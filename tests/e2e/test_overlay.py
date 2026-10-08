"""Overlay user scenarios; see OVERLAY_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np
from overlay_support import OverlayWorkspace
from PIL import Image
from raster_support import assert_failed, schema_errors, zone_wording

SUPPORT_KEYS = ("valid", "total", "fraction")


def layer(payload: dict, layer_id: str) -> dict:
    return next(item for item in payload["layers"] if item["id"] == layer_id)


def flags(payload: dict) -> dict[str, str]:
    return {
        item["code"]: item["severity"] for item in payload["quality"]["flags"]
    }


class OverlayE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-overlay-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = OverlayWorkspace(Path(self.temp.name))

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
        self.assertEqual(payload["command"], "overlay")
        self.assertEqual(zone_wording(result, payload), [])
        self.assertEqual(
            [item["id"] for item in payload["layers"]],
            ["satellite", "station"],
        )
        self.assertEqual(
            payload["artifacts"]["image"], str(self.workspace.output)
        )
        self.assertEqual(
            payload["artifacts"]["sidecar"], str(self.workspace.sidecar)
        )
        return payload

    def assert_rejected(self, result, message, code, option=None):
        return assert_failed(
            self, self.workspace, result, message, code, option
        )

    def station_rows(self, payload):
        path = layer(payload, "station")["data"]
        with open(path, encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_user_overlays_one_tropomi_day_with_stations(self):
        """Given orbits and stations, when overlaying, then both layers agree."""
        self.workspace.write_swath("20260101", 2, orbit=1)
        self.workspace.write_swath("20260101", 4, orbit=2)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay("20260101", "--smooth", "0")
        )
        satellite = layer(payload, "satellite")
        station = layer(payload, "station")
        self.assertEqual(satellite["time"]["start"], "20260101")
        self.assertEqual(satellite["time"]["aggregation"], "daily")
        self.assertEqual(satellite["source"]["files_total"], 2)
        self.assertEqual(satellite["stats"]["mean"], 3)
        self.assertEqual(station["time"]["at"], "2026010113")
        self.assertEqual(station["coverage"]["total"], 2)
        self.assertEqual(station["stats"]["mean"], 60)

    def test_user_keeps_observed_satellite_support_while_smoothing(self):
        """Given one observed cell, when smoothing, then support is unchanged."""
        self.workspace.write_swath("20260101", 4, sparse=True)
        self.workspace.write_stations("2026010113")
        plain = self.assert_plot(
            self.workspace.overlay("20260101", "--smooth", "0")
        )
        smoothed = self.assert_plot(
            self.workspace.overlay("20260101", "--smooth", "1.5")
        )
        self.assertEqual(
            [layer(plain, "satellite")["coverage"][k] for k in SUPPORT_KEYS],
            [
                layer(smoothed, "satellite")["coverage"][k]
                for k in SUPPORT_KEYS
            ],
        )

    def test_user_must_name_the_station_variable(self):
        """Given stations, when omitting --station-var, then exit 2."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        result = self.workspace.overlay("20260101", station_var=None)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--station-var", result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.parent.exists())

    def test_user_cannot_use_the_old_station_option(self):
        """Given stations, when passing --var, then reject the option."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        result = self.workspace.overlay("20260101", "--var", "NO2")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("No such option", result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.parent.exists())

    def test_user_overlays_a_gems_hcho_scan_with_mda8_ozone(self):
        """Given a GEMS HCHO scan, when naming MDA8 ozone, then show it."""
        self.workspace.write_gems_scan("202601010400", 6, product="hcho")
        self.workspace.write_stations("2026010112")
        payload = self.assert_plot(
            self.workspace.overlay(
                "202601011200",
                "--sensor",
                "gems",
                "--product",
                "hcho",
                station=None,
                station_var="O3_8h_24h",
            )
        )
        self.assertEqual(
            layer(payload, "station")["quantity"]["name"], "O3_8h_24h"
        )

    def test_user_selects_a_station_variable_explicitly(self):
        """Given total ozone, when naming O3, then stations show O3."""
        self.workspace.write_swath("20260101", 300, product="o3")
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260101", "--product", "o3", station_var="O3"
            )
        )
        self.assertEqual(layer(payload, "station")["quantity"]["name"], "O3")

    def test_user_learns_the_station_variable_is_unknown(self):
        """Given an unknown variable, when overlaying, then reject it."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101", station_var="XYZ"),
            "XYZ",
            "invalid_argument",
            "--station-var",
        )

    def test_user_rejects_hourly_tropomi_dates(self):
        """Given TROPOMI, when DATE has an hour, then require a date."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("2026010113"), "YYYYMMDD", "invalid_time"
        )

    def test_user_names_the_station_hour_for_a_tropomi_day(self):
        """Given a TROPOMI day, when omitting the station hour, then reject."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101", station=None),
            "--station-datetime",
            "invalid_argument",
            "--station-datetime",
        )

    def test_user_rejects_a_date_only_station_hour(self):
        """Given a TROPOMI day, when the station hour lacks HH, then reject."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101", station="20260101"),
            "YYYYMMDDHH",
            "invalid_time",
            "--station-datetime",
        )

    def test_user_never_gets_an_automatically_chosen_station_hour(self):
        """Given another hour on disk, when the named hour is missing, reject."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010123")
        self.assert_rejected(
            self.workspace.overlay("20260101"), "2026010113", "data_not_found"
        )

    def test_user_overlays_a_tropomi_window_mean(self):
        """Given two days, when overlaying a window, then days count equally."""
        self.workspace.write_swath("20260101", 2, orbit=1)
        self.workspace.write_swath("20260101", 4, orbit=2)
        self.workspace.write_swath("20260102", 9)
        self.workspace.write_stations("2026010213")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260102",
                "--days",
                "2",
                "--smooth",
                "0",
                station="2026010213",
            )
        )
        satellite = layer(payload, "satellite")
        self.assertEqual(satellite["stats"]["mean"], 6)
        self.assertEqual(satellite["time"]["days"]["found"], 2)
        self.assertEqual(satellite["time"]["end"], "20260102")
        self.assertEqual(layer(payload, "station")["time"]["at"], "2026010213")

    def test_user_rejects_competing_window_selectors(self):
        """Given a range, when also supplying --days, then reject ambiguity."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101-20260102", "--days", "2"),
            "--days",
            "invalid_argument",
            "--days",
        )

    def test_user_matches_a_gems_scan_to_the_nearest_station_hour(self):
        """Given a noon scan, when omitting the hour, then use noon stations."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_stations("2026010112")
        payload = self.assert_plot(
            self.workspace.overlay(
                "202601011200", "--sensor", "gems", station=None
            )
        )
        self.assertEqual(layer(payload, "station")["time"]["at"], "2026010112")
        self.assertEqual(
            payload["relations"]["time_matching"],
            {
                "layers": ["satellite", "station"],
                "reference": "nominal_scan_time",
                "difference_minutes": 0,
                "manual_override": False,
            },
        )

    def test_user_learns_a_gems_scan_hour_was_overridden(self):
        """Given a noon scan, when naming 13:00, then flag the override."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay(
                "202601011200", "--sensor", "gems", station="2026010113"
            )
        )
        matching = payload["relations"]["time_matching"]
        self.assertEqual(matching["difference_minutes"], 60)
        self.assertTrue(matching["manual_override"])
        self.assertNotIn("manual_time_override", flags(payload))

    def test_user_names_the_station_hour_for_a_gems_day(self):
        """Given a GEMS daily mean, when omitting the hour, then reject."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_stations("2026010112")
        self.assert_rejected(
            self.workspace.overlay(
                "20260101", "--sensor", "gems", station=None
            ),
            "--station-datetime",
            "invalid_argument",
            "--station-datetime",
        )

    def test_user_overlays_a_gems_window_mean(self):
        """Given unequal scan counts, when averaging two days, then mean is 7."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601010500", 6)
        self.workspace.write_gems_scan("202601020400", 10)
        self.workspace.write_stations("2026010212")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260102",
                "--sensor",
                "gems",
                "--days",
                "2",
                station="2026010212",
            )
        )
        self.assertEqual(layer(payload, "satellite")["stats"]["mean"], 7)
        self.assertEqual(layer(payload, "station")["time"]["at"], "2026010212")

    def test_user_sees_how_a_tropomi_day_meets_its_station_hour(self):
        """Given a TROPOMI day, when overlaying, then record the pairing."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        self.assertEqual(
            payload["relations"]["time_matching"],
            {
                "layers": ["satellite", "station"],
                "reference": "period_mean_with_explicit_station_hour",
                "difference_minutes": None,
                "manual_override": True,
            },
        )

    def test_user_sees_how_a_tropomi_window_meets_its_station_hour(self):
        """Given a TROPOMI window, when overlaying, then record the period."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_swath("20260102", 4)
        self.workspace.write_stations("2026010213")
        payload = self.assert_plot(
            self.workspace.overlay("20260101-20260102", station="2026010213")
        )
        time = layer(payload, "satellite")["time"]
        self.assertEqual(
            [time["aggregation"], time["start"], time["end"], time["basis"]],
            ["window_mean", "20260101", "20260102", "calendar_day"],
        )

    def test_user_sees_how_a_gems_window_meets_its_station_hour(self):
        """Given a GEMS window, when overlaying, then record China-time days."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_gems_scan("202601020400", 10)
        self.workspace.write_stations("2026010212")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260102",
                "--sensor",
                "gems",
                "--days",
                "2",
                station="2026010212",
            )
        )
        time = layer(payload, "satellite")["time"]
        self.assertEqual(time["aggregation"], "window_mean")
        self.assertEqual(time["basis"], "calendar_day")
        self.assertIsNone(
            payload["relations"]["time_matching"]["difference_minutes"]
        )

    def test_user_sees_how_a_gems_daily_mean_meets_its_station_hour(self):
        """Given a GEMS daily mean, when overlaying, then record the pairing."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_stations("2026010112")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260101", "--sensor", "gems", station="2026010112"
            )
        )
        self.assertEqual(
            payload["relations"]["time_matching"],
            {
                "layers": ["satellite", "station"],
                "reference": "daily_mean_with_explicit_station_hour",
                "difference_minutes": None,
                "manual_override": True,
            },
        )

    def test_user_reads_the_station_table(self):
        """Given three stations read, when overlaying, then list all three."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        rows = self.station_rows(
            self.assert_plot(self.workspace.overlay("20260101"))
        )
        self.assertEqual(
            [(row["id"], row["value"], row["in_region"]) for row in rows],
            [
                ("S001A", "40", "1"),
                ("S002A", "80", "1"),
                ("S003A", "999", "0"),
            ],
        )

    def test_user_sees_satellite_values_at_stations(self):
        """Given uniform satellite 4, when overlaying, then pair stations."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay("20260101", "--smooth", "0")
        )
        colocation = payload["relations"]["colocation"]
        self.assertEqual(colocation["pairs"], 2)
        self.assertIsNone(colocation["spearman"])
        self.assertFalse(colocation["comparable_units"])
        self.assertEqual(
            [
                (row["satellite_value"], row["colocated"])
                for row in self.station_rows(payload)
            ],
            [("4", "1"), ("4", "1"), ("", "0")],
        )

    def test_user_counts_exceedances_only_inside_the_region(self):
        """Given 999 outside the region, when overlaying, then count none."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        exceedance = layer(payload, "station")["exceedance"]
        self.assertEqual(
            [exceedance["threshold"], exceedance["count"]],
            [
                200,
                0,
            ],
        )

    def test_user_reads_what_the_comparison_pairs(self):
        """Given a day and an hour, when overlaying, then record, not explain."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        relations = payload["relations"]
        self.assertEqual(
            [
                relations["time_matching"]["reference"],
                relations["time_matching"]["difference_minutes"],
                relations["colocation"]["comparable_units"],
            ],
            ["period_mean_with_explicit_station_hour", None, False],
        )
        self.assertEqual(flags(payload), {"few_stations": "warning"})

    def test_user_is_warned_about_few_stations(self):
        """Given two valid stations, when overlaying, then flag the count."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        self.assertEqual(
            payload["quality"]["flags"],
            [
                {
                    "code": "few_stations",
                    "severity": "warning",
                    "layer": "station",
                    "evidence": {"valid": 2, "total": 2, "threshold": 3},
                }
            ],
        )

    def test_user_sees_satellite_values_at_the_highest_stations(self):
        """Given colocated stations, when overlaying, then pair the values."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        station = next(
            item for item in payload["layers"] if item["id"] == "station"
        )
        self.assertEqual(
            [
                (item["id"], item["value"], item["satellite_value"])
                for item in station["extremes"]["items"]
            ],
            [("S002A", 80.0, 4.0), ("S001A", 40.0, 4.0)],
        )


if __name__ == "__main__":
    unittest.main()
