"""CLI-wide user scenarios; see CLI_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

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

    def test_user_cannot_run_the_disabled_reconstruct_command(self):
        """Given the CLI, when running reconstruct, then report no such command."""
        result = self.workspace.invoke(
            "reconstruct", "FixtureCity", "2026010108", "--output", "out.png"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No such command", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
