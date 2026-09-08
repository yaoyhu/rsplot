"""Boundary rendering keeps overlaps while statistics select grid centers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cartopy.crs as ccrs
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from shapely.geometry import MultiPolygon, Polygon, box
from typer.testing import CliRunner

from rsplot.cli import app
from rsplot.config import LEVEL_DEFAULTS, AppConfig
from rsplot.geo.boundaries import RegionInfo
from rsplot.geo.processing import prepare_display_grid, prepare_existing_grid
from rsplot.plotting.map_frame import clip_raster_to_region
from rsplot.readers import get_product_info
from rsplot.readers.base import SwathData
from rsplot.result_builders.common import grid_boundary_policy
from rsplot.results import build_raster_result


class BoundaryGridTests(unittest.TestCase):
    def setUp(self):
        self.lon, self.lat = np.meshgrid([0.5, 1.5, 2.5, 3.5], [0.5, 1.5, 2.5])
        self.raw = np.arange(12, dtype=float).reshape(3, 4) + 1
        self.region = RegionInfo(
            "test",
            "city",
            box(0.7, 0.7, 2.8, 2.8),
            (0.7, 2.8, 0.7, 2.8),
            LEVEL_DEFAULTS["city"],
        )

    def test_overlap_cells_survive_without_entering_statistics(self):
        prepared = prepare_existing_grid(
            self.lon, self.lat, self.raw, self.region.geometry, fill_gaps=False
        )
        before = prepared.values.copy()
        display = prepare_display_grid(
            self.lon, self.lat, prepared.unmasked_values, self.region.geometry
        )
        self.assertTrue(np.isnan(prepared.values[0, 0]))
        self.assertEqual(display[0, 0], 1)
        self.assertTrue(np.isnan(display[:, 3]).all())
        np.testing.assert_array_equal(prepared.values, before)
        self.assertEqual(prepared.n_valid_region, 4)
        policy = grid_boundary_policy(self.lon, self.lat, display, self.region)
        self.assertEqual(policy["display"]["n_valid_intersecting_cells"], 9)
        self.assertEqual(policy["display"]["n_cells_with_centers_outside"], 5)
        result = build_raster_result(
            region=self.region,
            product="o3pr",
            date="20260907",
            prod_info=get_product_info("o3pr"),
            LON=self.lon,
            LAT=self.lat,
            grid=prepared.values,
            swath_meta={},
            vmin=0,
            vmax=20,
            output="test.png",
            display_grid=display,
        )
        self.assertEqual(result["stats"]["mean"], 8.5)
        self.assertEqual(result["stats"]["valid_region_pixels"], 4)
        self.assertEqual(result["boundary_policy"], policy)

    def test_display_smoothing_preserves_missing_cells_and_source(self):
        self.raw[1, 1] = np.nan
        before = self.raw.copy()
        display = prepare_display_grid(
            self.lon, self.lat, self.raw, self.region.geometry, smooth_sigma=1
        )
        self.assertTrue(np.isnan(display[1, 1]))
        self.assertTrue(np.isnan(display[:, 3]).all())
        self.assertTrue(np.isfinite(display[0, 0]))
        np.testing.assert_array_equal(self.raw, before)

    def test_center_exactly_on_boundary_is_excluded_from_statistics(self):
        geometry = box(0.5, 0.5, 2.5, 2.5)
        prepared = prepare_existing_grid(
            self.lon, self.lat, self.raw, geometry, fill_gaps=False
        )
        display = prepare_display_grid(self.lon, self.lat, self.raw, geometry)
        self.assertEqual(prepared.n_valid_region, 1)
        self.assertTrue(np.isfinite(display[0, 0]))
        self.assertTrue(np.isnan(prepared.values[0, 0]))

    def test_all_nan_stays_nan(self):
        display = prepare_display_grid(
            self.lon,
            self.lat,
            np.full(self.lon.shape, np.nan),
            self.region.geometry,
            smooth_sigma=1,
        )
        self.assertTrue(np.isnan(display).all())

    def test_descending_grid_and_holes(self):
        geometry = Polygon(
            [(0, 0), (4, 0), (4, 3), (0, 3)],
            holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
        )
        expected = prepare_display_grid(self.lon, self.lat, self.raw, geometry)
        actual = prepare_display_grid(
            self.lon[::-1, ::-1],
            self.lat[::-1, ::-1],
            self.raw[::-1, ::-1],
            geometry,
        )
        np.testing.assert_array_equal(actual, expected[::-1, ::-1])


class ClipRenderingTests(unittest.TestCase):
    def test_polygon_hole_island_and_projection(self):
        # Intentionally use the same ring direction; the clipper must orient holes.
        polygon = Polygon(
            [(1.2, 1.2), (3.7, 1.2), (3.7, 3.7), (1.2, 3.7)],
            holes=[[(2, 2), (3, 2), (3, 3), (2, 3)]],
        )
        geometry = MultiPolygon([polygon, box(4.2, 0.8, 4.8, 1.4)])
        region = RegionInfo(
            "clip", "city", geometry, (0, 6, 0, 5), LEVEL_DEFAULTS["city"]
        )
        lon, lat = np.meshgrid(np.arange(0.5, 6, 1), np.arange(0.5, 5, 1))
        for projection in (ccrs.PlateCarree(), ccrs.Mercator()):
            with self.subTest(projection=type(projection).__name__):
                fig = plt.figure(figsize=(6, 5), dpi=100)
                try:
                    ax = fig.add_axes([0, 0, 1, 1], projection=projection)
                    ax.set_extent([0, 6, 0, 5], crs=ccrs.PlateCarree())
                    mesh = ax.pcolormesh(
                        lon,
                        lat,
                        np.ones(lon.shape),
                        cmap=ListedColormap(["#0066cc"]),
                        shading="auto",
                        transform=ccrs.PlateCarree(),
                    )
                    clip_raster_to_region(mesh, ax, region)
                    ax.axis("off")
                    fig.canvas.draw()
                    rgba = np.asarray(fig.canvas.buffer_rgba())

                    def sample(x, y, projection=projection, ax=ax, rgba=rgba):
                        point = projection.transform_point(
                            x, y, ccrs.PlateCarree()
                        )
                        px, py = ax.transData.transform(point)
                        return rgba[
                            rgba.shape[0] - 1 - round(py), round(px), :3
                        ]

                    for point in ((1.3, 1.3), (3.5, 3.5), (4.5, 1.1)):
                        self.assertLess(int(sample(*point)[0]), 30, point)
                    for point in (
                        (1.1, 1.3),
                        (2.5, 2.5),
                        (4.1, 1.1),
                        (0.5, 0.5),
                    ):
                        self.assertGreater(int(sample(*point)[0]), 240, point)
                finally:
                    plt.close(fig)


class BoundaryCommandTests(unittest.TestCase):
    def test_tropomi_display_extension_preserves_legacy_statistics(self):
        from rsplot.geo.processing import prepare_swath_grid

        region = RegionInfo(
            "test",
            "city",
            box(0.7, 0.7, 2.8, 2.8),
            (0.7, 2.8, 0.7, 2.8),
            LEVEL_DEFAULTS["city"],
        )
        swath = SwathData(
            np.array([0.2, 1.2, 2.2]),
            np.array([0.2, 1.2, 2.2]),
            np.array([10.0, 20.0, 30.0]),
            3,
            1,
            0,
        )
        cfg = AppConfig(data_dirs={"no2": "unused"})
        legacy = prepare_swath_grid(
            swath.lon,
            swath.lat,
            swath.values,
            (-0.3, 3.8, -0.3, 3.8),
            1,
            region.geometry,
        )
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("rsplot.config.AppConfig.load", return_value=cfg),
            patch("rsplot.geo.boundaries.resolve_region", return_value=region),
            patch("rsplot.plotting.styles.setup_fonts"),
            patch(
                "rsplot.readers.tropomi_no2.TropomiNO2Reader.read",
                return_value=swath,
            ),
            patch("rsplot.plotting.raster.plot_raster") as render,
        ):
            out = Path(folder) / "tropomi.png"
            result = CliRunner().invoke(
                app,
                [
                    "raster",
                    "test",
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
                ],
            )
            self.assertEqual(
                result.exit_code, 0, result.output + str(result.exception)
            )
            data = json.loads(out.with_suffix(".json").read_text())
            self.assertEqual(
                data["stats"]["mean"],
                round(float(np.nanmean(legacy.values)), 2),
            )
            self.assertGreater(
                np.isfinite(render.call_args.args[2]).sum(),
                np.isfinite(legacy.values).sum(),
            )


if __name__ == "__main__":
    unittest.main()
