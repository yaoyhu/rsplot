"""CLI-wide user scenarios; see CLI_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import errno
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from raster_support import (
    RasterWorkspace,
    assert_failed,
    error_line,
    zone_wording,
)

ENABLED = (
    "raster",
    "radius",
    "overlay",
    "station",
    "trend",
    "meteo",
    "fnr",
)


def open_when_read(fifo: Path, process) -> int:
    """Open ``fifo`` for writing once ``process`` is reading it.

    The run is then inside its data read, past any startup cleanup.
    """
    while process.poll() is None:
        try:
            return os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as error:
            if error.errno != errno.ENXIO:
                raise
    raise AssertionError(f"rsplot exited {process.returncode} unread")


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
        self.assertFalse(
            {"recent", "forecast", "reconstruct"} & listed, listed
        )

    def test_user_cannot_run_the_disabled_forecast_command(self):
        """Given the CLI, when running forecast, then report no such command."""
        result = self.workspace.invoke(
            "forecast", "FixtureCity", "2026010108", "--output", "out.png"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No such command", result.stdout + result.stderr)

    def test_user_cannot_run_the_removed_recent_command(self):
        """Given the CLI, when running recent, then report no such command."""
        result = self.workspace.invoke(
            "recent",
            "FixtureCity",
            "20260103",
            "--days",
            "3",
            "--product",
            "no2",
            "--output",
            str(self.workspace.output),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No such command", result.stdout + result.stderr)
        self.assertFalse(self.workspace.output.parent.exists())

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

    def test_user_sees_only_long_options_for_fnr(self):
        """Given fnr help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("fnr"), [])

    def test_user_sees_only_long_options_for_meteo(self):
        """Given meteo help, when reading options, then none is a letter."""
        self.assertEqual(self.short_options("meteo"), [])

    def help_zone_wording(self, command: str) -> list[str]:
        """Time-zone words in a command's help, read on one wide line."""
        # Wide output keeps Rich from wrapping a word across two lines.
        self.workspace.env["COLUMNS"] = "1000"
        result = self.workspace.invoke(command, "--help")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return zone_wording(result)

    def test_user_reads_raster_help_without_time_zones(self):
        """Given raster help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("raster"), [])

    def test_user_reads_overlay_help_without_time_zones(self):
        """Given overlay help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("overlay"), [])

    def test_user_reads_radius_help_without_time_zones(self):
        """Given radius help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("radius"), [])

    def test_user_reads_station_help_without_time_zones(self):
        """Given station help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("station"), [])

    def test_user_reads_trend_help_without_time_zones(self):
        """Given trend help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("trend"), [])

    def test_user_reads_fnr_help_without_time_zones(self):
        """Given fnr help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("fnr"), [])

    def test_user_reads_meteo_help_without_time_zones(self):
        """Given meteo help, when reading times, then no zone is named."""
        self.assertEqual(self.help_zone_wording("meteo"), [])

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

    def assert_invalid_output(self, result) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        error = error_line(result.stderr)
        self.assertEqual(error["code"], "invalid_argument")
        self.assertEqual(error["option"], "--output")

    def assert_output_suffix_required(self, *arguments: str) -> None:
        self.workspace.write_swath("20260101", 4)
        result = self.workspace.invoke(
            *arguments,
            "--output",
            str(self.workspace.output.with_suffix("")),
        )
        self.assert_invalid_output(result)
        self.assertFalse(self.workspace.output.parent.exists())

    def test_user_must_give_raster_a_png_suffix(self):
        """Given a swath, when output has no suffix, then reject it."""
        self.assert_output_suffix_required(
            "raster",
            "FixtureCity",
            "20260101",
            "--product",
            "no2",
            "--basemap",
            "none",
        )

    def test_user_must_give_radius_a_png_suffix(self):
        """Given radius arguments, when output has no suffix, then reject."""
        self.assert_output_suffix_required(
            "radius",
            "S001A",
            "20260101",
            "--km",
            "10",
            "--product",
            "no2",
            "--station-datetime",
            "2026010113",
        )

    def test_user_must_give_overlay_a_png_suffix(self):
        """Given overlay arguments, when output has no suffix, then reject."""
        self.assert_output_suffix_required(
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

    def test_user_must_give_station_a_png_suffix(self):
        """Given station arguments, when output has no suffix, then reject."""
        self.assert_output_suffix_required(
            "station",
            "FixtureCity",
            "2026010113",
            "--var",
            "NO2",
        )

    def test_user_must_give_trend_a_png_suffix(self):
        """Given trend arguments, when output has no suffix, then reject."""
        self.assert_output_suffix_required(
            "trend",
            "S001A",
            "20260101",
            "--days",
            "1",
            "--var",
            "NO2",
        )

    def test_user_must_give_meteo_a_png_suffix(self):
        """Given meteo arguments, when output has no suffix, then reject."""
        self.assert_output_suffix_required(
            "meteo",
            "FixtureCity",
            "2026010113",
            "--temp-level",
            "2m",
        )

    def test_user_must_give_fnr_a_png_suffix(self):
        """Given fnr arguments, when output has no suffix, then reject."""
        self.assert_output_suffix_required(
            "fnr",
            "FixtureCity",
            "20260101",
            "--days",
            "1",
        )

    def test_user_cannot_request_another_output_image_format(self):
        """Given a swath, when requesting JPEG, then reject before writing."""
        self.workspace.write_swath("20260101", 4)
        result = self.workspace.raster(
            "20260101",
            "--output",
            str(self.workspace.output.with_suffix(".jpg")),
        )
        self.assert_invalid_output(result)
        self.assertFalse(self.workspace.output.parent.exists())

    def test_user_cannot_give_an_empty_output(self):
        """Given a swath, when output is empty, then reject before writing."""
        self.workspace.write_swath("20260101", 4)
        result = self.workspace.raster("20260101", "--output", "")
        self.assert_invalid_output(result)
        self.assertFalse(self.workspace.output.parent.exists())

    def assert_directory_output_rejected(self, name: str) -> None:
        self.workspace.write_swath("20260101", 4)
        directory = self.workspace.output.parent / name
        directory.mkdir(parents=True)
        marker = directory / "keep.txt"
        marker.write_text("keep")
        result = self.workspace.raster("20260101", "--output", str(directory))
        self.assert_invalid_output(result)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(list(directory.iterdir()), [marker])
        self.assertEqual(list(directory.parent.iterdir()), [directory])

    def test_user_cannot_use_a_directory_as_output(self):
        """Given a directory, when used as output, then preserve and reject."""
        self.assert_directory_output_rejected("cli2")

    def test_user_cannot_use_a_png_named_directory_as_output(self):
        """Given a .png directory, when used as output, then reject it."""
        self.assert_directory_output_rejected("map.png")

    def test_user_keeps_existing_files_after_invalid_output(self):
        """Given JSON, when used as output, then rejection preserves it."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.sidecar.parent.mkdir()
        self.workspace.sidecar.write_text('{"keep": true}')
        result = self.workspace.raster(
            "20260101", "--output", str(self.workspace.sidecar)
        )
        self.assert_invalid_output(result)
        self.assertEqual(self.workspace.sidecar.read_text(), '{"keep": true}')
        self.assertEqual(
            list(self.workspace.output.parent.iterdir()),
            [self.workspace.sidecar],
        )

    def assert_exact_png_output(self, suffix: str) -> None:
        self.workspace.write_swath("20260101", 4)
        output = self.workspace.output.with_suffix(suffix)
        result = self.workspace.raster("20260101", "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(output.with_suffix(".json").read_text())
        self.assertEqual(payload["artifacts"]["image"], str(output))
        self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(output.with_suffix(".satellite.nc").is_file())

    def test_user_finds_the_exact_png_named_by_the_sidecar(self):
        """Given a .png output, when mapping, then its recorded file exists."""
        self.assert_exact_png_output(".png")

    def test_user_can_use_an_uppercase_png_suffix(self):
        """Given a .PNG output, when mapping, then preserve its filename."""
        self.assert_exact_png_output(".PNG")

    def test_user_never_finds_an_old_sidecar_after_a_killed_run(self):
        """Given an old sidecar, when a run is killed, then it is gone."""
        self.workspace.sidecar.parent.mkdir()
        self.workspace.sidecar.write_text('{"old": true}')
        swath = self.workspace.write_blocking_swath("20260101")
        process = self.workspace.start(
            "raster",
            "FixtureCity",
            "20260101",
            "--product",
            "no2",
            "--output",
            str(self.workspace.output),
        )
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        writer = open_when_read(swath, process)
        self.addCleanup(os.close, writer)
        self.assertFalse(self.workspace.sidecar.exists())

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

    def test_user_cannot_force_the_raster_region_level(self):
        """Given raster, when passing --level, then reject the option."""
        self.assert_no_such_option(
            "raster", "FixtureCity", "20260101", "--level", "city"
        )

    def test_user_cannot_force_the_overlay_region_level(self):
        """Given overlay, when passing --level, then reject the option."""
        self.assert_no_such_option(
            "overlay", "FixtureCity", "20260101", "--level", "city"
        )

    def test_user_cannot_force_the_station_region_level(self):
        """Given station, when passing --level, then reject the option."""
        self.assert_no_such_option(
            "station", "FixtureCity", "2026010113", "--level", "city"
        )

    def test_user_cannot_force_the_trend_region_level(self):
        """Given trend, when passing --level, then reject the option."""
        self.assert_no_such_option(
            "trend", "FixtureCity", "20260101", "--region", "--level", "city"
        )

    def test_user_cannot_force_the_fnr_region_level(self):
        """Given fnr, when passing --level, then reject the option."""
        self.assert_no_such_option(
            "fnr", "FixtureCity", "20260101", "--level", "city"
        )

    def test_user_cannot_force_the_meteo_region_level(self):
        """Given meteo, when passing --level, then reject the option."""
        self.assert_no_such_option(
            "meteo", "FixtureCity", "2026010113", "--level", "city"
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

    def test_user_cannot_set_a_raster_valid_day_threshold(self):
        """Given a window, when passing --n-min to raster, then reject it."""
        self.assert_no_such_option(
            "raster",
            "FixtureCity",
            "20260102",
            "--product",
            "no2",
            "--days",
            "2",
            "--n-min",
            "1",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_set_an_overlay_valid_day_threshold(self):
        """Given a window, when passing --n-min to overlay, then reject it."""
        self.assert_no_such_option(
            "overlay",
            "FixtureCity",
            "20260102",
            "--product",
            "no2",
            "--station-var",
            "NO2",
            "--station-datetime",
            "2026010213",
            "--days",
            "2",
            "--n-min",
            "1",
            "--output",
            str(self.workspace.output),
        )

    def test_user_cannot_set_a_radius_valid_day_threshold(self):
        """Given a window, when passing --n-min to radius, then reject it."""
        self.assert_no_such_option(
            "radius",
            "S001A",
            "20260102",
            "--km",
            "10",
            "--product",
            "no2",
            "--days",
            "2",
            "--n-min",
            "1",
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
        error = assert_failed(
            self,
            self.workspace,
            self.workspace.raster("20260101"),
            "[paths.data_dirs].no2",
            "data_not_configured",
            None,
        )
        self.assertEqual(error["details"], {"config_key": "no2"})
        self.assertNotIn("option", error["message"])

    def test_user_reads_a_failure_from_one_error_line(self):
        """Given --days 0, when mapping, then one line names code and option."""
        self.workspace.write_swath("20260101", 4)
        result = self.workspace.raster("20260101", "--days", "0")
        error = assert_failed(
            self,
            self.workspace,
            result,
            "--days",
            "invalid_argument",
            "--days",
        )
        self.assertEqual(error["message"], "--days 必须 >= 1。")

    def test_user_keeps_no_stale_sidecar_after_a_failure(self):
        """Given an earlier map, when the same output fails, then no JSON."""
        self.workspace.write_swath("20260101", 4)
        first = self.workspace.raster("20260101")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        failed = self.workspace.raster("20260101", "--days", "0")
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertFalse(self.workspace.sidecar.exists())

    def test_user_finds_no_format_number_in_a_sidecar(self):
        """Given a map, when reading its sidecar, then only the release."""
        self.workspace.write_swath("20260101", 4)
        result = self.workspace.raster("20260101")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.workspace.payload()
        self.assertEqual(
            [key in payload for key in ("schema", "status", "error")],
            [False, False, False],
        )
        self.assertIn("rsplot_version", payload)

    def test_user_reads_the_generation_time_in_beijing_time(self):
        """Given a New York clock, when mapping, then generated_at is +08."""
        self.workspace.write_swath("20260101", 4)
        self.workspace.env["TZ"] = "America/New_York"
        result = self.workspace.raster("20260101")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(
            self.workspace.payload()["generated_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$",
        )

    def test_user_cannot_run_the_disabled_reconstruct_command(self):
        """Given the CLI, when running reconstruct, then report no such command."""
        result = self.workspace.invoke(
            "reconstruct", "FixtureCity", "2026010108", "--output", "out.png"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No such command", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
