"""Meteo user scenarios; see METEO_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from meteo_support import MeteoWorkspace
from netCDF4 import Dataset
from PIL import Image
from raster_support import schema_errors

HOUR = "2026010113"
UTC = "2026010105"


def layer(payload: dict, layer_id: str) -> dict:
    return next(item for item in payload["layers"] if item["id"] == layer_id)


class MeteoE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-meteo-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = MeteoWorkspace(Path(self.temp.name))

    def assert_plot(self, result, layer_ids):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with Image.open(self.workspace.output) as image:
            self.assertEqual(image.format, "PNG")
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["command"], "meteo")
        self.assertEqual([item["id"] for item in payload["layers"]], layer_ids)
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

    def test_user_maps_temperature(self):
        """Given 293.15 K, when mapping temperature, then mean is 20 °C."""
        self.workspace.write_temperature(UTC)
        payload = self.assert_plot(
            self.workspace.meteo(HOUR, "--temp-level", "2m"), ["temperature"]
        )
        temperature = layer(payload, "temperature")
        self.assertEqual(
            [temperature["stats"]["mean"], temperature["quantity"]["unit"]],
            [20, "degC"],
        )
        self.assertEqual(
            temperature["time"],
            {
                "aggregation": "hourly",
                "at": HOUR,
                "timezone": "Asia/Shanghai",
                "basis": "era5_hour",
                "archive_time_utc": UTC,
            },
        )
        self.assertEqual(payload["relations"], {})

    def test_user_maps_temperature_from_older_files(self):
        """Given files with a `time` coordinate, when mapping, then 20 °C."""
        self.workspace.time_name = "time"
        self.workspace.write_temperature(UTC)
        payload = self.assert_plot(
            self.workspace.meteo(HOUR, "--temp-level", "2m"), ["temperature"]
        )
        self.assertEqual(layer(payload, "temperature")["stats"]["mean"], 20)

    def test_user_maps_wind(self):
        """Given u 3 and v 4, when mapping wind, then speed is 5."""
        self.workspace.write_wind(UTC)
        wind = layer(
            self.assert_plot(
                self.workspace.meteo(HOUR, "--wind-level", "10m"), ["wind"]
            ),
            "wind",
        )
        self.assertEqual(
            [wind["kind"], wind["stats"]["mean"], wind["quantity"]["unit"]],
            ["vector_grid", 5, "m/s"],
        )
        self.assertEqual(wind["vector_summary"]["wind_from_deg"], 216.9)

    def test_user_loads_the_wind_grid(self):
        """Given u 3 and v 4, when loading data, then the grid holds them."""
        self.workspace.write_wind(UTC)
        payload = self.assert_plot(
            self.workspace.meteo(HOUR, "--wind-level", "10m"), ["wind"]
        )
        with Dataset(layer(payload, "wind")["data"]) as dataset:
            counted = dataset["counted"][:].astype(bool)
            values = [
                float(np.nanmean(dataset[name][:].filled(np.nan)[counted]))
                for name in ("u", "v", "value")
            ]
        self.assertEqual([round(value, 3) for value in values], [3, 4, 5])

    def test_user_maps_all_three_layers(self):
        """Given ERA5 and stations, when mapping all, then pair the hours."""
        self.workspace.write_temperature(UTC)
        self.workspace.write_wind(UTC)
        self.workspace.write_stations(HOUR)
        payload = self.assert_plot(
            self.workspace.meteo(
                HOUR,
                "--temp-level",
                "2m",
                "--wind-level",
                "10m",
                "--station-var",
                "NO2",
            ),
            ["temperature", "wind", "station"],
        )
        self.assertEqual(layer(payload, "station")["stats"]["mean"], 60)
        self.assertEqual(
            payload["relations"]["time_matching"],
            {
                "layers": ["wind", "station"],
                "reference": "same_hour",
                "difference_minutes": 0,
                "manual_override": False,
            },
        )

    def test_user_records_the_wind_drawing(self):
        """Given --wind-stride 2, when mapping, then render records it."""
        self.workspace.write_wind(UTC)
        payload = self.assert_plot(
            self.workspace.meteo(
                HOUR, "--wind-level", "10m", "--wind-stride", "2"
            ),
            ["wind"],
        )
        rendered = payload["render"]["layers"]["wind"]
        self.assertEqual(
            [rendered["stride"], rendered["colorbar"]], [2, False]
        )

    def test_user_rejects_a_date_only_hour(self):
        """Given a date, when overlaying stations, then require an hour."""
        self.workspace.write_wind(UTC)
        self.workspace.write_stations(HOUR)
        self.assert_rejected(
            self.workspace.meteo(
                "20260101", "--wind-level", "10m", "--station-var", "NO2"
            ),
            "YYYYMMDDHH",
            "invalid_time",
        )

    def test_user_needs_wind_for_a_station_layer(self):
        """Given stations without wind, when mapping, then reject it."""
        self.workspace.write_temperature(UTC)
        self.workspace.write_stations(HOUR)
        self.assert_rejected(
            self.workspace.meteo(
                HOUR, "--temp-level", "2m", "--station-var", "NO2"
            ),
            "--wind-level",
            "invalid_argument",
            "--station-var",
        )

    def test_user_names_at_least_one_layer(self):
        """Given no level, when mapping, then ask for a layer."""
        self.workspace.write_temperature(UTC)
        self.assert_rejected(
            self.workspace.meteo(HOUR), "--temp-level", "invalid_argument"
        )

    def test_user_learns_a_level_is_unsupported(self):
        """Given level 333, when mapping temperature, then reject it."""
        self.workspace.write_temperature(UTC)
        self.assert_rejected(
            self.workspace.meteo(HOUR, "--temp-level", "333"),
            "333",
            "invalid_argument",
            "--temp-level",
        )

    def test_user_styles_temperature_only_when_drawn(self):
        """Given wind only, when passing --cmap, then reject it."""
        self.workspace.write_wind(UTC)
        self.assert_rejected(
            self.workspace.meteo(
                HOUR, "--wind-level", "10m", "--cmap", "viridis"
            ),
            "--cmap",
            "invalid_argument",
            "--cmap",
        )

    def test_user_learns_the_era5_hour_is_missing(self):
        """Given ERA5 for another hour, when mapping, then report it."""
        self.workspace.write_temperature("2026010106")
        self.assert_rejected(
            self.workspace.meteo(HOUR, "--temp-level", "2m"),
            "ERA5",
            "data_not_found",
        )

    def test_user_learns_the_station_hour_is_missing(self):
        """Given no station file, when overlaying stations, then report it."""
        self.workspace.write_wind(UTC)
        self.assert_rejected(
            self.workspace.meteo(
                HOUR, "--wind-level", "10m", "--station-var", "NO2"
            ),
            HOUR,
            "data_not_found",
        )

    def test_user_learns_the_region_does_not_exist(self):
        """Given an unknown region, when mapping, then report it."""
        self.workspace.write_temperature(UTC)
        self.assert_rejected(
            self.workspace.meteo(
                HOUR, "--temp-level", "2m", region="Atlantis"
            ),
            "Atlantis",
            "region_not_found",
        )


if __name__ == "__main__":
    unittest.main()
