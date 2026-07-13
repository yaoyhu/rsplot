"""Domain-specific builders for rsplot's stable JSON sidecars."""

from rsplot.result_builders.fnr import build_fnr_result
from rsplot.result_builders.forecast import build_forecast_result
from rsplot.result_builders.overlay import build_overlay_result
from rsplot.result_builders.raster import build_raster_result
from rsplot.result_builders.station import build_station_result
from rsplot.result_builders.station_trend import build_station_trend_result

__all__ = [
    "build_fnr_result",
    "build_forecast_result",
    "build_overlay_result",
    "build_raster_result",
    "build_station_result",
    "build_station_trend_result",
]
