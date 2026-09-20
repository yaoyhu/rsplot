"""Station labels and radius decorations shared by raster and overlay maps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import numpy as np

from rsplot.plotting.station import station_marker_size

if TYPE_CHECKING:
    from cartopy.mpl.geoaxes import GeoAxes

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData


@dataclass(frozen=True)
class StationFocus:
    data: StationData
    center_id: str
    radius_km: float
    locations_only: bool = False


def add_station_focus(
    ax: GeoAxes,
    region: RegionInfo,
    focus: StationFocus,
) -> None:
    """Add station IDs and missing sites inside the map frame."""
    data = focus.data
    marker_size = station_marker_size(region.level)
    missing = ~np.isfinite(data.values)
    visible = (
        np.ones(data.n_stations, dtype=bool)
        if focus.locations_only
        else missing
    )
    if visible.any():
        ax.scatter(
            data.lon[visible],
            data.lat[visible],
            s=marker_size,
            facecolors="#2374ab" if focus.locations_only else "none",
            edgecolors="white" if focus.locations_only else "#666",
            linewidths=1.2,
            transform=ccrs.PlateCarree(),
            zorder=7,
            label="国控站点" if focus.locations_only else "站点缺测",
        )
    west, east, south, north = region.extent
    for index, station_id in enumerate(data.id):
        right_edge = data.lon[index] > west + (east - west) * 0.8
        y_offset = 10 if index % 2 == 0 else -15
        if data.lat[index] < south + (north - south) * 0.15:
            y_offset = 10
        elif data.lat[index] > south + (north - south) * 0.85:
            y_offset = -15
        ax.annotate(
            str(station_id),
            (data.lon[index], data.lat[index]),
            xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
            xytext=(-8 if right_edge else 8, y_offset),
            ha="right" if right_edge else "left",
            textcoords="offset points",
            fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"},
            arrowprops={"arrowstyle": "-", "color": "#555", "lw": 0.5},
            zorder=9,
        )
    if not focus.locations_only and not np.isfinite(data.values).any():
        ax.text(
            0.02,
            0.98,
            "该小时站点观测全部缺测",
            transform=ax.transAxes,
            va="top",
            fontsize=9,
            zorder=10,
            bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"},
        )
