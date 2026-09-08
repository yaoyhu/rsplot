"""Combined raster/station JSON-sidecar construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.common import serialize_region
from rsplot.result_builders.raster import build_raster_result
from rsplot.result_builders.station import build_station_result

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers import ProductInfo
    from rsplot.readers.guokong import StationData


def build_overlay_result(
    *,
    region: RegionInfo,
    product: str,
    date: str,
    prod_info: ProductInfo,
    LON: np.ndarray,
    LAT: np.ndarray,
    grid: np.ndarray,
    swath_meta: dict[str, Any],
    raster_vmin: float,
    raster_vmax: float,
    data: StationData,
    datetime_str: str,
    threshold: float | None,
    unit: str,
    cities_gdf: gpd.GeoDataFrame | None,
    output: str,
    display_grid: np.ndarray | None = None,
) -> dict[str, Any]:
    """Combine raster and station result blocks without shared duplication."""
    raster_block = build_raster_result(
        region=region,
        product=product,
        date=date,
        prod_info=prod_info,
        LON=LON,
        LAT=LAT,
        grid=grid,
        display_grid=display_grid,
        swath_meta=swath_meta,
        vmin=raster_vmin,
        vmax=raster_vmax,
        output=output,
    )
    station_block = build_station_result(
        region=region,
        data=data,
        datetime_str=datetime_str,
        threshold=threshold,
        unit=unit,
        cities_gdf=cities_gdf,
        output=output,
    )
    for key in ("command", "image", "region"):
        raster_block.pop(key, None)
        station_block.pop(key, None)

    return {
        "command": "overlay",
        "image": output,
        "region": serialize_region(region),
        "datetime": datetime_str,
        "date": date,
        "raster": raster_block,
        "station": station_block,
    }
