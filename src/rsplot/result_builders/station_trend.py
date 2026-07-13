"""JSON-sidecar construction for single-station hourly trends."""

from __future__ import annotations

from typing import Any

import numpy as np

from rsplot.readers.guokong import StationSeries
from rsplot.stats import basic_stats, round_finite


def build_station_trend_result(
    *,
    series: StationSeries,
    dates: list[str],
    threshold: float | None,
    unit: str,
    output: str,
) -> dict[str, Any]:
    """Build the machine-readable payload for station-trend."""
    valid = np.isfinite(series.values)
    n_valid = int(valid.sum())
    result: dict[str, Any] = {
        "command": "station-trend",
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
