"""Stable public facade for machine-readable result builders.

The domain implementations live under :mod:`rsplot.result_builders`; this
module retains the established import surface used by CLI and library callers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rsplot.result_builders import (
    build_fnr_result,
    build_forecast_result,
    build_meteo_result,
    build_overlay_result,
    build_raster_result,
    build_reconstruct_result,
    build_region_trend_result,
    build_station_result,
    build_station_trend_result,
)

__all__ = [
    "build_fnr_result",
    "build_forecast_result",
    "build_meteo_result",
    "build_overlay_result",
    "build_raster_result",
    "build_reconstruct_result",
    "build_region_trend_result",
    "build_station_result",
    "build_station_trend_result",
    "emit_result",
]


def emit_result(result: dict[str, Any], image_path: str) -> str:
    """Write ``{image}.json`` and return the sidecar path."""
    sidecar = str(Path(image_path).with_suffix(".json"))
    result["sidecar"] = sidecar
    with open(sidecar, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    return sidecar
