"""Overlay user scenarios; see OVERLAY_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from overlay_support import OverlayWorkspace
from PIL import Image

SUPPORT_KEYS = ("valid_region_pixels", "total_region_pixels", "coverage_pct")


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
        self.assertEqual(payload["command"], "overlay")
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

    def test_user_overlays_one_tropomi_day_with_stations(self):
        """Given orbits and stations, when overlaying, then both layers agree."""
        self.workspace.write_swath("20260101", 2, orbit=1)
        self.workspace.write_swath("20260101", 4, orbit=2)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay("20260101", "--smooth", "0")
        )
        self.assertEqual(payload["date"], "20260101")
        self.assertEqual(payload["datetime"], "2026010113")
        self.assertEqual(payload["raster"]["swath"]["n_files"], 2)
        self.assertEqual(payload["raster"]["stats"]["mean"], 3)
        self.assertEqual(payload["station"]["n_stations"], 2)
        self.assertEqual(payload["station"]["stats"]["mean"], 60)

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
            [plain["raster"]["stats"][key] for key in SUPPORT_KEYS],
            [smoothed["raster"]["stats"][key] for key in SUPPORT_KEYS],
        )

    def test_user_gets_surface_no2_for_no2_columns(self):
        """Given NO2 columns, when omitting --var, then stations show NO2."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        self.assertEqual(payload["station"]["variable"], "NO2")

    def test_user_gets_mda8_ozone_for_total_ozone(self):
        """Given total ozone, when omitting --var, then stations show MDA8."""
        self.workspace.write_swath("20260101", 300, product="o3")
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay("20260101", "--product", "o3")
        )
        self.assertEqual(payload["station"]["variable"], "O3_8h_24h")

    def test_user_gets_mda8_ozone_for_profile_ozone(self):
        """Given profile ozone, when omitting --var, then stations show MDA8."""
        self.workspace.write_swath("20260101", 30, product="o3pr")
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay("20260101", "--product", "o3pr")
        )
        self.assertEqual(payload["station"]["variable"], "O3_8h_24h")

    def test_user_gets_mda8_ozone_for_tropomi_hcho(self):
        """Given TROPOMI HCHO, when omitting --var, then stations show MDA8."""
        self.workspace.write_swath("20260101", 6, product="hcho")
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay("20260101", "--product", "hcho")
        )
        self.assertEqual(payload["station"]["variable"], "O3_8h_24h")

    def test_user_gets_mda8_ozone_for_gems_hcho(self):
        """Given a GEMS HCHO scan, when omitting --var, then use MDA8."""
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
            )
        )
        self.assertEqual(payload["station"]["variable"], "O3_8h_24h")

    def test_user_selects_a_station_variable_explicitly(self):
        """Given total ozone, when supplying --var O3, then stations show O3."""
        self.workspace.write_swath("20260101", 300, product="o3")
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260101", "--product", "o3", "--var", "O3"
            )
        )
        self.assertEqual(payload["station"]["variable"], "O3")

    def test_user_rejects_hourly_tropomi_dates(self):
        """Given TROPOMI, when DATE has an hour, then require a date."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(self.workspace.overlay("2026010113"), "YYYYMMDD")

    def test_user_names_the_station_hour_for_a_tropomi_day(self):
        """Given a TROPOMI day, when omitting the station hour, then reject."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101", station=None),
            "--station-datetime",
        )

    def test_user_rejects_a_date_only_station_hour(self):
        """Given a TROPOMI day, when the station hour lacks HH, then reject."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101", station="20260101"),
            "YYYYMMDDHH",
        )

    def test_user_never_gets_an_automatically_chosen_station_hour(self):
        """Given another hour on disk, when the named hour is missing, reject."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010123")
        self.assert_rejected(self.workspace.overlay("20260101"), "2026010113")

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
        self.assertEqual(payload["raster"]["stats"]["mean"], 6)
        self.assertEqual(payload["raster"]["window"]["n_days_found"], 2)
        self.assertEqual(payload["date"], "20260102")
        self.assertEqual(payload["datetime"], "2026010213")

    def test_user_rejects_competing_window_selectors(self):
        """Given a range, when also supplying --days, then reject ambiguity."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        self.assert_rejected(
            self.workspace.overlay("20260101-20260102", "--days", "2"),
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
        self.assertEqual(payload["datetime"], "2026010112")
        self.assertEqual(payload["time_matching"]["difference_minutes"], 0)
        self.assertFalse(payload["time_matching"]["manual_override"])

    def test_user_names_the_station_hour_for_a_gems_day(self):
        """Given a GEMS daily mean, when omitting the hour, then reject."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_stations("2026010112")
        self.assert_rejected(
            self.workspace.overlay(
                "20260101", "--sensor", "gems", station=None
            ),
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
        self.assertEqual(payload["raster"]["stats"]["mean"], 7)
        self.assertEqual(payload["datetime"], "2026010212")

    def test_user_sees_how_a_tropomi_day_meets_its_station_hour(self):
        """Given a TROPOMI day, when overlaying, then record the pairing."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.write_stations("2026010113")
        payload = self.assert_plot(self.workspace.overlay("20260101"))
        self.assertEqual(
            payload["time_matching"],
            {
                "satellite_period": {
                    "start": "20260101",
                    "end": "20260101",
                    "aggregation": "daily",
                    "date_basis": "filename_start_date_utc",
                },
                "station_datetime": "2026010113",
                "timezone": "Asia/Shanghai",
                "difference_minutes": None,
                "manual_override": True,
                "reference": "period_mean_with_explicit_station_hour",
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
        self.assertEqual(
            payload["time_matching"]["satellite_period"],
            {
                "start": "20260101",
                "end": "20260102",
                "aggregation": "window_mean",
                "date_basis": "filename_start_date_utc",
            },
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
        self.assertEqual(
            payload["time_matching"]["satellite_period"],
            {
                "start": "20260101",
                "end": "20260102",
                "aggregation": "window_mean",
                "date_basis": "asia_shanghai_calendar_day",
            },
        )
        self.assertIsNone(payload["time_matching"]["difference_minutes"])

    def test_user_keeps_the_gems_daily_mean_pairing_record(self):
        """Given a GEMS daily mean, when overlaying, then keep its record."""
        self.workspace.write_gems_scan("202601010400", 2)
        self.workspace.write_stations("2026010112")
        payload = self.assert_plot(
            self.workspace.overlay(
                "20260101", "--sensor", "gems", station="2026010112"
            )
        )
        self.assertEqual(
            payload["time_matching"],
            {
                "satellite_date": "20260101",
                "satellite_aggregation": "daily_mean",
                "station_datetime": "2026010112",
                "timezone": "Asia/Shanghai",
                "difference_minutes": None,
                "manual_override": True,
                "reference": "daily_mean_with_explicit_station_hour",
            },
        )


if __name__ == "__main__":
    unittest.main()
