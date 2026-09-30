"""Combined raster/station JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rsplot.result_builders.common import (
    member_basic_stats,
    serialize_member,
    serialize_region,
)
from rsplot.result_builders.station import build_station_result

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo
    from rsplot.readers.guokong import StationData


def build_overlay_result(
    *,
    raster: dict[str, Any],
    region: RegionInfo,
    date: str,
    prod_info: ProductInfo,
    data: StationData,
    datetime_str: str,
    threshold: float | None,
    unit: str,
    cities_gdf: gpd.GeoDataFrame | None,
    output: str,
    time_matching: dict[str, Any],
) -> dict[str, Any]:
    """Combine a prepared raster result with a station block."""
    raster_block = dict(raster)
    station_block = build_station_result(
        region=region,
        data=data,
        datetime_str=datetime_str,
        threshold=threshold,
        unit=unit,
        cities_gdf=cities_gdf,
        output=output,
    )
    if region.members:
        from rsplot.readers.guokong import mask_stations_to_region

        station_block["member_stats"] = []
        for member in region.members:
            selected = mask_stations_to_region(data, member.geometry)
            station_block["member_stats"].append(
                {
                    "region": serialize_member(member),
                    "n_stations": int(selected.n_stations),
                    "n_valid": int(selected.n_valid),
                    "stats": member_basic_stats(selected.values),
                }
            )
    for key in ("command", "image", "region"):
        raster_block.pop(key, None)
        station_block.pop(key, None)

    result = {
        "command": "overlay",
        "image": output,
        "region": serialize_region(region),
        "datetime": datetime_str,
        "date": date,
        "raster": raster_block,
        "station": station_block,
        "time_matching": time_matching,
    }
    if prod_info.processing == "nrti":
        result["sensor"] = "tropomi"
        result["processing"] = "nrti"
    if prod_info.sensor == "gems":
        result["sensor"] = "gems"
    return result
