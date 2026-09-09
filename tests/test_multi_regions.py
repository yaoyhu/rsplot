"""Comma-selected regions: parsing, shared-grid statistics and rendering."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import geopandas as gpd
import numpy as np
from shapely.geometry import Point, Polygon, box
from typer.testing import CliRunner

from rsplot.cli import app
from rsplot.config import AppConfig
from rsplot.geo.boundaries import resolve_region, resolve_regions
from rsplot.geo.gridding import mask_to_region
from rsplot.readers import get_product_info
from rsplot.readers.base import SwathData
from rsplot.readers.guokong import StationData, mask_stations_to_region
from rsplot.result_builders.common import serialize_region
from rsplot.result_builders.overlay import build_overlay_result
from rsplot.result_builders.raster import build_raster_result

SELECTION = "中山市/东区街道,中山市/南区街道,中山市/石岐街道"


class RegionFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cfg = AppConfig(
            geojson_dir="/fixture",
            data_dirs={
                "no2": "/unused",
                "gems_o3": "/unused",
                "guokong": "/unused",
            },
        )
        self.provinces = gpd.GeoDataFrame(
            {"name": ["广东省", "福建省"]},
            geometry=[box(0, 0, 6, 4), box(8, 0, 12, 4)],
            crs=4326,
        )
        self.cities = gpd.GeoDataFrame(
            {"name": ["中山市", "珠海市", "厦门市"]},
            geometry=[box(0, 0, 4, 4), box(4, 0, 6, 4), box(8, 0, 12, 4)],
            crs=4326,
        )
        self.counties = gpd.GeoDataFrame(
            {"name": ["东区街道", "南区街道", "石岐街道", "东区街道"]},
            geometry=[
                box(0.1, 0.1, 1, 1.9),
                box(1, 0.1, 2, 1.9),
                box(3, 0.1, 3.9, 1.9),
                box(8.1, 0.1, 9, 1.9),
            ],
            crs=4326,
        )
        for name, data in [
            ("province", self.provinces),
            ("city", self.cities),
            ("county", self.counties),
        ]:
            self.stack.enter_context(
                patch("rsplot.geo.boundaries._load_" + name, return_value=data)
            )
        self.stack.enter_context(
            patch(
                "rsplot.geo.boundaries._city_subdivisions",
                side_effect=lambda name, *_: (
                    (self.counties.iloc[:3], "township")
                    if name == "中山市"
                    else None
                ),
            )
        )


class ParsingTests(RegionFixture):
    def test_streets_commas_newlines_aliases_and_order(self):
        region = resolve_regions(
            " 中山/东区， 中山市/南区街道,中山\n市/石岐街道,中山市/东区街道 ",
            self.cfg,
        )
        self.assertEqual(region.name, "联合区域（3个）")
        self.assertEqual(region.level, "county")
        self.assertEqual(
            [m.qualified_name for m in region.members], SELECTION.split(",")
        )
        self.assertEqual(region.members[0].administrative_level, "township")
        self.assertFalse(region.geometry.contains(Point(2.5, 1)))
        self.assertEqual(len(region.main_boundary_gdf), 3)
        self.assertAlmostEqual(region.extent[0], 0.1)
        self.assertAlmostEqual(region.extent[1], 3.9)

    def test_multi_provinces_cities_and_mixed_levels(self):
        for names, level in [
            ("广东省,福建省", "province"),
            ("中山,珠海", "city"),
            ("广东省,厦门市,中山市/东区街道", "province"),
        ]:
            with self.subTest(names=names):
                region = resolve_regions(names, self.cfg)
                self.assertEqual(region.level, level)
                self.assertEqual(len(region.members), len(names.split(",")))
                self.assertFalse(region.geometry.contains(Point(7, 1)))
        repeated = resolve_regions("中山,中山市", self.cfg)
        self.assertEqual(len(repeated.members), 1)

    def test_same_leaf_names_are_qualified(self):
        region = resolve_regions("中山/东区,厦门/东区", self.cfg)
        self.assertEqual(
            [m["name"] for m in serialize_region(region)["members"]],
            ["中山市/东区街道", "厦门市/东区街道"],
        )

    def test_invalid_and_empty_members_fail_without_partial_selection(self):
        for name in [
            ",中山",
            "中山,",
            "中山，，珠海",
            "中山,不存在",
            "中山/石歧区街道,珠海",
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve_regions(name, self.cfg)
        with self.assertRaisesRegex(ValueError, "第 2 个区域"):
            resolve_regions("中山,不存在", self.cfg)

    def test_single_region_and_override_keep_existing_behavior(self):
        for name, level in [
            ("中山", None),
            ("广东", "province"),
            ("中山/东区", "county"),
        ]:
            old = resolve_region(name, self.cfg, level)
            new = resolve_regions(name, self.cfg, level)
            self.assertEqual(serialize_region(new), serialize_region(old))
            self.assertTrue(new.geometry.equals(old.geometry))
            self.assertNotIn("members", serialize_region(new))
        self.assertEqual(
            resolve_regions("中山,珠海", self.cfg, "city").level, "city"
        )
        with self.assertRaises(ValueError):
            resolve_regions("广东,福建", self.cfg, "city")
        with self.assertRaises(ValueError):
            resolve_region("中山,珠海", self.cfg)

    def test_nested_members_do_not_duplicate_union_or_subdivisions(self):
        region = resolve_regions("广东省,中山市", self.cfg)
        self.assertTrue(
            region.geometry.equals(self.provinces.geometry.iloc[0])
        )
        self.assertEqual(len(region.members), 2)
        for frame in [region.sub_boundary_gdf, region.detail_boundary_gdf]:
            if frame is not None:
                self.assertFalse(frame.geometry.to_wkb().duplicated().any())
                self.assertTrue(
                    frame.geometry.map(region.geometry.covers).all()
                )


class StatisticsTests(RegionFixture):
    def raster_result(self, region, raw):
        lon, lat = np.meshgrid([0.5, 1.5, 2.5, 3.5], [0.5, 1.5])
        return build_raster_result(
            region=region,
            product="no2",
            date="20260907",
            prod_info=get_product_info("no2"),
            LON=lon,
            LAT=lat,
            grid=mask_to_region(lon, lat, raw, region.geometry),
            swath_meta={},
            vmin=0,
            vmax=100,
            output="test.png",
        )

    def test_shared_grid_union_and_empty_member(self):
        region = resolve_regions(SELECTION, self.cfg)
        raw = np.array([[1, 2, 100, np.nan], [5, 6, 100, np.nan]])
        result = self.raster_result(region, raw)
        self.assertEqual(result["stats"]["n"], 4)
        self.assertEqual(result["stats"]["mean"], 3.5)
        members = result["member_stats"]
        self.assertEqual([m["stats"]["mean"] for m in members], [3, 4, None])
        self.assertEqual(members[2]["stats"]["valid_region_pixels"], 0)
        self.assertEqual(members[2]["stats"]["total_region_pixels"], 2)
        self.assertEqual(members[2]["stats"]["n"], 0)
        self.assertNotIn("spatial_summary", result)

    def test_parent_child_totals_are_not_added(self):
        region = resolve_regions("广东省,中山市", self.cfg)
        result = self.raster_result(region, np.ones((2, 4)))
        self.assertEqual(result["stats"]["n"], 8)
        self.assertEqual(
            [m["stats"]["n"] for m in result["member_stats"]], [8, 8]
        )
        self.assertIn("spatial_summary", result)

    def test_member_with_no_analysis_center_is_retained(self):
        self.counties.loc[2, "geometry"] = box(3.1, 0.1, 3.2, 0.2)
        region = resolve_regions(SELECTION, self.cfg)
        result = self.raster_result(region, np.ones((2, 4)))
        empty = result["member_stats"][2]["stats"]
        self.assertEqual(empty["total_region_pixels"], 0)
        self.assertEqual(empty["n"], 0)
        self.assertIsNone(empty["mean"])

    def test_member_centers_on_shared_boundary_are_excluded(self):
        region = resolve_regions("中山/东区,中山/南区", self.cfg)
        lon, lat = np.meshgrid([0.5, 1, 1.5], [0.5, 1.5])
        result = build_raster_result(
            region=region,
            product="no2",
            date="20260907",
            prod_info=get_product_info("no2"),
            LON=lon,
            LAT=lat,
            grid=np.ones(lon.shape),
            swath_meta={},
            vmin=0,
            vmax=2,
            output="test.png",
        )
        self.assertEqual(result["stats"]["valid_region_pixels"], 6)
        self.assertEqual(
            [
                m["stats"]["valid_region_pixels"]
                for m in result["member_stats"]
            ],
            [2, 2],
        )

    def test_overlay_station_union_member_counts_and_nulls(self):
        region = resolve_regions(SELECTION, self.cfg)
        stations = StationData(
            np.array(["a", "b", "gap", "c"]),
            np.array([0.5, 1.5, 2.5, 3.5]),
            np.full(4, 0.5),
            np.array([10, 20, 999, np.nan]),
            "NO2",
            4,
            3,
        )
        stations = mask_stations_to_region(stations, region.geometry)
        lon, lat = np.meshgrid([0.5, 1.5, 2.5, 3.5], [0.5, 1.5])
        result = build_overlay_result(
            region=region,
            product="no2",
            date="20260907",
            prod_info=get_product_info("no2"),
            LON=lon,
            LAT=lat,
            grid=mask_to_region(lon, lat, np.ones(lon.shape), region.geometry),
            swath_meta={},
            raster_vmin=0,
            raster_vmax=2,
            data=stations,
            datetime_str="2026090719",
            threshold=200,
            unit="unit",
            cities_gdf=None,
            output="test.png",
        )
        self.assertEqual(result["station"]["n_stations"], 3)
        self.assertEqual(result["station"]["stats"]["mean"], 15)
        stats = result["station"]["member_stats"]
        self.assertEqual([m["stats"]["mean"] for m in stats], [10, 20, None])
        self.assertEqual(stats[2]["n_valid"], 0)
        self.assertEqual(len(result["raster"]["member_stats"]), 3)


class RenderingTests(RegionFixture):
    def test_selected_labels_and_automatic_ticks(self):
        from rsplot.plotting.map_frame import (
            add_region_boundaries,
            configure_map_axes,
        )

        region = resolve_regions(SELECTION, self.cfg)
        ax = Mock()
        add_region_boundaries(ax, region)
        self.assertEqual(
            [c.args[2] for c in ax.text.call_args_list],
            ["东区街道", "南区街道", "石岐街道"],
        )
        configure_map_axes(ax, region, use_basemap=True)
        import matplotlib.ticker as mticker

        self.assertIsInstance(
            ax.gridlines.return_value.xlocator, mticker.MaxNLocator
        )
        region = resolve_regions("中山/东区,厦门/东区", self.cfg)
        ax.reset_mock()
        add_region_boundaries(ax, region)
        self.assertEqual(
            [c.args[2] for c in ax.text.call_args_list],
            ["中山市/东区街道", "厦门市/东区街道"],
        )

    def test_selected_subdivision_is_not_drawn_or_labeled_twice(self):
        from rsplot.plotting.map_frame import add_region_boundaries

        region = resolve_regions("广东省,中山市", self.cfg)
        ax = Mock()
        add_region_boundaries(ax, region)
        geometries = [
            g
            for call in ax.add_feature.call_args_list
            for g in call.args[0].geometries()
        ]
        city = region.members[1].geometry
        self.assertEqual(sum(g.equals(city) for g in geometries), 1)
        self.assertEqual(
            sum(call.args[2] == "中山市" for call in ax.text.call_args_list), 1
        )

    def test_disconnected_union_and_hole_are_clipped(self):
        import cartopy.crs as ccrs
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap

        from rsplot.plotting.map_frame import clip_raster_to_region

        self.counties.loc[0, "geometry"] = Polygon(
            [(0, 0), (2, 0), (2, 2), (0, 2)],
            holes=[[(0.5, 0.5), (1, 0.5), (1, 1), (0.5, 1)]],
        )
        region = resolve_regions("中山/东区,中山/石岐", self.cfg)
        lon, lat = np.meshgrid(
            np.arange(0.25, 4, 0.5), np.arange(0.25, 2, 0.5)
        )
        for projection in [ccrs.PlateCarree(), ccrs.Mercator()]:
            fig = plt.figure(figsize=(4, 2), dpi=100)
            try:
                ax = fig.add_axes([0, 0, 1, 1], projection=projection)
                ax.set_extent([0, 4, 0, 2], crs=ccrs.PlateCarree())
                mesh = ax.pcolormesh(
                    lon,
                    lat,
                    np.ones(lon.shape),
                    shading="auto",
                    cmap=ListedColormap(["#0066cc"]),
                    transform=ccrs.PlateCarree(),
                )
                clip_raster_to_region(mesh, ax, region)
                ax.axis("off")
                fig.canvas.draw()
                rgba = np.asarray(fig.canvas.buffer_rgba())
                for x, y, blue in [
                    (0.25, 0.25, True),
                    (0.75, 0.75, False),
                    (2.5, 1, False),
                    (3.5, 1, True),
                ]:
                    xy = projection.transform_point(x, y, ccrs.PlateCarree())
                    px, py = ax.transData.transform(xy)
                    self.assertEqual(
                        int(rgba[rgba.shape[0] - 1 - round(py), round(px), 0])
                        < 30,
                        blue,
                    )
            finally:
                plt.close(fig)


class CommandTests(RegionFixture):
    def setUp(self):
        super().setUp()
        self.folder = Path(
            self.stack.enter_context(tempfile.TemporaryDirectory())
        )
        self.stack.enter_context(
            patch("rsplot.config.AppConfig.load", return_value=self.cfg)
        )
        self.stack.enter_context(patch("rsplot.plotting.styles.setup_fonts"))
        self.plot = self.stack.enter_context(
            patch("rsplot.plotting.raster.plot_raster")
        )
        self.overlay = self.stack.enter_context(
            patch("rsplot.plotting.overlay.plot_overlay")
        )
        swath = SwathData(
            np.array([0.5, 1.5, 3.5]),
            np.array([0.5, 0.5, 0.5]),
            np.array([10, 20, 30]),
            3,
            1,
            0,
        )
        self.reader = self.stack.enter_context(
            patch(
                "rsplot.readers.tropomi_no2.TropomiNO2Reader.read",
                return_value=swath,
            )
        )
        stations = StationData(
            np.array(["a", "b", "gap", "c"]),
            np.array([0.5, 1.5, 2.5, 3.5]),
            np.full(4, 0.5),
            np.array([10, 20, 999, 30]),
            "NO2",
            4,
            4,
        )
        self.stations = self.stack.enter_context(
            patch(
                "rsplot.readers.guokong.read_stations",
                return_value=(stations, "2026090719"),
            )
        )

    def invoke(self, command, *args, region=SELECTION):
        out = self.folder / (command + ".png")
        result = CliRunner().invoke(
            app,
            [
                command,
                region,
                "20260907",
                "-p",
                "no2",
                "--res",
                "1",
                "--smooth",
                "0",
                "--basemap",
                "none",
                "--output",
                str(out),
                *args,
            ],
        )
        self.assertEqual(
            result.exit_code, 0, result.output + str(result.exception)
        )
        return json.loads(out.with_suffix(".json").read_text())

    def test_tropomi_raster_overlay_share_selection_and_read_once(self):
        raster = self.invoke("raster")
        self.reader.assert_called_once()
        self.assertEqual(len(raster["member_stats"]), 3)
        self.reader.reset_mock()
        overlay = self.invoke("overlay")
        self.reader.assert_called_once()
        self.stations.assert_called_once()
        self.assertEqual(overlay["region"], raster["region"])
        self.assertEqual(overlay["station"]["n_stations"], 3)
        self.assertEqual(self.overlay.call_args.args[3].n_stations, 3)

    def test_gems_daily_overlay_uses_selected_resolution(self):
        from rsplot.geo.footprints import regular_grid
        from rsplot.temporal import ScanMean

        def scan_mean(**kwargs):
            res = kwargs["res"]
            lon, lat = regular_grid((0, 4, 0, 2), res)
            return ScanMean(
                lon,
                lat,
                np.full(lon.shape, 40.0),
                np.ones(lon.shape, dtype=int),
                30,
                8,
                0,
                {"request": "20260907", "analysis_resolution_deg": res},
            )

        with patch(
            "rsplot.temporal.read_scan_mean", side_effect=scan_mean
        ) as scan:
            results = [
                self.invoke(
                    "raster", "--sensor", "gems", "-p", "o3pr", "--res", res
                )
                for res in [".1", ".075"]
            ]
            self.assertEqual(scan.call_count, 2)
            self.assertEqual(
                [call.kwargs["res"] for call in scan.call_args_list],
                [0.1, 0.075],
            )
            self.assertNotEqual(
                results[0]["stats"]["total_region_pixels"],
                results[1]["stats"]["total_region_pixels"],
            )
            scan.reset_mock()
            overlay = self.invoke(
                "overlay",
                "--sensor",
                "gems",
                "-p",
                "o3pr",
                "--station-datetime",
                "2026090719",
                "--res",
                ".075",
            )
            scan.assert_called_once()
            self.assertEqual(self.stations.call_args.args[1], "2026090719")
            self.assertEqual(
                overlay["raster"]["member_stats"], results[1]["member_stats"]
            )
            self.assertEqual(
                overlay["time_matching"]["satellite_aggregation"], "daily_mean"
            )
            self.assertTrue(
                self.plot.call_args.kwargs["coverage_geometry"].equals(
                    self.overlay.call_args.kwargs["coverage_geometry"]
                )
            )

    def test_invalid_selection_stops_before_reading(self):
        result = CliRunner().invoke(
            app, ["raster", "中山,不存在", "20260907", "-p", "no2"]
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("第 2 个区域", result.output)
        self.reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
