"""Shared map-frame setup for rsplot's Cartopy renderers.

This module owns the common figure, boundary, geographic decoration, and
output lifecycle used by raster, station, overlay, and FNR plots.  Data
layers and colorbars remain in their domain-specific renderers so their
draw order stays explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from cartopy.feature import ShapelyFeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

from rsplot.tiles.tianditu import TianDiTuTiles

if TYPE_CHECKING:
    from cartopy.mpl.geoaxes import GeoAxes
    from matplotlib.artist import Artist
    from matplotlib.figure import Figure
    from shapely.geometry.base import BaseGeometry

    from rsplot.geo.boundaries import RegionInfo


@dataclass(frozen=True)
class MapFrame:
    """Figure state shared by the plotting pipelines."""

    fig: Figure
    ax: GeoAxes
    tiles: TianDiTuTiles | None
    use_basemap: bool


def figure_size_for_level(level: str) -> tuple[float, float]:
    """Choose the established figure size for an administrative level."""
    return {
        "country": (14, 12),
        "key_region": (12, 10),
        "province": (10, 10),
        "city": (10, 8),
        "county": (8, 7),
    }.get(level, (10, 8))


def create_map_frame(
    region: RegionInfo,
    *,
    dpi: int,
    basemap: bool | None,
    tianditu_key: str | None,
) -> MapFrame:
    """Create a figure using the region's basemap and projection rules."""
    requested_basemap = (
        basemap if basemap is not None else region.params.basemap
    )
    use_basemap = requested_basemap and bool(tianditu_key)
    if use_basemap:
        tiles = TianDiTuTiles(tk=tianditu_key, layer="img")
        projection = tiles.crs
    else:
        tiles = None
        projection = ccrs.PlateCarree()

    fig, ax = plt.subplots(
        figsize=figure_size_for_level(region.level),
        dpi=dpi,
        subplot_kw={"projection": projection},
    )
    return MapFrame(
        fig=fig,
        ax=ax,
        tiles=tiles,
        use_basemap=use_basemap,
    )


def add_basemap_tiles(frame: MapFrame, region: RegionInfo) -> None:
    """Add configured TianDiTu imagery at the caller-selected layer order."""
    if frame.tiles is not None:
        frame.ax.add_image(frame.tiles, region.params.zoom)


def add_region_boundaries(ax: GeoAxes, region: RegionInfo) -> None:
    """Draw detail, subdivision, and main boundaries in established order."""
    selected = {
        member.geometry.normalize().wkb
        for member in getattr(region, "members", ())
    }

    def visible_geometries(frame):
        if not selected:
            return frame.geometry
        return [
            geometry
            for geometry in frame.geometry
            if geometry.normalize().wkb not in selected
        ]

    if (
        region.detail_boundary_gdf is not None
        and len(region.detail_boundary_gdf) > 0
    ):
        ax.add_feature(
            ShapelyFeature(
                visible_geometries(region.detail_boundary_gdf),
                ccrs.PlateCarree(),
                edgecolor="#aaa",
                facecolor="none",
                linewidth=0.25,
                linestyle=":",
            )
        )

    if (
        region.sub_boundary_gdf is not None
        and len(region.sub_boundary_gdf) > 0
    ):
        is_county_sub = region.level == "city"
        ax.add_feature(
            ShapelyFeature(
                visible_geometries(region.sub_boundary_gdf),
                ccrs.PlateCarree(),
                edgecolor="#888" if not is_county_sub else "#666",
                facecolor="none",
                linewidth=0.4 if not is_county_sub else 0.6,
                linestyle="-" if not is_county_sub else "--",
            )
        )
        add_subdivision_labels(ax, region)

    if region.main_boundary_gdf is not None:
        ax.add_feature(
            ShapelyFeature(
                region.main_boundary_gdf.geometry,
                ccrs.PlateCarree(),
                edgecolor="red",
                facecolor="none",
                linewidth=region.params.boundary_linewidth,
            )
        )

    if getattr(region, "members", ()):
        add_member_labels(ax, region)


def add_subdivision_labels(ax: GeoAxes, region: RegionInfo) -> None:
    """Add name labels for a region's subdivision features."""
    gdf = region.sub_boundary_gdf
    if gdf is None or len(gdf) == 0:
        return

    name_field = region.sub_name_field
    fontsize = region.params.label_fontsize

    selected_geometry = {
        m.geometry.normalize().wkb for m in getattr(region, "members", ())
    }
    seen_labels = set()
    for _, row in gdf.iterrows():
        key = row.geometry.normalize().wkb
        if key in selected_geometry or (row[name_field], key) in seen_labels:
            continue
        seen_labels.add((row[name_field], key))
        point = row.geometry.representative_point()
        if region.level in (
            "key_region",
            "province",
        ) and not region.geometry.contains(point):
            continue

        label = row[name_field]
        if region.level in ("key_region", "province"):
            label = label.replace("市", "")

        ax.text(
            point.x,
            point.y,
            label,
            transform=ccrs.PlateCarree(),
            fontsize=fontsize,
            ha="center",
            va="center",
            color="#222",
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
        )


def add_member_labels(ax: GeoAxes, region: RegionInfo) -> None:
    """Label selections separately from subdivisions; qualify duplicate names."""
    from collections import Counter

    names = Counter(member.name for member in region.members)
    for member in region.members:
        point = member.geometry.representative_point()
        label = (
            (member.qualified_name or member.name)
            if names[member.name] > 1
            else member.name
        )
        ax.text(
            point.x,
            point.y,
            label,
            transform=ccrs.PlateCarree(),
            fontsize=region.params.label_fontsize,
            ha="center",
            va="center",
            color="#222",
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
        )


def configure_map_axes(
    ax: GeoAxes,
    region: RegionInfo,
    *,
    use_basemap: bool,
) -> None:
    """Apply coast/ocean, padded extent, and geographic gridlines."""
    if not use_basemap:
        ax.coastlines(linewidth=0.5, color="#333")
        ax.add_feature(cfeature.OCEAN, facecolor="#e6f2ff", zorder=0)

    lon_min, lon_max, lat_min, lat_max = region.extent
    pad = region.params.pad
    ax.set_extent(
        [lon_min - pad, lon_max + pad, lat_min - pad, lat_max + pad],
        crs=ccrs.PlateCarree(),
    )

    gridlines = ax.gridlines(
        draw_labels=True,
        linewidth=0.2,
        linestyle="--",
        alpha=0.5,
    )
    gridlines.top_labels = gridlines.right_labels = False
    gridlines.xformatter = LONGITUDE_FORMATTER
    gridlines.yformatter = LATITUDE_FORMATTER
    if getattr(region, "members", ()):
        gridlines.xlocator = mticker.MaxNLocator(nbins=5)
        gridlines.ylocator = mticker.MaxNLocator(nbins=5)
    else:
        gridlines.xlocator = mticker.MultipleLocator(region.params.grid_step)
        gridlines.ylocator = mticker.MultipleLocator(region.params.grid_step)


def finalize_map_figure(
    fig: Figure,
    *,
    dpi: int,
    output: str | None,
    layout_rect: tuple[float, float, float, float] | None = None,
) -> None:
    """Lay out and then save/close or display a completed map figure."""
    if layout_rect is None:
        plt.tight_layout()
    else:
        fig.tight_layout(rect=layout_rect)

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def clip_raster_to_region(
    artist: Artist,
    ax: GeoAxes,
    region: RegionInfo,
    *,
    coverage_geometry: BaseGeometry | None = None,
) -> None:
    """Clip only the data layer, preserving holes and disconnected islands."""
    import numpy as np
    from matplotlib.path import Path as MplPath
    from shapely.geometry import GeometryCollection, MultiPolygon
    from shapely.geometry.polygon import orient

    def orient_geometry(geometry: BaseGeometry) -> BaseGeometry:
        if geometry.geom_type == "Polygon":
            return orient(geometry, sign=1.0)
        if geometry.geom_type == "MultiPolygon":
            return MultiPolygon(
                [orient(part, sign=1.0) for part in geometry.geoms]
            )
        if geometry.geom_type == "GeometryCollection":
            return GeometryCollection(
                [orient_geometry(part) for part in geometry.geoms]
            )
        return geometry

    # Project the geometry into the axes coordinates before building a clip
    # path, so both PlateCarree and satellite-basemap Mercator axes work.
    clip_geometry = region.geometry
    if coverage_geometry is not None:
        clip_geometry = clip_geometry.intersection(coverage_geometry)
    geometry = ax.projection.project_geometry(
        orient_geometry(clip_geometry), ccrs.PlateCarree()
    )
    paths = []

    def append_polygons(geometry: BaseGeometry) -> None:
        if geometry.is_empty:
            return
        if geometry.geom_type == "Polygon":
            polygon = orient(geometry, sign=1.0)
            for ring in (polygon.exterior, *polygon.interiors):
                vertices = np.asarray(ring.coords)[:, :2]
                codes = np.full(len(vertices), MplPath.LINETO, dtype=np.uint8)
                codes[0], codes[-1] = MplPath.MOVETO, MplPath.CLOSEPOLY
                paths.append(MplPath(vertices, codes))
        elif hasattr(geometry, "geoms"):
            for part in geometry.geoms:
                append_polygons(part)

    append_polygons(geometry)
    if not paths:
        raise ValueError("行政区边界没有可用于裁剪的多边形。")
    artist.set_clip_path(MplPath.make_compound_path(*paths), ax.transData)
    # Cartopy can create an auxiliary collection for wrapped mesh cells.
    wrapped = getattr(artist, "_wrapped_collection_fix", None)
    if wrapped is not None:
        wrapped.set_clip_path(MplPath.make_compound_path(*paths), ax.transData)
