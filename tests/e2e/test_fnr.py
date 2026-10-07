"""FNR user scenarios; see FNR_SCENARIOS.md for Given/When/Then."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from fnr_support import FnrWorkspace
from netCDF4 import Dataset
from PIL import Image
from raster_support import assert_failed, schema_errors


def layer(payload: dict, layer_id: str) -> dict:
    return next(item for item in payload["layers"] if item["id"] == layer_id)


def flags(payload: dict) -> list[tuple[str, str, str | None]]:
    return [
        (item["code"], item["severity"], item.get("layer"))
        for item in payload["quality"]["flags"]
    ]


class FnrE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rsplot-fnr-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = FnrWorkspace(Path(self.temp.name))

    def assert_plot(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with Image.open(self.workspace.output) as image:
            self.assertEqual(image.format, "PNG")
            rgb = np.asarray(image.convert("RGB"), dtype=int)
            self.assertGreater(np.count_nonzero(np.ptp(rgb, axis=2) > 30), 500)
        payload = self.workspace.payload()
        self.assertEqual(schema_errors(payload), [])
        self.assertEqual(payload["command"], "fnr")
        self.assertEqual(
            [item["id"] for item in payload["layers"]], ["no2", "hcho", "fnr"]
        )
        return payload

    def assert_rejected(self, result, message, code, option=None):
        return assert_failed(
            self, self.workspace, result, message, code, option
        )

    def test_user_maps_the_fnr_regime(self):
        """Given NO2 2 and HCHO 6, when mapping, then FNR is 3."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(self.workspace.fnr("20260103"))
        fnr = layer(payload, "fnr")
        self.assertEqual(
            [
                layer(payload, "no2")["stats"]["mean"],
                layer(payload, "hcho")["stats"]["mean"],
                fnr["stats"]["mean"],
            ],
            [2, 6, 3],
        )
        self.assertEqual(fnr["quantity"]["unit"], "1")
        self.assertEqual(
            [fnr["coverage"]["valid"], fnr["coverage"]["total"]], [16, 16]
        )
        time = fnr["time"]
        self.assertEqual(
            [time["aggregation"], time["start"], time["end"], time["basis"]],
            ["window_mean", "20260101", "20260103", "filename_start_date_utc"],
        )

    def test_user_counts_cells_per_regime(self):
        """Given FNR 3, when mapping, then every cell is NOx-limited."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(self.workspace.fnr("20260103"))
        self.assertEqual(
            layer(payload, "fnr")["categories"],
            {"voc_limited": 0, "transition": 0, "nox_limited": 16},
        )

    def test_user_changes_regime_thresholds(self):
        """Given FNR 3, when raising thresholds, then cells are VOC-limited."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(
            self.workspace.fnr(
                "20260103",
                "--voc-threshold",
                "4",
                "--nox-threshold",
                "5",
                "--display-max",
                "6",
            )
        )
        self.assertEqual(
            layer(payload, "fnr")["categories"]["voc_limited"], 16
        )
        rendered = payload["render"]["layers"]["fnr"]
        self.assertEqual(
            [
                rendered["voc_threshold"],
                rendered["nox_threshold"],
                rendered["display_max"],
            ],
            [4, 5, 6],
        )

    def test_user_loads_the_fnr_grids(self):
        """Given FNR 3, when loading data, then the grids hold it."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(self.workspace.fnr("20260103"))
        self.assertEqual(len(payload["artifacts"]["data"]), 3)
        with Dataset(layer(payload, "fnr")["data"]) as dataset:
            values = dataset["value"][:].filled(np.nan)
            counted = dataset["counted"][:].astype(bool)
            days = dataset["valid_days"][:]
        self.assertEqual(round(float(np.nanmean(values[counted])), 2), 3.0)
        self.assertEqual(int(days[counted].min()), 3)

    def test_user_reads_the_masking_diagnostics(self):
        """Given full coverage, when mapping, then all 16 cells pass."""
        self.workspace.write_days(2, 6)
        method = layer(
            self.assert_plot(self.workspace.fnr("20260103")), "fnr"
        )["method"]
        self.assertEqual(
            [method["mask_counts"]["final_valid"], method["no2_min_column"]],
            [16, 0.5],
        )

    def test_user_finds_both_products_input_files(self):
        """Given three days per product, when mapping, then list them."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(self.workspace.fnr("20260103"))
        self.assertEqual(
            [
                layer(payload, "no2")["source"]["files_total"],
                layer(payload, "hcho")["source"]["files_total"],
            ],
            [3, 3],
        )

    def test_user_is_warned_about_missing_days(self):
        """Given HCHO missing on Jan 2, when mapping, then warn on hcho."""
        self.workspace.write_days(2, 6, days=(1, 3))
        self.workspace.write_swath("20260102", 2, product="no2")
        payload = self.assert_plot(
            self.workspace.fnr("20260103", "--n-min", "2")
        )
        self.assertEqual(layer(payload, "hcho")["time"]["days"]["found"], 2)
        self.assertIn(("missing_days", "warning", "hcho"), flags(payload))
        self.assertEqual(layer(payload, "fnr")["stats"]["mean"], 3)

    def test_user_masks_a_low_no2_background(self):
        """Given NO2 2, when requiring NO2 >= 3, then nothing is valid."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260103", "--no2-min", "3"),
            "FNR",
            "no_valid_data",
        )

    def test_user_rejects_an_invalid_date(self):
        """Given Feb 30, when mapping, then reject the date."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260230"), "20260230", "invalid_time"
        )

    def test_user_rejects_a_zero_day_window(self):
        """Given --days 0, when mapping, then reject it."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260103", "--days", "0"),
            "--days",
            "invalid_argument",
            "--days",
        )

    def test_user_rejects_an_impossible_n_min(self):
        """Given three days, when requiring five, then reject it."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260103", "--n-min", "5"),
            "--n-min",
            "invalid_argument",
            "--n-min",
        )

    def test_user_rejects_crossed_thresholds(self):
        """Given voc above nox, when mapping, then reject the thresholds."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr(
                "20260103", "--voc-threshold", "3", "--nox-threshold", "2"
            ),
            "threshold",
            "invalid_argument",
        )

    def test_user_learns_the_region_does_not_exist(self):
        """Given an unknown region, when mapping, then report it."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260103", region="Atlantis"),
            "Atlantis",
            "region_not_found",
        )

    def test_user_maps_fnr_across_two_regions(self):
        """Given data in one region, when mapping two, then keep both."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(
            self.workspace.fnr("20260103", region="FixtureCity,EastCity")
        )
        self.assertEqual(
            [item["name"] for item in payload["region"]["members"]],
            ["FixtureCity", "EastCity"],
        )
        self.assertEqual(
            [
                (row["name"], row["n"], row["mean"], row["category"])
                for row in layer(payload, "fnr")["by_member"]
            ],
            [
                ("FixtureCity", 16, 3.0, "nox_limited"),
                ("EastCity", 0, None, None),
            ],
        )

    def test_user_compares_the_inputs_across_two_regions(self):
        """Given two regions, when mapping, then each input has members."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(
            self.workspace.fnr("20260103", region="FixtureCity,EastCity")
        )
        self.assertEqual(
            [
                (row["name"], row["n"], row["mean"])
                for row in layer(payload, "no2")["by_member"]
            ],
            [("FixtureCity", 16, 2.0), ("EastCity", 0, None)],
        )
        self.assertEqual(
            [row["mean"] for row in layer(payload, "hcho")["by_member"]],
            [6.0, None],
        )

    def test_user_names_the_window_for_a_single_date(self):
        """Given one end date, when omitting --days, then reject it."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260103", days=None),
            "--days",
            "invalid_argument",
            "--days",
        )

    def test_user_maps_an_explicit_date_range(self):
        """Given a date range, when omitting --days, then map the range."""
        self.workspace.write_days(2, 6)
        payload = self.assert_plot(
            self.workspace.fnr("20260101-20260103", days=None)
        )
        self.assertEqual(
            [layer(payload, "fnr")["time"][k] for k in ("start", "end")],
            ["20260101", "20260103"],
        )

    def test_user_cannot_combine_a_date_range_with_days(self):
        """Given a date range, when adding --days, then reject it."""
        self.workspace.write_days(2, 6)
        self.assert_rejected(
            self.workspace.fnr("20260101-20260103"),
            "--days",
            "invalid_argument",
            "--days",
        )


if __name__ == "__main__":
    unittest.main()
