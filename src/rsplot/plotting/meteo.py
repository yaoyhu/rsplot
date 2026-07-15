"""Standalone meteorological maps with optional station observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cartopy.crs as ccrs
from cartopy.mpl.path import shapely_to_path
from matplotlib.patches import PathPatch

from rsplot.plotting.map_frame import (
    add_basemap_tiles,
    add_region_boundaries,
    configure_map_axes,
    create_map_frame,
    finalize_map_figure,
)
from rsplot.plotting.station import draw_station_layer
from rsplot.plotting.wind import draw_wind_vectors

if TYPE_CHECKING:
    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.era5 import Era5FieldData
    from rsplot.readers.era5_wind import WindFieldData
    from rsplot.readers.guokong import StationData


def temperature_alpha(*, use_basemap: bool, has_station: bool) -> float:
    """Keep station markers legible over the temperature field."""
    if has_station:
        return 0.45 if use_basemap else 0.55
    return 0.7 if use_basemap else 1.0


def plot_meteo(
    region: RegionInfo,
    *,
    field: Era5FieldData | None = None,
    wind: WindFieldData | None = None,
    station: StationData | None = None,
    station_threshold: float | None = None,
    station_colorbar_label: str = "",
    field_cmap: str = "RdYlBu_r",
    field_vmin: float | None = None,
    field_vmax: float | None = None,
    wind_stride: int = 1,
    wind_scale: float | None = None,
    wind_width: float = 0.004,
    dpi: int = 300,
    basemap: bool | None = None,
    tianditu_key: str | None = None,
    title: str | None = None,
    output: str | None = None,
) -> None:
    """Draw temperature, black wind vectors, and optional stations."""
    if field is None and wind is None:
        raise ValueError("气象图至少需要温度或风场中的一个图层。")
    if station is not None and wind is None:
        raise ValueError("气象图中的站点图层必须与风场一起绘制。")

    frame = create_map_frame(
        region,
        dpi=dpi,
        basemap=basemap,
        tianditu_key=tianditu_key,
    )
    fig = frame.fig
    ax = frame.ax
    add_basemap_tiles(frame, region)

    field_mesh = None
    if field is not None:
        field_mesh = ax.pcolormesh(
            field.lon,
            field.lat,
            field.values,
            transform=ccrs.PlateCarree(),
            cmap=field_cmap,
            vmin=field_vmin,
            vmax=field_vmax,
            shading="auto",
            alpha=temperature_alpha(
                use_basemap=frame.use_basemap,
                has_station=station is not None,
            ),
            zorder=2,
        )
        clip_patch = PathPatch(
            shapely_to_path(region.geometry),
            transform=ccrs.PlateCarree()._as_mpl_transform(ax),
        )
        field_mesh.set_clip_path(clip_patch)

    if wind is not None:
        draw_wind_vectors(
            ax,
            wind,
            stride=wind_stride,
            scale=wind_scale,
            width=wind_width,
        )

    add_region_boundaries(ax, region)
    station_scatter = (
        draw_station_layer(
            ax,
            station,
            region,
            threshold=station_threshold,
        )
        if station is not None
        else None
    )
    configure_map_axes(ax, region, use_basemap=frame.use_basemap)

    if field_mesh is not None and station_scatter is not None:
        field_axis = ax.inset_axes([1.03, 0.54, 0.025, 0.42])
        field_colorbar = fig.colorbar(field_mesh, cax=field_axis)
        field_colorbar.set_label(f"Temperature ({field.unit})", fontsize=9)
        field_colorbar.ax.tick_params(labelsize=8)

        station_axis = ax.inset_axes([1.03, 0.04, 0.025, 0.42])
        station_colorbar = fig.colorbar(station_scatter, cax=station_axis)
        if station_colorbar_label:
            station_colorbar.set_label(station_colorbar_label, fontsize=9)
        station_colorbar.ax.tick_params(labelsize=8)
    elif field_mesh is not None and field is not None:
        field_colorbar = fig.colorbar(
            field_mesh,
            ax=ax,
            shrink=0.7,
            pad=0.05,
        )
        field_colorbar.set_label(f"Temperature ({field.unit})")
    elif station_scatter is not None:
        station_colorbar = fig.colorbar(
            station_scatter,
            ax=ax,
            shrink=0.7,
            pad=0.05,
        )
        if station_colorbar_label:
            station_colorbar.set_label(station_colorbar_label)

    if title is not None:
        ax.set_title(title, fontsize=14)

    layout_rect = (
        (0, 0, 0.9, 1)
        if field_mesh is not None and station_scatter is not None
        else None
    )
    finalize_map_figure(
        fig,
        dpi=dpi,
        output=output,
        layout_rect=layout_rect,
    )
