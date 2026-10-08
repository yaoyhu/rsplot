"""Hourly ``series`` layers for station and regional trends."""

from __future__ import annotations

from typing import Any

import numpy as np

from rsplot.result_builders.envelope import (
    capped,
    coverage_block,
    flag,
    stats_block,
)
from rsplot.stats import round_finite

COMPLETE_HOURS = 0.90
MIN_STATIONS = 3


def series_time(dates: list[str]) -> dict[str, Any]:
    return {
        "aggregation": "hourly_series",
        "start": dates[0],
        "end": dates[-1],
        "basis": "station_hour",
    }


def series_quantity(var: str, unit: str) -> dict[str, Any]:
    return {
        "name": var,
        "unit": unit or "1",
        "scale": 1,
        "label": f"{var} ({unit})" if unit else var,
    }


def exceedance_block(
    values: np.ndarray, threshold: float | None, standard: str | None
) -> dict[str, Any] | None:
    if threshold is None:
        return None
    finite = values[np.isfinite(values)]
    count = int((finite > threshold).sum())
    return {
        "threshold": threshold,
        "operator": ">",
        "standard": standard,
        "count": count,
        "fraction": round(count / finite.size, 3) if finite.size else None,
    }


def missing_hours_flag(layer_id: str, coverage: dict) -> list[dict]:
    fraction = coverage["fraction"]
    if fraction is None or fraction >= COMPLETE_HOURS:
        return []
    return [
        flag(
            "missing_hours",
            "warning",
            layer=layer_id,
            evidence={**coverage, "threshold": COMPLETE_HOURS},
        )
    ]


def daily_rows(
    timestamps: list[str], values: np.ndarray
) -> list[dict[str, Any]]:
    """One row per China-time day: valid hours, mean, min and max."""
    days: dict[str, list[float]] = {}
    for stamp, value in zip(timestamps, values, strict=True):
        days.setdefault(stamp[:8], []).append(float(value))
    rows = []
    for date, day_values in days.items():
        finite = np.asarray(day_values)[np.isfinite(day_values)]
        empty = finite.size == 0
        rows.append(
            {
                "date": date,
                "hours": int(finite.size),
                "mean": None if empty else round_finite(np.mean(finite)),
                "min": None if empty else round_finite(np.min(finite)),
                "max": None if empty else round_finite(np.max(finite)),
            }
        )
    return rows


def diurnal_rows(
    timestamps: list[str], values: np.ndarray
) -> list[dict[str, Any]]:
    """One row per China-time hour of day: valid days and their mean."""
    hours = np.array([int(stamp[8:10]) for stamp in timestamps])
    rows = []
    for hour in range(24):
        selected = values[hours == hour]
        finite = selected[np.isfinite(selected)]
        rows.append(
            {
                "hour": hour,
                "days": int(finite.size),
                "mean": round_finite(np.mean(finite)) if finite.size else None,
            }
        )
    return rows


def station_series_layer(
    *,
    station_id: str,
    var: str,
    unit: str,
    timestamps: list[str],
    values: np.ndarray,
    dates: list[str],
    source: dict[str, Any],
    threshold: float | None,
    standard: str | None,
    data: str,
) -> tuple[dict[str, Any], list[dict]]:
    """One station's hours as a ``series`` layer."""
    valid = np.isfinite(values)
    coverage = coverage_block(int(valid.sum()), len(values), "hours")
    order = np.flatnonzero(valid)[np.argsort(values[valid])[::-1]]
    layer: dict[str, Any] = {
        "id": "station",
        "kind": "series",
        "subject": {"station_id": station_id},
        "quantity": series_quantity(var, unit),
        "time": series_time(dates),
        "source": source,
        "method": {"gaps": "kept_as_missing", "hours_per_day": 24},
        "coverage": coverage,
        "stats": stats_block(values),
        "daily": daily_rows(timestamps, values),
        "diurnal": diurnal_rows(timestamps, values),
        "by_admin": [],
        "extremes": capped(
            [
                {
                    "datetime": timestamps[index],
                    "value": round_finite(values[index]),
                }
                for index in order
            ],
            coverage["valid"],
            "value_desc",
        ),
        "data": data,
    }
    exceedance = exceedance_block(values, threshold, standard)
    if exceedance is not None:
        layer["exceedance"] = exceedance
    flags = missing_hours_flag("station", coverage)
    if source["failed_files"]:
        flags.append(
            flag(
                "failed_files",
                "warning",
                layer="station",
                evidence={"count": len(source["failed_files"])},
            )
        )
    return layer, flags


def region_series_layers(
    *,
    station_ids: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    var: str,
    unit: str,
    timestamps: list[str],
    values: np.ndarray,
    mean: np.ndarray,
    counts: np.ndarray,
    dates: list[str],
    source: dict[str, Any],
    threshold: float | None,
    standard: str | None,
    data: str,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """The hourly regional mean and every station's hours."""
    quantity = series_quantity(var, unit)
    time = series_time(dates)
    mean_coverage = coverage_block(
        int((counts > 0).sum()), len(counts), "hours"
    )
    mean_valid = np.isfinite(mean)
    mean_order = np.flatnonzero(mean_valid)[np.argsort(mean[mean_valid])[::-1]]
    regional: dict[str, Any] = {
        "id": "regional_mean",
        "kind": "series",
        "quantity": quantity,
        "time": time,
        "source": source,
        "method": {
            "aggregation": "mean_over_stations_with_value",
            "gaps": "kept_as_missing",
        },
        "coverage": mean_coverage,
        "stats": stats_block(mean),
        "daily": daily_rows(timestamps, mean),
        "diurnal": diurnal_rows(timestamps, mean),
        "by_admin": [],
        "extremes": capped(
            [
                {
                    "datetime": timestamps[index],
                    "value": round_finite(mean[index]),
                    "n_stations": int(counts[index]),
                }
                for index in mean_order
            ],
            mean_coverage["valid"],
            "value_desc",
        ),
        "data": data,
    }
    mean_exceedance = exceedance_block(mean, threshold, standard)
    if mean_exceedance is not None:
        regional["exceedance"] = mean_exceedance

    has_data = np.isfinite(values).any(axis=1)
    station_rows = []
    for index in np.flatnonzero(has_data):
        row_values = values[index]
        finite = row_values[np.isfinite(row_values)]
        item: dict[str, Any] = {
            "id": str(station_ids[index]),
            "lon": round(float(lon[index]), 3),
            "lat": round(float(lat[index]), 3),
            "value": round_finite(np.max(finite)),
            "mean": round_finite(np.mean(finite)),
            "hours_valid": int(finite.size),
        }
        if threshold is not None:
            item["n_exceed"] = int((finite > threshold).sum())
        station_rows.append(item)
    station_rows.sort(key=lambda row: -(row["value"] or 0))
    station_coverage = coverage_block(
        int(has_data.sum()), len(station_ids), "stations"
    )
    stations: dict[str, Any] = {
        "id": "station",
        "kind": "series",
        "quantity": quantity,
        "time": time,
        "source": source,
        "method": {
            "region_selection": "point_inside_region",
            "gaps": "kept_as_missing",
        },
        "coverage": station_coverage,
        "stats": stats_block(values),
        "by_admin": [],
        "extremes": capped(
            station_rows, station_coverage["valid"], "max_value_desc"
        ),
        "data": data,
    }
    station_exceedance = exceedance_block(values, threshold, standard)
    if station_exceedance is not None:
        stations["exceedance"] = station_exceedance

    flags = missing_hours_flag("regional_mean", mean_coverage)
    if station_coverage["valid"] < MIN_STATIONS:
        flags.append(
            flag(
                "few_stations",
                "warning",
                layer="station",
                evidence={**station_coverage, "threshold": MIN_STATIONS},
            )
        )
    if source["failed_files"]:
        flags.append(
            flag(
                "failed_files",
                "warning",
                layer="station",
                evidence={"count": len(source["failed_files"])},
            )
        )
    return [regional, stations], flags
