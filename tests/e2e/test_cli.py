"""CLI-wide user scenarios; see CLI_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from raster_support import RasterWorkspace

ENABLED = (
    "raster",
    "radius",
    "overlay",
    "station",
    "trend",
    "meteo",
    "recent",
    "fnr",
)


class CliE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-cli-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = RasterWorkspace(Path(self.temp.name))

    def test_user_sees_only_enabled_commands(self):
        """Given the CLI, when requesting help, then list enabled commands."""
        result = self.workspace.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        listed = {
            line.strip("│ ").split()[0]
            for line in result.stdout.splitlines()
            if line.startswith("│ ") and line.strip("│ ")
        }
        self.assertTrue(set(ENABLED) <= listed, listed)
        self.assertFalse({"forecast", "reconstruct"} & listed, listed)

    def test_user_cannot_run_the_disabled_forecast_command(self):
        """Given the CLI, when running forecast, then report no such command."""
        result = self.workspace.invoke(
            "forecast", "FixtureCity", "2026010108", "--output", "out.png"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No such command", result.stdout + result.stderr)

    def assert_no_such_option(self, *arguments: str) -> None:
        result = self.workspace.invoke(*arguments)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("No such option", result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.parent.exists())

    def short_options(self, command: str) -> list[str]:
        """Single-letter option names listed in a command's help."""
        result = self.workspace.invoke(command, "--help")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return re.findall(r"(?<=\s)-[A-Za-z](?=\s)", result.stdout)

    def test_user_sees_only_long_options_for_raster(self):
        """Given raster help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("raster"), [])

    def test_user_sees_only_long_options_for_overlay(self):
        """Given overlay help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("overlay"), [])

    def test_user_sees_only_long_options_for_radius(self):
        """Given radius help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("radius"), [])

    def test_user_sees_only_long_options_for_station(self):
        """Given station help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("station"), [])

    def test_user_sees_only_long_options_for_trend(self):
        """Given trend help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("trend"), [])

    def test_user_sees_only_long_options_for_recent(self):
        """Given recent help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("recent"), [])

    def test_user_sees_only_long_options_for_fnr(self):
        """Given fnr help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("fnr"), [])

    def test_user_sees_only_long_options_for_meteo(self):
        """Given meteo help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("meteo"), [])

    def test_user_cannot_use_a_former_alias(self):
        """Given raster, when passing -o, then reject it as unknown."""
        self.assert_no_such_option(
            "raster", "FixtureCity", "20260101", "-o", "map.png"
        )

    def assert_missing_option(self, option: str, *arguments: str) -> None:
        output = str(self.workspace.output)
        result = self.workspace.invoke(
            *(output if item == "OUT" else item for item in arguments)
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Missing option", result.stdout + result.stderr)
        self.assertIn(option, result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.parent.exists())

    def test_user_must_give_raster_an_output(self):
        """Given raster, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output", "raster", "FixtureCity", "20260101", "--product", "no2"
        )

    def test_user_must_give_raster_a_product(self):
        """Given raster, when omitting --product, then exit 2 naming it."""
        self.assert_missing_option(
            "--product", "raster", "FixtureCity", "20260101", "--output", "OUT"
        )

    def test_user_must_give_overlay_an_output(self):
        """Given overlay, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output",
            "overlay",
            "FixtureCity",
            "20260101",
            "--product",
            "no2",
            "--station-var",
            "NO2",
            "--station-datetime",
            "2026010113",
        )

    def test_user_must_give_overlay_a_product(self):
        """Given overlay, when omitting --product, then exit 2 naming it."""
        self.assert_missing_option(
            "--product",
            "overlay",
            "FixtureCity",
            "20260101",
            "--station-var",
            "NO2",
            "--station-datetime",
            "2026010113",
            "--output",
            "OUT",
        )

    def test_user_must_give_radius_an_output(self):
        """Given radius, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output",
            "radius",
            "S001A",
            "20260101",
            "--km",
            "10",
            "--product",
            "no2",
        )

    def test_user_must_give_radius_a_product(self):
        """Given radius, when omitting --product, then exit 2 naming it."""
        self.assert_missing_option(
            "--product",
            "radius",
            "S001A",
            "20260101",
            "--km",
            "10",
            "--output",
            "OUT",
        )

    def test_user_must_give_station_an_output(self):
        """Given station, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output", "station", "FixtureCity", "2026010113", "--var", "NO2"
        )

    def test_user_must_give_station_a_variable(self):
        """Given station, when omitting --var, then exit 2 naming it."""
        self.assert_missing_option(
            "--var", "station", "FixtureCity", "2026010113", "--output", "OUT"
        )

    def test_user_must_give_trend_an_output(self):
        """Given trend, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output",
            "trend",
            "S001A",
            "20260101",
            "--days",
            "1",
            "--var",
            "NO2",
        )

    def test_user_must_give_trend_a_variable(self):
        """Given trend, when omitting --var, then exit 2 naming it."""
        self.assert_missing_option(
            "--var",
            "trend",
            "S001A",
            "20260101",
            "--days",
            "1",
            "--output",
            "OUT",
        )

    def test_user_must_give_recent_an_output(self):
        """Given recent, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output",
            "recent",
            "FixtureCity",
            "20260101",
            "--days",
            "3",
            "--product",
            "no2",
        )

    def test_user_must_give_recent_a_day_count(self):
        """Given recent, when omitting --days, then exit 2 naming it."""
        self.assert_missing_option(
            "--days",
            "recent",
            "FixtureCity",
            "20260101",
            "--product",
            "no2",
            "--output",
            "OUT",
        )

    def test_user_must_give_fnr_an_output(self):
        """Given fnr, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output", "fnr", "FixtureCity", "20260101", "--days", "3"
        )

    def test_user_must_give_meteo_an_output(self):
        """Given meteo, when omitting --output, then exit 2 naming it."""
        self.assert_missing_option(
            "--output",
            "meteo",
            "FixtureCity",
            "2026010113",
            "--temp-level",
            "2m",
        )

    def test_user_cannot_point_raster_at_a_data_folder(self):
        """Given config paths, when passing --data-dir, then reject it."""
        self.assert_no_such_option(
            "raster",
            "FixtureCity",
            "20260101",
            "--data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_overlay_at_a_satellite_folder(self):
        """Given config paths, when passing --raster-dir, then reject it."""
        self.assert_no_such_option(
            "overlay",
            "FixtureCity",
            "20260101",
            "--raster-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_overlay_at_a_station_folder(self):
        """Given config paths, when passing --station-dir, then reject it."""
        self.assert_no_such_option(
            "overlay",
            "FixtureCity",
            "20260101",
            "--station-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_radius_at_a_data_folder(self):
        """Given config paths, when passing --data-dir, then reject it."""
        self.assert_no_such_option(
            "radius",
            "S001A",
            "20260101",
            "--km",
            "10",
            "--data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_radius_at_a_station_folder(self):
        """Given config paths, when passing --station-data-dir, then reject."""
        self.assert_no_such_option(
            "radius",
            "S001A",
            "20260101",
            "--km",
            "10",
            "--station-data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_station_at_a_data_folder(self):
        """Given config paths, when passing --data-dir, then reject it."""
        self.assert_no_such_option(
            "station",
            "FixtureCity",
            "2026010113",
            "--data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_trend_at_a_data_folder(self):
        """Given config paths, when passing --data-dir, then reject it."""
        self.assert_no_such_option(
            "trend",
            "S001A",
            "20260101",
            "--data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_recent_at_a_data_folder(self):
        """Given config paths, when passing --data-dir, then reject it."""
        self.assert_no_such_option(
            "recent",
            "FixtureCity",
            "20260101",
            "--data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_fnr_at_an_no2_folder(self):
        """Given config paths, when passing --no2-dir, then reject it."""
        self.assert_no_such_option(
            "fnr",
            "FixtureCity",
            "20260101",
            "--no2-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_fnr_at_an_hcho_folder(self):
        """Given config paths, when passing --hcho-dir, then reject it."""
        self.assert_no_such_option(
            "fnr",
            "FixtureCity",
            "20260101",
            "--hcho-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_meteo_at_an_era5_folder(self):
        """Given config paths, when passing --data-dir, then reject it."""
        self.assert_no_such_option(
            "meteo",
            "FixtureCity",
            "2026010113",
            "--data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_point_meteo_at_a_station_folder(self):
        """Given config paths, when passing --station-data-dir, then reject."""
        self.assert_no_such_option(
            "meteo",
            "FixtureCity",
            "2026010113",
            "--station-data-dir",
            "/x",
            "--output",
            str(self.workspace.output),
        )

    def test_user_learns_a_data_folder_is_not_configured(self):
        """Given no no2 folder in config, when mapping, then say so."""
        del self.workspace.data_dirs["no2"]
        self.workspace.write_config()
        result = self.workspace.raster("20260101")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = self.workspace.payload()
        self.assertEqual(
            [payload["status"], payload["error"]["code"]],
            ["error", "data_not_configured"],
        )
        self.assertIn("[paths.data_dirs].no2", payload["error"]["message"])
        self.assertNotIn("option", payload["error"]["message"])

    def test_user_cannot_run_the_disabled_reconstruct_command(self):
        """Given the CLI, when running reconstruct, then report no such command."""
        result = self.workspace.invoke(
            "reconstruct", "FixtureCity", "2026010108", "--output", "out.png"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No such command", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
