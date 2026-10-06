"""The ``station`` points layer and satellite colocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.result_builders.envelope import (
    capped,
    coverage_block,
    flag,
    stats_block,
)
from rsplot.result_builders.station import (
    aqi_distribution,
    attribute_stations_to_areas,
    station_admin_level,
)
from rsplot.stats import round_finite

if TYPE_CHECKING:
    import geopandas as gpd

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import StationData

MIN_STATIONS = 3
MIN_PAIRS = 3
TABLE_COLUMNS = [
    "id",
    "lon",
    "lat",
    "admin",
    "admin_level",
    "value",
    "valid",
    "exceeds",
    "in_region",
    "satellite_value",
    "colocated",
]


@dataclass
class StationInputs:
    """One station hour read for a region, before and after masking."""

    read: StationData
    in_region: np.ndarray
    var: str
    unit: str
    threshold: float | None
    standard: str | None
    hour: str
    data_root: str
    source_file: str


def satellite_at_stations(
    lon: np.ndarray,
    lat: np.ndarray,
    grid: np.ndarray,
    counted: np.ndarray,
    station_lon: np.ndarray,
    station_lat: np.ndarray,
) -> np.ndarray:
    """Value of the valid statistics cell containing each station, else NaN."""
    lons = np.asarray(lon)[0, :]
    lats = np.asarray(lat)[:, 0]
    out = np.full(len(station_lon), np.nan)
    if lons.size < 2 or lats.size < 2:
        return out
    dx = float(lons[1] - lons[0])
    dy = float(lats[1] - lats[0])
    ix = np.rint((station_lon - lons[0]) / dx).astype(int)
    iy = np.rint((station_lat - lats[0]) / dy).astype(int)
    for index, (column, row) in enumerate(zip(ix, iy, strict=True)):
        if not (0 <= column < lons.size and 0 <= row < lats.size):
            continue
        inside_cell = (
            abs(lons[column] - station_lon[index]) <= abs(dx) / 2 + 1e-9
            and abs(lats[row] - station_lat[index]) <= abs(dy) / 2 + 1e-9
        )
        value = grid[row, column]
        if inside_cell and counted[row, column] and np.isfinite(value):
            out[index] = value
    return out


def spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    """Rank correlation, or None with too few or constant pairs."""
    if len(x) < MIN_PAIRS or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    from scipy.stats import spearmanr

    return round_finite(float(spearmanr(x, y).statistic), 3)


def build_station_layer(
    inputs: StationInputs,
    region: RegionInfo,
    *,
    admin_gdf: gpd.GeoDataFrame | None,
    satellite_values: np.ndarray | None,
    data: str | None,
    extra_columns: dict[str, np.ndarray] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the station layer, its quality flags and its table rows.

    ``extra_columns`` adds per-station table columns, e.g. radius offsets.
    """
    from rsplot.readers.guokong import mask_stations_to_region

    read = inputs.read
    values = np.asarray(read.values, dtype=float)
    valid = np.isfinite(values)
    in_region = np.asarray(inputs.in_region, dtype=bool)
    level = station_admin_level(region)
    admins = (
        attribute_stations_to_areas(
            read.lon, read.lat, admin_gdf, region.sub_name_field
        )
        if admin_gdf is not None and len(admin_gdf) > 0
        else np.full(len(values), "", dtype=object)
    )
    threshold = inputs.threshold
    exceeds = (
        valid & (values > threshold)
        if threshold is not None
        else np.zeros(len(values), dtype=bool)
    )
    if satellite_values is None:
        satellite_values = np.full(len(values), np.nan)
    colocated = valid & in_region & np.isfinite(satellite_values)

    rows = [
        {
            "id": str(read.id[index]),
            "lon": float(read.lon[index]),
            "lat": float(read.lat[index]),
            "admin": admins[index] or "",
            "admin_level": (level or "") if admins[index] else "",
            "value": float(values[index]),
            "valid": int(valid[index]),
            "exceeds": int(exceeds[index]),
            "in_region": int(in_region[index]),
            "satellite_value": float(satellite_values[index]),
            "colocated": int(colocated[index]),
            **{
                name: column[index]
                for name, column in (extra_columns or {}).items()
            },
        }
        for index in range(len(values))
    ]

    region_valid = valid & in_region
    region_values = values[region_valid]
    n_stations = int(in_region.sum())
    n_valid = int(region_valid.sum())

    by_admin: dict[str, list[int]] = {}
    for index in np.flatnonzero(region_valid):
        if admins[index]:
            by_admin.setdefault(admins[index], []).append(int(index))
    admin_rows = []
    for name, indices in by_admin.items():
        area_values = values[indices]
        row: dict[str, Any] = {
            "name": name,
            "level": level or "subdivision",
            "n": len(indices),
            "mean": round_finite(np.mean(area_values)),
            "min": round_finite(np.min(area_values)),
            "max": round_finite(np.max(area_values)),
        }
        if threshold is not None:
            row["n_exceed"] = int(exceeds[indices].sum())
        admin_rows.append(row)
    admin_rows.sort(key=lambda row: -(row["mean"] or 0))

    order = np.flatnonzero(region_valid)[
        np.argsort(values[region_valid])[::-1]
    ]
    extremes = [
        {
            "id": str(read.id[index]),
            "lon": round(float(read.lon[index]), 3),
            "lat": round(float(read.lat[index]), 3),
            "value": round_finite(values[index]),
            "admin": admins[index] or None,
        }
        for index in order
    ]

    unit = inputs.unit or "1"
    layer: dict[str, Any] = {
        "id": "station",
        "kind": "points",
        "quantity": {
            "name": inputs.var,
            "unit": unit,
            "scale": 1,
            "label": f"{inputs.var} ({inputs.unit})"
            if inputs.unit
            else inputs.var,
        },
        "time": {
            "aggregation": "hourly",
            "at": inputs.hour,
            "timezone": "Asia/Shanghai",
            "basis": "station_hour",
        },
        "source": {
            "sensor": "station",
            "processing": None,
            "data_root": inputs.data_root,
            "files": [inputs.source_file],
            "files_total": 1,
            "files_manifest": None,
            "failed_files": {},
        },
        "method": {
            "region_selection": "point_inside_region",
            "boundary_tolerance_deg": 1e-9,
            "fill_values_removed": ">= 65534",
        },
        "coverage": coverage_block(n_valid, n_stations, "stations"),
        "stats": stats_block(region_values),
        "by_admin": admin_rows,
        "extremes": capped(extremes, n_valid, "value_desc"),
        "data": data,
    }
    if inputs.var == "AQI":
        layer["categories"] = aqi_distribution(region_values)
    if threshold is not None:
        count = int((exceeds & in_region).sum())
        layer["exceedance"] = {
            "threshold": threshold,
            "operator": ">",
            "standard": inputs.standard,
            "count": count,
            "fraction": round(count / n_valid, 3) if n_valid else None,
        }
    if region.members:
        from rsplot.readers.guokong import StationData

        region_data = StationData(
            id=np.asarray(read.id)[in_region],
            lon=read.lon[in_region],
            lat=read.lat[in_region],
            values=values[in_region],
            var_name=read.var_name,
            n_stations=n_stations,
            n_valid=n_valid,
        )
        layer["by_member"] = []
        for member in region.members:
            selected = mask_stations_to_region(region_data, member.geometry)
            member_stats = stats_block(selected.values)
            layer["by_member"].append(
                {
                    "name": member.qualified_name or member.name,
                    "level": member.administrative_level or member.level,
                    "n": member_stats["n"],
                    "mean": member_stats["mean"],
                    "min": member_stats["min"],
                    "max": member_stats["max"],
                }
            )

    flags: list[dict[str, Any]] = []
    evidence = {"valid": n_valid, "total": n_stations}
    if n_valid == 0:
        flags.append(
            flag(
                "no_valid_data",
                "critical",
                "No station in the region has a valid value at this hour.",
                layer="station",
                evidence=evidence,
            )
        )
    elif n_valid < MIN_STATIONS:
        flags.append(
            flag(
                "few_stations",
                "warning",
                f"Only {n_valid} station(s) in the region have a valid "
                "value; station statistics are not representative.",
                layer="station",
                evidence={**evidence, "threshold": MIN_STATIONS},
            )
        )
    if 0 < n_valid < n_stations:
        flags.append(
            flag(
                "missing_station_values",
                "info",
                f"{n_stations - n_valid} of {n_stations} stations in the "
                "region have no value at this hour.",
                layer="station",
                evidence=evidence,
            )
        )
    return layer, flags, rows


def colocation_block(
    rows: list[dict[str, Any]], data: str | None
) -> dict[str, Any]:
    """Summarize satellite/station pairs at in-region stations."""
    pairs = [row for row in rows if row["colocated"]]
    station_values = np.array([row["value"] for row in pairs])
    satellite_values = np.array([row["satellite_value"] for row in pairs])
    block: dict[str, Any] = {
        "layers": ["satellite", "station"],
        "method": "station_in_valid_statistics_cell",
        "pairs": len(pairs),
        "spearman": spearman(satellite_values, station_values),
        "comparable_units": False,
    }
    if data is not None:
        block["data"] = data
    return block


def comparison_flags(
    matching: dict[str, Any],
    satellite_time: dict[str, Any],
    station_hour: str,
) -> list[dict[str, Any]]:
    """Explain what a satellite/station comparison can and cannot mean."""
    flags = [
        flag(
            "column_vs_surface",
            "info",
            "Satellite columns and surface concentrations show spatial "
            "agreement, not equal quantities.",
        )
    ]
    if matching["difference_minutes"] is None:
        flags.append(
            flag(
                "daily_vs_hourly",
                "info",
                "A daily or window satellite field is compared with one "
                "station hour; there is no single satellite observation time.",
                evidence={
                    "satellite": satellite_time,
                    "station": station_hour,
                },
            )
        )
    elif matching["manual_override"]:
        flags.append(
            flag(
                "manual_time_override",
                "info",
                "--station-datetime replaced the nearest station hour of the "
                "scan.",
                evidence={
                    "difference_minutes": matching["difference_minutes"]
                },
            )
        )
    return flags
