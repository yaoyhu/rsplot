"""Station-centered satellite maps with optional single-hour observations."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.raster import parse_raster_dates, prepare_raster
from rsplot.config import STATION_VAR_META, AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console

# Keyword argument -> CLI spellings, for recording where values came from.
RADIUS_OPTIONS = {
    "sensor": ("--sensor",),
    "processing": ("--processing",),
    "product": ("--product",),
    "days": ("--days",),
    "n_min": ("--n-min",),
    "km": ("--km",),
    "station_var": ("--station-var",),
    "station_datetime": ("--station-datetime",),
    "output": ("--output",),
    "dpi": ("--dpi",),
    "res": ("--res",),
    "basemap": ("--basemap",),
    "vmin": ("--vmin",),
    "vmax": ("--vmax",),
    "cmap": ("--cmap",),
    "smooth": ("--smooth",),
    "title": ("--title",),
    "qa": ("--qa",),
    "cf": ("--cf",),
}
LOCATION_COLUMNS = [
    "id",
    "lon",
    "lat",
    "admin",
    "in_region",
    "is_center",
    "distance_km",
    "dx_km",
    "dy_km",
]
RADIUS_COLUMNS = ["is_center", "distance_km", "dx_km", "dy_km"]


def location_snapshot_hour(
    date_arg: str,
    sensor: str,
    days: int | None,
    station_datetime: str | None,
) -> str:
    """Hour whose station coordinates are drawn when no variable is shown."""
    from rsplot.readers.gems import parse_gems_time
    from rsplot.temporal import adapt_hourly_time

    scan_mode = sensor == "gems" and len(date_arg) == 12
    if scan_mode:
        try:
            parse_gems_time(date_arg)
        except ValueError as error:
            raise RsplotError("invalid_time", str(error)) from error
        if days is not None:
            raise RsplotError(
                "invalid_argument",
                "GEMS 单次扫描不能同时使用 --days。",
                option="--days",
            )
    dates, _ = parse_raster_dates(
        date_arg[:8] if scan_mode else date_arg, days
    )
    if station_datetime is not None:
        try:
            adapt_hourly_time(station_datetime, label="--station-datetime ")
        except ValueError as error:
            raise RsplotError(
                "invalid_time", str(error), option="--station-datetime"
            ) from error
    return station_datetime or dates[-1]


def run_radius(**kwargs: Any) -> None:
    """Map a station-centred square with an optional station hour."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        command="radius",
        kwargs=kwargs,
        options=RADIUS_OPTIONS,
        positionals={
            "station_id": kwargs["station_id"],
            "date": kwargs["date_arg"],
        },
        emit=lambda created: _emit_radius(created, **kwargs),
    )


def _emit_radius(
    created: list[Path],
    *,
    station_id: str,
    date_arg: str,
    km: float,
    station_var: str | None = None,
    station_datetime: str | None = None,
    console: Console,
    **raster_options: Any,
) -> None:
    """Resolve stations and a square, reuse satellite preparation, emit."""
    from rsplot.commands.overlay import resolve_station_hour
    from rsplot.config import get_exceedance_threshold
    from rsplot.data_files import data_path, write_grid_netcdf, write_table_csv
    from rsplot.geo.radius import (
        administrative_context,
        resolve_radius_region,
        station_distances,
        station_offsets_km,
        station_square_mask,
    )
    from rsplot.plotting.overlay import plot_overlay
    from rsplot.plotting.raster import plot_raster
    from rsplot.plotting.station_focus import StationFocus
    from rsplot.readers import get_product_info
    from rsplot.readers.guokong import (
        StationData,
        read_station_locations,
        read_stations,
    )
    from rsplot.result_builders.envelope import (
        coverage_block,
        request_block,
        resolved,
        sidecar_path,
        stats_block,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.satellite import build_satellite_layer
    from rsplot.result_builders.station import (
        attribute_stations_to_areas,
        build_station_display,
    )
    from rsplot.result_builders.station_layer import (
        TABLE_COLUMNS,
        StationInputs,
        build_station_layer,
        colocation_block,
        comparison_flags,
        satellite_at_stations,
    )

    if not math.isfinite(km) or km <= 0:
        raise RsplotError(
            "invalid_argument",
            "--km 必须是大于 0 的有限数字。",
            option="--km",
        )
    station_id = station_id.strip().upper()
    if not station_id:
        raise RsplotError("invalid_argument", "站点 ID 不能为空。")
    if station_var is not None:
        station_var = station_var.strip()
        if station_var not in STATION_VAR_META:
            raise RsplotError(
                "invalid_argument",
                f"未知站点变量 '{station_var}'。可用: "
                + ", ".join(STATION_VAR_META),
                option="--station-var",
            )
    options = {
        "product": "o3",
        "sensor": "tropomi",
        "processing": None,
        "days": None,
        "n_min": None,
        "level": None,
        "output": None,
        "dpi": 300,
        "res": None,
        "basemap": "none",
        "vmin": None,
        "vmax": None,
        "cmap": None,
        "smooth": None,
        "title": None,
        "qa": None,
        "cf": 0.5,
        **raster_options,
    }
    prod = get_product_info(
        options["product"],
        sensor=options["sensor"],
        processing=options["processing"],
    )
    options["processing"] = prod.processing
    options["sensor"] = prod.sensor
    matching = None
    if station_var is not None:
        request, matching, dates, window_mode = resolve_station_hour(
            date_arg,
            prod.sensor,
            options["days"],
            options["n_min"],
            station_datetime,
        )
    else:
        request = location_snapshot_hour(
            date_arg, prod.sensor, options["days"], station_datetime
        )
        scan_mode = prod.sensor == "gems" and len(date_arg) == 12
        dates, window_mode = parse_raster_dates(
            date_arg[:8] if scan_mode else date_arg, options["days"]
        )
    cfg = AppConfig.load()
    directory = cfg.get_data_dir("guokong")
    locations = read_station_locations(directory, request)
    values = np.full(len(locations.id), np.nan)
    if station_var is not None:
        observations, _ = read_stations(
            directory, locations.datetime, station_var
        )
        values = observations.values
    indices = np.flatnonzero(locations.id == station_id)
    if not len(indices):
        raise RsplotError(
            "region_not_found",
            f"站点文件 {locations.source_file} 中未找到 '{station_id}'。",
            details={"station_id": station_id},
        )
    center = int(indices[0])
    lon, lat = float(locations.lon[center]), float(locations.lat[center])
    info = resolve_radius_region(station_id, lon, lat, km, cfg)
    distances = station_distances(lon, lat, locations.lon, locations.lat)
    dx_km, dy_km = station_offsets_km(lon, lat, locations.lon, locations.lat)
    selected = np.flatnonzero(
        station_square_mask(lon, lat, km, locations.lon, locations.lat)
    )
    unique = {}
    for index in np.concatenate((indices, selected)):
        key = str(locations.id[index])
        if not key:
            continue
        if key in unique:
            previous = unique[key]
            if not (
                locations.lon[index] == locations.lon[previous]
                and locations.lat[index] == locations.lat[previous]
                and (
                    values[index] == values[previous]
                    or (np.isnan(values[index]) and np.isnan(values[previous]))
                )
            ):
                raise RsplotError(
                    "read_failed", f"站点 '{key}' 重复且坐标或观测值冲突。"
                )
        else:
            unique[key] = int(index)
    selected = np.asarray(list(unique.values()), dtype=int)
    data = StationData(
        id=locations.id[selected],
        lon=locations.lon[selected],
        lat=locations.lat[selected],
        values=values[selected],
        var_name=station_var or "",
        n_stations=len(selected),
        n_valid=int(np.isfinite(values[selected]).sum()),
    )
    source_label = prod.sensor.upper() + (" NRTI" if prod.processing else "")
    source_name = prod.sensor + ("_nrti" if prod.processing else "")
    period = f"{dates[0]}~{dates[-1]}" if window_mode else date_arg
    if options["output"] is None:
        suffix = (
            f"_{station_var}_{locations.datetime}"
            if station_var
            else "_positions"
        )
        options["output"] = str(
            Path("/tmp")
            / (
                f"rsplot_radius_{station_id}_{source_name}_"
                f"{options['product']}_{period}_{km:g}km{suffix}.png"
            )
        )
    if options["title"] is None:
        pretty_period = (
            f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]} ~ "
            f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}"
            if window_mode
            else datetime.strptime(
                date_arg, "%Y%m%d%H%M" if len(date_arg) == 12 else "%Y%m%d"
            ).strftime("%Y-%m-%d %H:%M" if len(date_arg) == 12 else "%Y-%m-%d")
        )
        station_hour = datetime.strptime(
            locations.datetime, "%Y%m%d%H"
        ).strftime("%Y-%m-%d %H:%M")
        aggregation = (
            "窗口均值"
            if window_mode
            else "扫描"
            if prod.sensor == "gems" and len(date_arg) == 12
            else "当日有效扫描均值"
            if prod.sensor == "gems"
            else "单日"
        )
        station_label = (
            f"站点 {station_var} · {station_hour} 北京时间"
            if station_var
            else f"站点位置快照 · {station_hour} 北京时间"
        )
        options["title"] = (
            f"{info.name}\n{source_label} {options['product'].upper()} "
            f"· {pretty_period} {aggregation}（北京时间）\n{station_label}"
        )
    console.print(
        f"[bold]站点快照:[/bold] {locations.datetime} 北京时间，"
        f"正方形范围内 {data.n_stations} 站"
    )
    run = prepare_raster(
        region=info,
        date_arg=date_arg,
        console=console,
        **options,
    )
    satellite_inputs = run.satellite
    assert satellite_inputs is not None
    image = str(Path(options["output"]).resolve())
    sidecar = sidecar_path(image)

    grid_path = data_path(image, "satellite", ".nc")
    created.append(grid_path)
    grid_entry = write_grid_netcdf(
        grid_path,
        satellite_inputs.lon,
        satellite_inputs.lat,
        satellite_inputs.grid,
        satellite_inputs.counted,
        extent=info.extent,
        layer="satellite",
        attrs={
            "quantity": prod.quantity,
            "unit": prod.unit,
            "scale": prod.unit_scale,
            "time_aggregation": satellite_inputs.time["aggregation"],
        },
        valid_days=satellite_inputs.valid_days,
    )

    offsets = {
        "is_center": (data.id == station_id).astype(int),
        "distance_km": distances[selected],
        "dx_km": dx_km[selected],
        "dy_km": dy_km[selected],
    }
    station_path = data_path(image, "station", ".csv")
    admin_gdf = info.sub_boundary_gdf
    relations: dict[str, Any] = {}
    comparison: list[dict[str, Any]] = []
    station_flags: list[dict[str, Any]] = []
    if station_var is not None:
        unit, limit_key, limit_time = STATION_VAR_META[station_var]
        threshold = get_exceedance_threshold(station_var)
        station_layer, station_flags, rows = build_station_layer(
            StationInputs(
                read=data,
                in_region=np.ones(data.n_stations, dtype=bool),
                var=station_var,
                unit=unit,
                threshold=threshold,
                standard=(
                    f"AQ_LIMITS_2026 {limit_key} {limit_time}"
                    if threshold is not None
                    else None
                ),
                hour=locations.datetime,
                data_root=str(directory),
                source_file=Path(locations.source_file).name,
            ),
            info,
            admin_gdf=admin_gdf,
            satellite_values=satellite_at_stations(
                satellite_inputs.lon,
                satellite_inputs.lat,
                satellite_inputs.grid,
                satellite_inputs.counted,
                data.lon,
                data.lat,
            ),
            data=str(station_path),
            extra_columns=offsets,
        )
        columns = TABLE_COLUMNS + list(offsets)
    else:
        admins = (
            attribute_stations_to_areas(
                data.lon, data.lat, admin_gdf, info.sub_name_field
            )
            if admin_gdf is not None and len(admin_gdf) > 0
            else np.full(data.n_stations, "", dtype=object)
        )
        rows = [
            {
                "id": str(data.id[index]),
                "lon": float(data.lon[index]),
                "lat": float(data.lat[index]),
                "admin": admins[index] or "",
                "in_region": 1,
                **{name: column[index] for name, column in offsets.items()},
            }
            for index in range(data.n_stations)
        ]
        columns = LOCATION_COLUMNS
        station_layer = {
            "id": "station",
            "kind": "points",
            "quantity": {"name": "location", "unit": "1", "scale": 1},
            "time": {
                "aggregation": "hourly",
                "at": locations.datetime,
                "timezone": "Asia/Shanghai",
                "basis": "station_hour",
            },
            "source": {
                "sensor": "station",
                "processing": None,
                "data_root": str(directory),
                "files": [Path(locations.source_file).name],
                "files_total": 1,
                "files_manifest": None,
                "failed_files": {},
            },
            "method": {
                "region_selection": "square_east_north_offsets",
                "values": "locations_only",
            },
            "coverage": coverage_block(
                data.n_stations, data.n_stations, "stations"
            ),
            "stats": stats_block(np.array([])),
            "by_admin": [],
            "extremes": {
                "items": [],
                "total": 0,
                "truncated": False,
                "order": "value_desc",
            },
            "data": str(station_path),
        }
    station_layer["method"]["region_selection"] = "square_east_north_offsets"
    created.append(station_path)
    station_entry = write_table_csv(
        station_path,
        rows,
        columns,
        content="station_table",
        layer="station",
    )

    created.append(Path(image))
    focus = StationFocus(data, station_id, km, station_var is None)
    plot_options = {**run.plot_options, "station_focus": focus}
    if station_var is None:
        plot_raster(run.lon, run.lat, run.grid, info, **plot_options)
    else:
        for key in ("cmap", "vmin", "vmax"):
            plot_options[f"raster_{key}"] = plot_options.pop(key)
        plot_options["raster_label"] = plot_options.pop("colorbar_label")
        unit = STATION_VAR_META[station_var][0]
        plot_options["station_label"] = (
            f"{station_var} ({unit})" if unit else station_var
        )
        plot_overlay(run.lon, run.lat, run.grid, data, info, **plot_options)

    satellite_layer, satellite_flags = build_satellite_layer(
        satellite_inputs, info, data=grid_entry["path"], files_manifest=None
    )
    if matching is not None:
        relations = {
            "time_matching": matching,
            "colocation": colocation_block(rows, str(station_path)),
        }
        comparison = comparison_flags(
            matching, satellite_layer["time"], locations.datetime
        )

    request_values = dict(run.resolved)
    request_values.pop("region", None)
    request_values.update(
        station_id=resolved(station_id, "cli"),
        km=resolved(km, "cli"),
        station_var=(
            resolved(station_var, "cli") if station_var is not None else None
        ),
        station_datetime=(
            resolved(locations.datetime, "cli")
            if station_datetime is not None
            else resolved(
                locations.datetime,
                "built_in",
                "nearest scan hour"
                if station_var is not None
                else "end date snapshot",
            )
        ),
        station_data_dir=resolved(str(directory), "config"),
    )
    render_layers = dict(run.render["layers"])
    if station_var is not None:
        render_layers["station"] = build_station_display(data) or {
            "range_method": "data_p5_p95"
        }
    payload = success_envelope(
        command="radius",
        request=request_block(request_values),
        region=info,
        layers=[satellite_layer, station_layer],
        relations=relations,
        flags=satellite_flags + station_flags + comparison,
        render={"image": image, **run.render, "layers": render_layers},
        artifacts={
            "image": image,
            "sidecar": sidecar,
            "data": [grid_entry, station_entry],
        },
        radius={
            "center_station": station_id,
            "km": km,
            "side_length_km": 2 * km,
            "shape": "square",
            "projection": "station_centered_WGS84_AEQD",
            "center_lon": lon,
            "center_lat": lat,
            "administrative_context": administrative_context(info, lon, lat),
        },
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(f"[bold green]✓ 已保存:[/bold green] {image}")
