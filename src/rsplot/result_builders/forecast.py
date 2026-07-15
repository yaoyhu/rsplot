"""Forecast JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.common import (
    grid_per_admin_stats,
    serialize_region,
    top_hotspots,
)
from rsplot.result_builders.station import build_station_result
from rsplot.stats import basic_stats, round_finite
from rsplot.temporal import DEFAULT_INPUT_TIMEZONE

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.forecast import ForecastData
    from rsplot.readers.guokong import StationData


def build_forecast_result(
    *,
    region: RegionInfo,
    data: ForecastData,
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    vmin: float,
    vmax: float,
    output: str,
    station_data: StationData | None = None,
    station_datetime: str | None = None,
    station_threshold: float | None = None,
    station_unit: str = "",
    cities_gdf: gpd.GeoDataFrame | None = None,
) -> dict[str, Any]:
    """Build the stable JSON sidecar payload for a forecast run."""
    from rsplot.geo.gridding import grid_coverage_in_region

    coverage, n_valid, total = grid_coverage_in_region(
        LON,
        LAT,
        grid,
        region.geometry,
    )
    result: dict[str, Any] = {
        "command": "forecast",
        "mode": (
            "forecast_station_overlay"
            if station_data is not None
            else "forecast"
        ),
        "image": output,
        "region": serialize_region(region),
        "variable": data.variable,
        "label": data.label,
        "unit": data.unit,
        "forecast": {
            "source": "forecast",
            "init_datetime": data.init_datetime,
            "timezone": DEFAULT_INPUT_TIMEZONE,
            "lead_hour": data.lead_hour,
            "valid_datetime": data.valid_datetime,
            "archive_timezone": data.archive_timezone,
            "archive_init_datetime": data.archive_init_datetime,
            "archive_valid_datetime": data.archive_valid_datetime,
            "source_file": data.source_file,
        },
        "vrange": {
            "vmin": round_finite(vmin),
            "vmax": round_finite(vmax),
        },
        "stats": {
            "grid_shape": list(grid.shape),
            "coverage_pct": coverage,
            "n_region_cells": total,
            "n_valid": n_valid,
            "n_read_cells": int(data.n_cells),
            "n_read_valid": int(data.n_valid),
            **basic_stats(grid),
        },
    }

    if station_data is not None:
        station_block = build_station_result(
            region=region,
            data=station_data,
            datetime_str=station_datetime or data.valid_datetime,
            threshold=station_threshold,
            unit=station_unit,
            cities_gdf=cities_gdf,
            output=output,
        )
        for key in ("command", "image", "region"):
            station_block.pop(key, None)
        result["station"] = station_block

    sub_gdf = region.sub_boundary_gdf
    if sub_gdf is not None and len(sub_gdf) > 0:
        result["spatial_summary"] = grid_per_admin_stats(
            LON,
            LAT,
            grid,
            sub_gdf,
        )
        result["hotspots"] = top_hotspots(LON, LAT, grid, sub_gdf, n=5)

    return result
