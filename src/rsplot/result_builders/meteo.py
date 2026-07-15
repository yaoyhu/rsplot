"""Meteorological map JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.common import serialize_region
from rsplot.result_builders.station import build_station_result
from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.era5 import Era5FieldData
    from rsplot.readers.era5_wind import WindFieldData
    from rsplot.readers.guokong import StationData


def build_wind_block(wind: WindFieldData, stride: int) -> dict[str, Any]:
    """Build machine-readable metadata for a plotted ERA5 wind layer."""
    step = max(1, stride)
    sample = np.s_[::step, ::step]
    sampled_valid = np.isfinite(wind.speed[sample])
    finite = np.isfinite(wind.speed)
    total = wind.n_cells

    mean_u = float(np.nanmean(wind.u))
    mean_v = float(np.nanmean(wind.v))
    direction_to = (np.degrees(np.arctan2(mean_u, mean_v)) + 360.0) % 360.0
    direction_from = (direction_to + 180.0) % 360.0

    max_flat_index = int(np.nanargmax(wind.speed))
    max_index = np.unravel_index(max_flat_index, wind.speed.shape)
    return {
        "source": "ERA5",
        "level": wind.level,
        "station_datetime": wind.station_datetime,
        "datetime_utc": wind.datetime_utc,
        "unit": wind.unit,
        "source_files": list(wind.source_files),
        "grid_shape": list(wind.speed.shape),
        "coverage_pct": (
            round(100 * int(finite.sum()) / total, 1) if total else 0.0
        ),
        "n_region_cells": int(total),
        "stride": step,
        "n_vectors_valid": int(finite.sum()),
        "n_arrows_plotted": int(sampled_valid.sum()),
        "display": {"color": "black", "colorbar": False},
        "u_stats": basic_stats(wind.u),
        "v_stats": basic_stats(wind.v),
        "speed_stats": basic_stats(wind.speed),
        "resultant": {
            "mean_u": round_finite(mean_u),
            "mean_v": round_finite(mean_v),
            "direction_to_deg": round_finite(direction_to, 1),
            "wind_from_deg": round_finite(direction_from, 1),
        },
        "max_speed_location": {
            "lon": round(float(wind.lon[max_index]), 3),
            "lat": round(float(wind.lat[max_index]), 3),
            "speed": round_finite(wind.speed[max_index]),
        },
    }


def build_meteo_result(
    *,
    region: RegionInfo,
    variable: str,
    input_datetime: str,
    input_timezone: str,
    datetime_utc: str,
    output: str,
    requested_datetime: str | None = None,
    field: Era5FieldData | None = None,
    field_cmap: str | None = None,
    field_vmin: float | None = None,
    field_vmax: float | None = None,
    wind: WindFieldData | None = None,
    wind_stride: int | None = None,
    station: StationData | None = None,
    station_datetime: str | None = None,
    station_threshold: float | None = None,
    station_unit: str = "",
    cities_gdf: gpd.GeoDataFrame | None = None,
) -> dict[str, Any]:
    """Build the stable machine-readable result for ``meteo``."""
    mode = _meteo_mode(field=field, wind=wind, station=station)
    primary_level = field.level if field is not None else wind.level
    primary_unit = field.unit if field is not None else wind.unit
    result: dict[str, Any] = {
        "command": "meteo",
        "mode": mode,
        "image": output,
        "region": serialize_region(region),
        "datetime": input_datetime,
        "requested_datetime": requested_datetime or input_datetime,
        "timezone": input_timezone,
        "datetime_utc": datetime_utc,
        "variable": variable,
        "level": primary_level,
        "unit": primary_unit,
    }

    if field is not None:
        total = field.n_cells
        result["field"] = {
            "variable": field.variable,
            "level": field.level,
            "unit": field.unit,
            "source_file": field.source_file,
            "grid_shape": list(field.values.shape),
            "coverage_pct": (
                round(100 * field.n_valid / total, 1) if total else 0.0
            ),
            "n_region_cells": total,
            "n_valid": field.n_valid,
            "stats": basic_stats(field.values),
            "display": {
                "cmap": field_cmap,
                "vmin": (
                    round_finite(field_vmin)
                    if field_vmin is not None
                    else None
                ),
                "vmax": (
                    round_finite(field_vmax)
                    if field_vmax is not None
                    else None
                ),
                "range_method": "manual_or_region_p02_p98",
            },
        }

    if wind is not None:
        result["wind"] = build_wind_block(wind, wind_stride or 1)

    if station is not None:
        station_block = build_station_result(
            region=region,
            data=station,
            datetime_str=station_datetime or input_datetime,
            threshold=station_threshold,
            unit=station_unit,
            cities_gdf=cities_gdf,
            output=output,
        )
        for key in ("command", "image", "region"):
            station_block.pop(key, None)
        result["station"] = station_block

    return result


def _meteo_mode(
    *,
    field: Era5FieldData | None,
    wind: WindFieldData | None,
    station: StationData | None,
) -> str:
    if station is not None and field is not None:
        return "temperature_station_wind"
    if station is not None:
        return "station_wind"
    if field is not None and wind is not None:
        return "temperature_wind"
    return "temperature" if field is not None else "wind"
