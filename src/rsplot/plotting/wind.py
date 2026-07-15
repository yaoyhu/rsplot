"""Shared ERA5 wind-vector plotting helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import numpy as np

if TYPE_CHECKING:
    from cartopy.mpl.geoaxes import GeoAxes
    from matplotlib.quiver import Quiver

    from rsplot.readers.era5_wind import WindFieldData


def wind_stride_for_shape(shape: tuple[int, int], region_level: str) -> int:
    """Choose a readable quiver stride for a regional ERA5 subset."""
    target = {
        "country": 32,
        "key_region": 30,
        "province": 28,
        "city": 24,
        "county": 20,
    }.get(region_level, 24)
    return max(1, round(max(shape) / target))


def nice_wind_reference(speed: np.ndarray) -> float:
    """Return a compact, human-readable quiver-key magnitude."""
    value = float(np.nanpercentile(speed, 75))
    if value <= 0:
        return 1.0
    magnitude = 10 ** np.floor(np.log10(value))
    scaled = value / magnitude
    nice = 1.0 if scaled <= 1 else 2.0 if scaled <= 2 else 5.0
    return nice * magnitude


def draw_wind_vectors(
    ax: GeoAxes,
    wind: WindFieldData,
    *,
    stride: int = 1,
    scale: float | None = None,
    width: float = 0.004,
) -> Quiver | None:
    """Draw black wind arrows and a reference key for their magnitude."""
    step = max(1, stride)
    sample = np.s_[::step, ::step]
    sampled_speed = wind.speed[sample]
    finite_speed = sampled_speed[np.isfinite(sampled_speed)]
    if len(finite_speed) == 0:
        return None

    wind_quiver = ax.quiver(
        wind.lon[sample],
        wind.lat[sample],
        wind.u[sample],
        wind.v[sample],
        transform=ccrs.PlateCarree(),
        color="black",
        scale=scale,
        pivot="middle",
        width=width,
        alpha=0.9,
        zorder=3,
    )
    reference = nice_wind_reference(finite_speed)
    ax.quiverkey(
        wind_quiver,
        0.86,
        0.035,
        reference,
        f"{reference:g} {wind.unit}",
        labelpos="E",
        coordinates="axes",
        fontproperties={"size": 8},
    )
    return wind_quiver
