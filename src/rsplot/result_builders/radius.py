"""Radius-map sidecars with separate satellite and hourly-station semantics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.config import STATION_VAR_META
from rsplot.geo.radius import administrative_context
from rsplot.result_builders.common import member_basic_stats
from rsplot.result_builders.station import build_station_display
from rsplot.stats import round_finite

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData


def build_radius_result(
    raster_result: dict[str, Any],
    region: RegionInfo,
    data: StationData,
    center_id: str,
    km: float,
    distances: np.ndarray,
    source_file: str,
    matching: dict[str, Any],
    station_var: str | None,
) -> dict[str, Any]:
    """Extend the raster contract without combining column and surface data."""
    result = dict(raster_result)
    result["command"] = "radius"
    result["mode"] = "station_overlay" if station_var else "station_locations"
    center = int(np.flatnonzero(data.id == center_id)[0])
    result["radius"] = {
        "km": km,
        "distance_method": "WGS84_geodesic",
        "shape": "square",
        "km_semantics": "center_to_each_side",
        "side_length_km": 2 * km,
        "geometry_projection": "station_centered_WGS84_AEQD",
        "center": {
            "id": center_id,
            "lon": float(data.lon[center]),
            "lat": float(data.lat[center]),
        },
    }
    result["administrative_context"] = administrative_context(
        region,
        float(data.lon[center]),
        float(data.lat[center]),
    )
    result["time_matching"] = matching
    rows = []
    for index, station_id in enumerate(data.id):
        row = {
            "id": str(station_id),
            "lon": float(data.lon[index]),
            "lat": float(data.lat[index]),
            "distance_km": round_finite(distances[index], 6),
            "is_center": station_id == center_id,
        }
        if station_var:
            row["value"] = round_finite(data.values[index])
            row["missing"] = not bool(np.isfinite(data.values[index]))
        rows.append(row)
    result["stations"] = {
        "source_file": source_file,
        "datetime": matching["station_datetime"],
        "timezone": "Asia/Shanghai",
        "aggregation": "single_hour" if station_var else "locations_only",
        "variable": station_var,
        "unit": STATION_VAR_META[station_var][0] if station_var else None,
        "count": data.n_stations,
        "items": rows,
    }
    if station_var:
        display = build_station_display(data)
        if display is not None:
            result["stations"]["display"] = display
        result["stations"]["stats"] = {
            "n_valid": data.n_valid,
            "n_missing": data.n_stations - data.n_valid,
            **member_basic_stats(data.values),
        }
    if not result["stats"].get("valid_region_pixels"):
        result["stats"] = {
            **result["stats"],
            **member_basic_stats(np.array([])),
        }
    return result
