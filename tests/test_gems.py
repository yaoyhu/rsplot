"""GEMS scientific/CLI regressions, using tiny local NetCDF fixtures."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import xarray as xr
from netCDF4 import Dataset
from rich.console import Console
from shapely.geometry import box
from typer.testing import CliRunner

from rsplot.cli import app
from rsplot.config import LEVEL_DEFAULTS, AppConfig
from rsplot.geo.boundaries import RegionInfo
from rsplot.readers import PRODUCT_REGISTRY, get_product_info
from rsplot.readers.base import BaseReader, SwathData
from rsplot.readers.gems import EPOCH, GemsNO2Reader, match_station_hour
from rsplot.temporal import compute_window_mean, read_scan_mean

EXTENT = (115.0, 117.0, 30.0, 32.0)
QUIET = Console(file=io.StringIO())


def make_scan(
    root, product="no2", stamp="202609010045", values=None, omit_cloud=False
):
    """One 2x3 scan, with all pixels in a single target cell by default."""
    info = get_product_info(product, sensor="gems")
    spec = info.reader_cls.spec
    folder = root / stamp[:6] / stamp[6:8]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        f"GK2_GEMS_L2_{stamp[:8]}_{stamp[8:]}_"
        f"{spec.file_product}_FC_DPRO_ORI.nc"
    )
    data = "product" if spec.profile else "Data Fields"
    geo = "geolocation" if spec.profile else "Geolocation Fields"
    names = (
        ("longitude", "latitude", "solar_zenith_angle", "viewing_zenith_angle")
        if spec.profile
        else (
            "Longitude",
            "Latitude",
            "SolarZenithAngle",
            "ViewingZenithAngle",
        )
    )
    with Dataset(path, "w") as ds:
        ds.createDimension("y", 2)
        ds.createDimension("x", 3)
        for group in (
            data,
            geo,
            "support_data",
            "METADATA/ALGORITHM_SETTINGS",
        ):
            ds.createGroup(group)

        def field(group, name, value, units="1"):
            v = ds[group].createVariable(
                name, "f8", ("y", "x"), fill_value=-1e30
            )
            v.units = units
            v[:] = value
            return v

        for name, value in zip(names, (115.2, 30.2, 30, 20), strict=True):
            field(geo, name, value)
        xx, yy = np.meshgrid([115.201, 115.202, 115.203], [30.201, 30.202])
        ds[f"{geo}/{names[0]}"][:] = xx
        ds[f"{geo}/{names[1]}"][:] = yy
        raw = (
            np.ones((2, 3))
            if values is None
            else np.array(values).reshape(2, 3)
        )
        field(
            data,
            spec.value,
            raw / spec.scale,
            "DU" if spec.profile else "molecules cm-2",
        )
        if spec.profile:
            # Both output quantities live in a single O3P file.
            other = (
                "troposphere_ozone_column"
                if product == "o3"
                else "total_ozone_column"
            )
            field(data, other, raw + 100, "DU")
        flag = (
            "final_algorithm_flags" if spec.profile else "FinalAlgorithmFlags"
        )
        field(data, flag, 0)
        cloud_group, cloud_name = spec.cloud.split("/")
        if not omit_cloud:
            field(cloud_group, cloud_name, 0.1)
        t = ds[geo].createVariable(
            "time" if spec.profile else "Time", "f8", ("x",)
        )
        t.units = (
            "seconds since 2000-01-01 12:00:00 UTC"
            if spec.profile
            else "second"
            if product == "no2"
            else "Seconds since 2000-01-01 12 UTC"
        )
        nominal = datetime.strptime(stamp, "%Y%m%d%H%M").replace(
            tzinfo=timezone.utc
        )
        t[:] = (nominal - EPOCH).total_seconds() + np.array([0, 600, 1800])
        settings = ds if spec.profile else ds["METADATA/ALGORITHM_SETTINGS"]
        settings.product_version = "test-v1"
    return path


class GemsReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_four_quantity_mappings_and_units(self):
        for product in ("no2", "hcho", "o3", "o3pr"):
            with self.subTest(product=product):
                root = self.root / product
                make_scan(root, product, values=[-2, 1, 2, 3, 4, 5])
                reader = get_product_info(product, sensor="gems").reader_cls()
                scan = reader.read(str(root), "202609010845", EXTENT)
                np.testing.assert_allclose(scan.values, [-2, 1, 2, 3, 4, 5])
                meta = scan.metadata["scans"][0]
                self.assertEqual(meta["product_version"], "test-v1")
                self.assertEqual(
                    meta["nominal_local"], "2026-09-01T08:45:00+08:00"
                )
                self.assertEqual(
                    meta["observation_end_utc"], "2026-09-01T01:15:00+00:00"
                )

    def test_quality_fill_cloud_and_geometry_filters(self):
        for product in ("no2", "hcho", "o3pr"):
            root = self.root / product
            p = make_scan(root, product, values=[-2, 1, 2, 3, 4, 5])
            spec = get_product_info(product, sensor="gems").reader_cls.spec
            data = "product" if spec.profile else "Data Fields"
            geo = "geolocation" if spec.profile else "Geolocation Fields"
            flag = (
                "final_algorithm_flags"
                if spec.profile
                else "FinalAlgorithmFlags"
            )
            with Dataset(p, "a") as ds:
                ds[f"{data}/{flag}"][0, 1] = 2
                ds[spec.cloud][0, 2] = -1e30
                ds[f"{data}/{spec.value}"][1, 0] = -1e30
                ds[
                    f"{geo}/"
                    + (
                        "solar_zenith_angle"
                        if spec.profile
                        else "SolarZenithAngle"
                    )
                ][1, 1] = 70
                ds[f"{geo}/" + ("longitude" if spec.profile else "Longitude")][
                    1, 2
                ] = 125
            reader = get_product_info(product, sensor="gems").reader_cls()
            scan = reader.read(str(root), "20260901", EXTENT)
            np.testing.assert_allclose(scan.values, [-2])

    def test_cloud_threshold_is_inclusive(self):
        p = make_scan(self.root)
        with Dataset(p, "a") as ds:
            ds["Data Fields/CloudFraction"][:] = [
                [0.5, 0.51, -0.1],
                [1.1, np.nan, 0],
            ]
        scan = GemsNO2Reader().read(str(self.root), "20260901", EXTENT)
        self.assertEqual(scan.n_pixels, 2)

    def test_cross_month_utc_selection_and_missing_scan(self):
        make_scan(self.root, stamp="202608311645")
        make_scan(self.root, stamp="202609011645")
        reader = GemsNO2Reader()
        files = reader.discover(str(self.root), "20260901")
        self.assertEqual(len(files), 1)
        self.assertIn("20260831_1645", files[0][0].name)
        self.assertEqual(
            len(reader.discover(str(self.root), "202609010045")), 1
        )
        with self.assertRaisesRegex(FileNotFoundError, "202609010045"):
            reader.discover(str(self.root), "202609010145")

    def test_duplicates_are_not_double_weighted(self):
        p = make_scan(self.root)
        p.with_name(p.name.replace("_FC_", "_FW_")).write_bytes(p.read_bytes())
        with self.assertRaisesRegex(ValueError, "多个文件"):
            GemsNO2Reader().discover(str(self.root), "20260901")

    def test_unreadable_and_unknown_units_are_reported(self):
        p = make_scan(self.root)
        with Dataset(p, "a") as ds:
            ds["Data Fields/ColumnAmountNO2Trop"].units = "unexpected"
        broken = make_scan(self.root, stamp="202609010145")
        broken.write_text("not netcdf")
        result = read_scan_mean(
            reader=GemsNO2Reader(),
            data_dir=str(self.root),
            request="20260901",
            extent=EXTENT,
            res=1,
        )
        self.assertEqual(result.n_broken, 2)
        self.assertEqual(len(result.metadata["failed_files"]), 2)
        self.assertTrue(np.isnan(result.grid).all())

    def test_absent_required_field_is_file_error(self):
        make_scan(self.root, omit_cloud=True)
        result = list(
            GemsNO2Reader().iter_scans(str(self.root), "20260901", EXTENT)
        )
        self.assertEqual(result[0].n_broken, 1)
        self.assertIn("error", result[0].metadata)

    def test_equal_scan_then_equal_day_weighting(self):
        make_scan(self.root, values=[1] * 6)
        make_scan(
            self.root,
            stamp="202609010145",
            values=[9, -1e15, -1e15, -1e15, -1e15, -1e15],
        )
        make_scan(self.root, stamp="202609020045", values=[20] * 6)
        # Day one: 6 pixels at 1 and 1 pixel at 9 -> scan mean 5, not 15/7.
        day = read_scan_mean(
            reader=GemsNO2Reader(),
            data_dir=str(self.root),
            request="20260901",
            extent=EXTENT,
            res=1,
        )
        self.assertAlmostEqual(day.grid[0, 0], 5)
        self.assertEqual(day.n_valid[0, 0], 2)
        result = compute_window_mean(
            reader=GemsNO2Reader(),
            data_dir=str(self.root),
            dates=["20260901", "20260902", "20260903"],
            extent=EXTENT,
            res=1,
            qa_threshold=0.5,
            console=QUIET,
        )
        self.assertAlmostEqual(result.grid[0, 0], 12.5)
        self.assertEqual(result.n_valid[0, 0], 2)
        self.assertIn("20260903", result.dates_failed)
        self.assertTrue(np.isnan(result.grid[1, 1]))

    def test_empty_scans_are_not_zero_observations(self):
        make_scan(self.root, values=[8] * 6)
        p = make_scan(self.root, stamp="202609010145")
        with Dataset(p, "a") as ds:
            ds["Data Fields/FinalAlgorithmFlags"][:] = 4
        result = read_scan_mean(
            reader=GemsNO2Reader(),
            data_dir=str(self.root),
            request="20260901",
            extent=EXTENT,
            res=1,
        )
        self.assertEqual(result.grid[0, 0], 8)
        self.assertEqual(result.n_valid[0, 0], 1)
        self.assertEqual(result.metadata["n_scans_found"], 2)
        self.assertEqual(result.metadata["n_scans_valid"], 1)

    def test_station_rounding_override_and_validation(self):
        for scan, hour in [
            ("202609010845", "2026090109"),
            ("202609012330", "2026090200"),
            ("202609010829", "2026090108"),
        ]:
            actual, meta = match_station_hour(scan)
            self.assertEqual(actual, hour)
            self.assertLessEqual(abs(meta["difference_minutes"]), 30)
        hour, meta = match_station_hour("202609010845", "2026090112")
        self.assertEqual(hour, "2026090112")
        self.assertTrue(meta["manual_override"])
        with self.assertRaises(ValueError):
            match_station_hour("202602300845")
        with self.assertRaises(ValueError):
            match_station_hour("202609010845", "20260901")

    def test_registry_and_legacy_batch_compatibility(self):
        self.assertIs(get_product_info("no2"), PRODUCT_REGISTRY["no2"])
        self.assertEqual(
            get_product_info("o3pr", sensor="gems").data_key, "gems_o3"
        )
        with self.assertRaises(ValueError):
            get_product_info("no2", sensor="unknown")

        class LegacyReader(BaseReader):
            def read(self, data_dir, date, extent, qa_threshold=0.5):
                return SwathData(
                    np.array([115.2]),
                    np.array([30.2]),
                    np.array([3.0]),
                    1,
                    1,
                    0,
                )

        result = compute_window_mean(
            reader=LegacyReader(),
            data_dir="unused",
            dates=["20260901"],
            extent=EXTENT,
            res=1,
            qa_threshold=0.5,
            console=QUIET,
        )
        self.assertEqual(result.grid[0, 0], 3)
        self.assertEqual(result.n_files_total, 1)


class GemsCommandTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(
            self.stack.enter_context(tempfile.TemporaryDirectory())
        )
        self.region = RegionInfo(
            "Test",
            "city",
            box(115, 30, 117, 32),
            EXTENT,
            LEVEL_DEFAULTS["city"],
        )
        self.cfg = AppConfig(
            data_dirs={"gems_no2": str(self.root), "guokong": str(self.root)},
            geojson_dir=str(self.root),
        )
        for target, value in [
            ("rsplot.config.AppConfig.load", self.cfg),
            ("rsplot.geo.boundaries.resolve_region", self.region),
            ("rsplot.plotting.styles.setup_fonts", None),
            ("rsplot.commands.overlay.load_fallback_city_boundaries", None),
        ]:
            self.stack.enter_context(patch(target, return_value=value))
        self.plot = self.stack.enter_context(
            patch("rsplot.plotting.raster.plot_raster")
        )
        self.overlay = self.stack.enter_context(
            patch("rsplot.plotting.overlay.plot_overlay")
        )
        self.runner = CliRunner()
        make_scan(self.root, values=[1, 2, 3, 4, 5, 6])
        xr.Dataset(
            {
                "lon": ("station", [115.2]),
                "lat": ("station", [30.2]),
                "id": ("station", ["A001"]),
                "NO2": ("station", [25.0]),
            }
        ).to_netcdf(self.root / "2026090109.nc")

    def invoke(self, command, date, *options):
        output = self.root / (
            command + ".png" if command != "recent" else "recent.json"
        )
        args = [
            command,
            "Test",
            date,
            "--sensor",
            "gems",
            "-p",
            "no2",
            "--res",
            "1",
            "--output",
            str(output),
        ]
        if command != "recent":
            args += ["--basemap", "none"]
        result = self.runner.invoke(app, args + list(options))
        return result, output.with_suffix(".json")

    def test_scan_and_daily_recent_share_scientific_statistics(self):
        result, out = self.invoke("raster", "202609010845", "--smooth", "0")
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        scan = json.loads(out.read_text())
        result, out = self.invoke("raster", "20260901", "--smooth", "2")
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        daily = json.loads(out.read_text())
        result, out = self.invoke("recent", "20260901", "--days", "1")
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        recent = json.loads(out.read_text())
        self.assertEqual(scan["stats"]["mean"], daily["stats"]["mean"])
        self.assertEqual(
            daily["stats"]["mean"], recent["daily"][0]["stats"]["mean"]
        )
        display = self.plot.call_args.args[2]
        self.assertEqual(int(np.isfinite(display).sum()), 1)
        self.assertEqual(daily["sensor"], "gems")
        self.assertNotIn("qa_threshold", daily["swath"])
        self.assertEqual(recent["source"], "raster")

    def test_window_n_min_remains_days(self):
        make_scan(self.root, stamp="202609010145")
        result, _ = self.invoke("raster", "20260901-20260902", "--n-min", "2")
        self.assertEqual(result.exit_code, 1)
        result, out = self.invoke(
            "raster", "20260901-20260902", "--n-min", "1"
        )
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        data = json.loads(out.read_text())
        self.assertEqual(data["window"]["n_days_found"], 1)
        self.assertIn("20260902", data["window"]["dates_failed"])
        self.assertIn("20260901", data["window"]["daily"])

    def test_overlay_hour_pairing_and_missing_hour(self):
        result, out = self.invoke("overlay", "202609010845")
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        data = json.loads(out.read_text())
        self.assertEqual(data["datetime"], "2026090109")
        self.assertEqual(data["time_matching"]["difference_minutes"], 15)
        result, _ = self.invoke(
            "overlay", "202609010845", "--station-datetime", "2026090110"
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("2026090110", result.output)

    def test_daily_overlay_uses_daily_mean_and_explicit_station_hour(self):
        make_scan(self.root, stamp="202609010145", values=[10] * 6)
        result, out = self.invoke("raster", "20260901", "--smooth", "0")
        self.assertEqual(result.exit_code, 0, result.output)
        daily = json.loads(out.read_text())
        result, out = self.invoke(
            "overlay",
            "20260901",
            "--station-datetime",
            "2026090109",
            "--smooth",
            "0",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        overlay = json.loads(out.read_text())
        self.assertEqual(overlay["raster"]["stats"], daily["stats"])
        self.assertEqual(overlay["raster"]["swath"], daily["swath"])
        self.assertEqual(overlay["datetime"], "2026090109")
        self.assertIsNone(overlay["time_matching"]["difference_minutes"])
        self.assertEqual(
            overlay["time_matching"]["satellite_aggregation"], "daily_mean"
        )
        self.assertIn("daily mean", self.overlay.call_args.kwargs["title"])
        result, _ = self.invoke(
            "overlay", "20260901", "--station-datetime", "2026090119"
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("2026090119", result.output)

    def test_display_resolution_preserves_raster_overlay_recent_statistics(
        self,
    ):
        results = []
        supports = []
        for res in ["0.1", "0.075"]:
            result, out = self.invoke(
                "raster", "20260901", "--res", res, "--smooth", "0"
            )
            self.assertEqual(result.exit_code, 0, result.output)
            results.append(json.loads(out.read_text()))
            supports.append(self.plot.call_args.kwargs["coverage_geometry"])
        self.assertEqual(results[0]["stats"], results[1]["stats"])
        self.assertTrue(supports[0].equals(supports[1]))
        self.assertEqual(results[0]["swath"]["analysis_resolution_deg"], 0.05)
        self.assertNotEqual(
            results[0]["swath"]["display_resolution_deg"],
            results[1]["swath"]["display_resolution_deg"],
        )
        for res in ["0.1", "0.075"]:
            result, out = self.invoke(
                "overlay",
                "20260901",
                "--station-datetime",
                "2026090109",
                "--res",
                res,
                "--smooth",
                "0",
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                json.loads(out.read_text())["raster"]["stats"],
                results[0]["stats"],
            )
            result, out = self.invoke(
                "raster",
                "20260901-20260901",
                "--n-min",
                "1",
                "--res",
                res,
                "--smooth",
                "0",
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                json.loads(out.read_text())["stats"], results[0]["stats"]
            )
            result, out = self.invoke(
                "recent", "20260901", "--days", "1", "--res", res
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                json.loads(out.read_text())["daily"][0]["stats"]["mean"],
                results[0]["stats"]["mean"],
            )

    def test_expected_errors_have_no_traceback(self):
        for command, date, args in [
            ("raster", "20260901", ["--qa", "0.5"]),
            ("raster", "202609010845", ["--days", "1"]),
            ("raster", "202609010845", ["--n-min", "1"]),
            ("raster", "202609010945", []),
            ("overlay", "20260901", []),
            ("overlay", "202609010845", ["-p", "hcho"]),
            ("recent", "20260901", ["--source", "station"]),
        ]:
            with self.subTest(command=command, args=args):
                result, _ = self.invoke(command, date, *args)
                self.assertEqual(
                    result.exit_code, 1, result.output + str(result.exception)
                )
                self.assertNotIn("Traceback", result.output)

    def test_recent_all_invalid_retains_file_diagnostics(self):
        p = make_scan(self.root)
        p.write_text("broken")
        result, out = self.invoke("recent", "20260901", "--days", "1")
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        row = json.loads(out.read_text())["daily"][0]
        self.assertFalse(row["ok"])
        self.assertEqual(row["meta"]["n_broken"], 1)
        self.assertEqual(len(row["meta"]["failed_files"]), 1)


class GemsFootprintTests(unittest.TestCase):
    def test_overlap_uses_area_and_preserves_empty_cells(self):
        from rsplot.geo.footprints import overlap_mean, regular_grid

        lon, lat = regular_grid((0, 2, 0, 1), 1)
        cx = np.array([[0, 0.75, 0.75, 0], [0.75, 1, 1, 0.75]])
        cy = np.array([[0, 0, 1, 1], [0, 0, 1, 1]])
        grid = overlap_mean(cx, cy, np.array([10.0, 30.0]), lon, lat, 1)
        self.assertAlmostEqual(grid[0, 0], 15)
        self.assertTrue(np.isnan(grid[0, 1]))

    def test_native_center_geometry_does_not_bridge_qa_hole(self):
        from rsplot.geo.footprints import (
            inferred_corner_grid,
            overlap_mean,
            pixel_corners,
            regular_grid,
        )

        lon, lat = np.meshgrid([0.5, 1.5, 2.5], [0.5, 1.5, 2.5])
        cx = pixel_corners(inferred_corner_grid(lon)).reshape(-1, 4)
        cy = pixel_corners(inferred_corner_grid(lat)).reshape(-1, 4)
        keep = np.ones(9, dtype=bool)
        keep[4] = False
        x, y = regular_grid((0, 3, 0, 3), 1)
        grid = overlap_mean(cx[keep], cy[keep], np.ones(8), x, y, 1)
        self.assertEqual(np.isfinite(grid).sum(), 8)
        self.assertTrue(np.isnan(grid[1, 1]))

    def test_display_changes_neither_support_nor_analysis_values(self):
        from rsplot.geo.footprints import (
            prepare_footprint_display,
            regular_grid,
        )

        lon, lat = regular_grid((113, 113.3, 22, 22.3), 0.05)
        values = np.full(lon.shape, 40.0)
        values[2:4, 2:4] = np.nan
        before = values.copy()
        region = box(113, 22, 113.3, 22.3)
        results = [
            prepare_footprint_display(
                lon,
                lat,
                values,
                region,
                analysis_res=0.05,
                display_res=res,
                smooth_sigma=1,
            )
            for res in [0.1, 0.075, 0.025]
        ]
        for result in results:
            self.assertTrue(result.support.equals(results[0].support))
            self.assertFalse(
                result.support.contains(box(113.11, 22.11, 113.19, 22.19))
            )
            np.testing.assert_array_equal(values, before)
            np.testing.assert_allclose(
                result.values[np.isfinite(result.values)], 40.0
            )
        self.assertNotEqual(results[0].values.shape, results[1].values.shape)

    def test_coarse_display_keeps_analysis_holes_visibly_empty(self):
        import cartopy.crs as ccrs
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap

        from rsplot.geo.footprints import (
            prepare_footprint_display,
            regular_grid,
        )
        from rsplot.plotting.map_frame import clip_raster_to_region

        lon, lat = regular_grid((0, 3, 0, 3), 0.5)
        values = np.ones(lon.shape)
        values[2:4, 2:4] = np.nan
        region = RegionInfo(
            "test",
            "city",
            box(0.1, 0.1, 2.9, 2.9),
            (0.1, 2.9, 0.1, 2.9),
            LEVEL_DEFAULTS["city"],
        )
        for projection in (ccrs.PlateCarree(), ccrs.Mercator()):
            for res in (1.5, 0.3):
                with self.subTest(
                    projection=type(projection).__name__, res=res
                ):
                    display = prepare_footprint_display(
                        lon,
                        lat,
                        values,
                        region.geometry,
                        analysis_res=0.5,
                        display_res=res,
                        smooth_sigma=1,
                    )
                    fig = plt.figure(figsize=(3, 3), dpi=100)
                    try:
                        ax = fig.add_axes([0, 0, 1, 1], projection=projection)
                        ax.set_extent([0, 3, 0, 3], crs=ccrs.PlateCarree())
                        mesh = ax.pcolormesh(
                            display.lon,
                            display.lat,
                            display.values,
                            shading="auto",
                            cmap=ListedColormap(["#0066cc"]),
                            transform=ccrs.PlateCarree(),
                        )
                        clip_raster_to_region(
                            mesh, ax, region, coverage_geometry=display.support
                        )
                        ax.axis("off")
                        fig.canvas.draw()
                        rgba = np.asarray(fig.canvas.buffer_rgba())
                        for x, y, blue in [
                            (1.5, 1.5, False),
                            (0.9, 1.5, True),
                            (2.5, 2.5, True),
                            (0.05, 0.5, False),
                        ]:
                            point = projection.transform_point(
                                x, y, ccrs.PlateCarree()
                            )
                            px, py = ax.transData.transform(point)
                            red = int(
                                rgba[
                                    rgba.shape[0] - 1 - round(py), round(px), 0
                                ]
                            )
                            self.assertEqual(red < 30, blue, (x, y, red))
                    finally:
                        plt.close(fig)

    def test_footprint_intersection_survives_an_exterior_center(self):
        with tempfile.TemporaryDirectory() as folder:
            make_scan(Path(folder))
            scan = next(
                GemsNO2Reader().iter_scans(
                    folder, "20260901", (115.2006, 115.2009, 30.2006, 30.2009)
                )
            )
            self.assertEqual(scan.n_pixels, 1)
            self.assertGreater(scan.lon[0], 115.2009)
            self.assertLess(scan.corner_lon[0].min(), 115.2009)

    def test_supplied_hcho_corners_take_precedence_and_qa_is_preserved(self):
        from rsplot.geo.footprints import inferred_corner_grid

        with tempfile.TemporaryDirectory() as folder:
            path = make_scan(Path(folder), product="hcho")
            with Dataset(path, "a") as ds:
                ds.createDimension("cy", 3)
                ds.createDimension("cx", 4)
                geo = ds["Geolocation Fields"]
                for name in ["Longitude", "Latitude"]:
                    values = inferred_corner_grid(np.array(geo[name][:]))
                    geo.createVariable("Corner" + name, "f8", ("cy", "cx"))[
                        :
                    ] = values
                ds["Data Fields/FinalAlgorithmFlags"][0, 1] = 2
            reader = get_product_info("hcho", sensor="gems").reader_cls()
            scan = next(reader.iter_scans(folder, "20260901", EXTENT))
            self.assertEqual(scan.n_pixels, 5)
            self.assertEqual(scan.corner_lon.shape, (5, 4))
            self.assertEqual(
                scan.metadata["footprint_source"], "file_corner_coordinates"
            )


if __name__ == "__main__":
    unittest.main()
