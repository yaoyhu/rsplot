"""JSON-sidecar construction for station and regional hourly trends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.readers.guokong import RegionStationSeries, StationSeries
from rsplot.result_builders.common import serialize_region
from rsplot.stats import basic_stats, round_finite

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo


def build_station_trend_result(
    *,
    series: StationSeries,
    dates: list[str],
    threshold: float | None,
    unit: str,
    output: str,
) -> dict[str, Any]:
    """Build the machine-readable payload for a single-station trend."""
    valid = np.isfinite(series.values)
    n_valid = int(valid.sum())
    result: dict[str, Any] = {
        "command": "trend",
        "image": output,
        "station": {
            "id": series.station_id,
            "lon": round(series.lon, 3),
            "lat": round(series.lat, 3),
        },
        "variable": series.var_name,
        "unit": unit or None,
        "threshold": threshold,
        "period": {
            "start": series.timestamps[0],
            "end": series.timestamps[-1],
            "days_requested": len(dates),
            "hours_requested": series.n_hours,
        },
        "availability": {
            "files_found": len(series.source_files),
            "files_missing": len(series.missing_files),
            "files_failed": len(series.failed_files),
            "hours_station_missing": len(series.station_missing_hours),
            "hours_valid": n_valid,
            "missing_file_hours": list(series.missing_files),
            "failed_files": dict(series.failed_files),
            "station_missing_hours": list(series.station_missing_hours),
        },
        "stats": basic_stats(series.values),
        "series": [
            {
                "datetime": timestamp,
                "value": round_finite(value),
            }
            for timestamp, value in zip(
                series.timestamps,
                series.values,
                strict=True,
            )
        ],
    }

    if threshold is not None and n_valid:
        exceed = int((series.values[valid] > threshold).sum())
        result["exceedance"] = {
            "count": exceed,
            "rate_pct": round(100 * exceed / n_valid, 1),
        }
    return result


def build_region_trend_result(
    *,
    series: RegionStationSeries,
    region: RegionInfo,
    dates: list[str],
    threshold: float | None,
    unit: str,
    view: str,
    focus_station_ids: list[str],
    output: str,
) -> dict[str, Any]:
    """Build the compact machine-readable payload for a regional trend."""
    mean_values = series.hourly_mean
    hourly_counts = series.hourly_valid_counts
    station_summaries: list[dict[str, Any]] = []
    exceeding_stations: list[dict[str, Any]] = []

    for index, station_id in enumerate(series.station_ids.astype(str)):
        values = series.values[index]
        summary: dict[str, Any] = {
            "id": station_id,
            "lon": round(float(series.lon[index]), 3),
            "lat": round(float(series.lat[index]), 3),
            "hours_valid": int(np.isfinite(values).sum()),
            "stats": basic_stats(values),
        }
        if threshold is not None and summary["hours_valid"]:
            exceedance = _exceedance_stats(values, threshold)
            summary["exceedance"] = exceedance
            if exceedance["count"]:
                exceeding_stations.append(
                    {
                        "id": station_id,
                        "lon": summary["lon"],
                        "lat": summary["lat"],
                        **exceedance,
                    }
                )
        station_summaries.append(summary)

    exceeding_stations.sort(
        key=lambda row: (
            -(row["max_excess"] or 0),
            -row["count"],
            row["id"],
        )
    )
    focus_stations = [
        _focus_station_result(series, station_id, threshold)
        for station_id in focus_station_ids
    ]

    return {
        "command": "trend",
        "mode": "region",
        "image": output,
        "region": serialize_region(region),
        "variable": series.var_name,
        "unit": unit or None,
        "threshold": threshold,
        "params": {
            "view": view,
            "focus_station_ids": focus_station_ids,
        },
        "period": {
            "start": series.timestamps[0],
            "end": series.timestamps[-1],
            "days_requested": len(dates),
            "hours_requested": series.n_hours,
        },
        "availability": {
            "files_found": len(series.source_files),
            "files_missing": len(series.missing_files),
            "files_failed": len(series.failed_files),
            "stations_total": series.n_stations,
            "stations_with_data": int(
                np.isfinite(series.values).any(axis=1).sum()
            ),
            "hours_with_data": int((hourly_counts > 0).sum()),
            "observation_values": series.n_valid,
            "missing_file_hours": list(series.missing_files),
            "failed_files": dict(series.failed_files),
        },
        "regional_mean": {
            "stats": basic_stats(mean_values),
            "series": [
                {
                    "datetime": timestamp,
                    "value": round_finite(value),
                    "n_stations": int(count),
                }
                for timestamp, value, count in zip(
                    series.timestamps,
                    mean_values,
                    hourly_counts,
                    strict=True,
                )
            ],
        },
        "station_summaries": station_summaries,
        "exceeding_stations": exceeding_stations,
        "focus_stations": focus_stations,
    }


def _focus_station_result(
    series: RegionStationSeries,
    station_id: str,
    threshold: float | None,
) -> dict[str, Any]:
    index = series.station_index(station_id)
    if index is None:
        raise ValueError(f"区域时序中未找到重点站 '{station_id}'")
    values = series.values[index]
    result: dict[str, Any] = {
        "id": str(series.station_ids[index]),
        "lon": round(float(series.lon[index]), 3),
        "lat": round(float(series.lat[index]), 3),
        "stats": basic_stats(values),
        "series": [
            {
                "datetime": timestamp,
                "value": round_finite(value),
            }
            for timestamp, value in zip(
                series.timestamps,
                values,
                strict=True,
            )
        ],
    }
    if threshold is not None and np.isfinite(values).any():
        result["exceedance"] = _exceedance_stats(values, threshold)
    return result


def _exceedance_stats(
    values: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    valid = np.isfinite(values)
    n_valid = int(valid.sum())
    exceed = valid & (values > threshold)
    count = int(exceed.sum())
    max_excess = (
        round_finite(np.max(values[exceed] - threshold)) if count else None
    )
    return {
        "count": count,
        "rate_pct": round(100 * count / n_valid, 1) if n_valid else 0.0,
        "max_excess": max_excess,
    }
