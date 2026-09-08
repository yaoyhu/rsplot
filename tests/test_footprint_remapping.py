"""Standalone area-remapping regressions; no satellite reader or data required."""

from __future__ import annotations

import unittest

import numpy as np
from shapely.geometry import box

from rsplot.geo.footprints import (
    inferred_corner_grid,
    overlap_mean,
    prepare_footprint_display,
    regular_grid,
)


class FootprintRemappingTests(unittest.TestCase):
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

    def test_empty_source_and_display_remain_empty(self):
        lon, lat = regular_grid((0, 1, 0, 1), 0.25)
        result = overlap_mean(
            np.empty((0, 4)), np.empty((0, 4)), np.empty(0), lon, lat, 0.25
        )
        self.assertTrue(np.isnan(result).all())
        display = prepare_footprint_display(
            lon,
            lat,
            result,
            box(0, 0, 1, 1),
            analysis_res=0.25,
            display_res=0.1,
            smooth_sigma=1,
        )
        self.assertTrue(display.support.is_empty)
        self.assertTrue(np.isnan(display.values).all())

    def test_missing_geolocation_is_not_interpolated(self):
        centers = np.arange(9, dtype=float).reshape(3, 3)
        centers[1, 1] = np.nan
        before = centers.copy()
        corners = inferred_corner_grid(centers)
        self.assertTrue(np.isnan(corners[1:3, 1:3]).all())
        np.testing.assert_array_equal(centers, before)


if __name__ == "__main__":
    unittest.main()
