"""Station-centered satellite maps with optional single-hour observations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import satellite_errors, validate_positive
from rsplot.commands.raster import parse_raster_dates, prepare_raster
from rsplot.config import STATION_VAR_META, AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def station_time_request(
    date_arg: str,
    sensor: str,
    days: int | None,
    station_var: str | None,
    station_datetime: str | None,
) -> tuple[str, dict[str, Any], list[str], bool]:
    """Resolve one station snapshot; never average station observations."""
    from rsplot.readers.gems import match_station_hour, parse_gems_time
    from rsplot.temporal import adapt_hourly_time

    scan_mode = sensor == "gems" and len(date_arg) == 12
    if scan_mode:
        parse_gems_time(date_arg)
        if days is not None:
            raise ValueError("GEMS 单次扫描不能同时使用 --days。")
    dates, window_mode = parse_raster_dates(
        date_arg[:8] if scan_mode else date_arg,
        days,
    )
    if station_datetime is not None:
        adapt_hourly_time(station_datetime, label="站点时间")
    if scan_mode and station_var is not None:
        request, matching = match_station_hour(date_arg, station_datetime)
    else:
        if station_var is not None and station_datetime is None:
            raise ValueError(
                "卫星日均或窗口图选择 --station-var 时，必须通过 "
                "--station-datetime YYYYMMDDHH 指定一个站点小时。"
            )
        request = station_datetime or dates[-1]
        matching = {
            "reference": (
                "explicit_station_hour"
                if station_datetime
                else "latest_location_snapshot_on_end_date"
            ),
            "manual_override": station_datetime is not None,
            "difference_minutes": None,
            "timezone": "Asia/Shanghai",
        }
    return request, matching, dates, window_mode


@satellite_errors
def run_radius(
    *,
    station_id: str,
    date_arg: str,
    km: float,
    station_var: str | None = None,
    station_datetime: str | None = None,
    station_data_dir: str | None = None,
    console: Console,
    **raster_options: Any,
) -> None:
    """Resolve stations and a station-centered square, then reuse satellite preparation."""
    from rsplot.geo.radius import (
        resolve_radius_region,
        station_distances,
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
    from rsplot.result_builders.radius import build_radius_result
    from rsplot.results import emit_result

    validate_positive(km, "--km")
    station_id = station_id.strip().upper()
    if not station_id:
        raise ValueError("站点 ID 不能为空。")
    if station_var is not None:
        station_var = station_var.strip()
        if station_var not in STATION_VAR_META:
            raise ValueError(
                f"未知站点变量 '{station_var}'。可用: "
                + ", ".join(STATION_VAR_META)
            )
    options = {
        "product": "o3",
        "sensor": "tropomi",
        "days": None,
        "n_min": None,
        "level": None,
        "data_dir": None,
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
    prod = get_product_info(options["product"], sensor=options["sensor"])
    options["sensor"] = prod.sensor
    request, matching, dates, window_mode = station_time_request(
        date_arg,
        prod.sensor,
        options["days"],
        station_var,
        station_datetime,
    )
    cfg = AppConfig.load()
    directory = station_data_dir or cfg.get_data_dir("guokong")
    locations = read_station_locations(directory, request)
    matching["station_datetime"] = locations.datetime
    values = np.full(len(locations.id), np.nan)
    if station_var is not None:
        observations, _ = read_stations(
            directory, locations.datetime, station_var
        )
        values = observations.values
    indices = np.flatnonzero(locations.id == station_id)
    if not len(indices):
        raise ValueError(
            f"站点文件 {locations.source_file} 中未找到 '{station_id}'。"
        )
    center = int(indices[0])
    lon, lat = float(locations.lon[center]), float(locations.lat[center])
    info = resolve_radius_region(station_id, lon, lat, km, cfg)
    distances = station_distances(lon, lat, locations.lon, locations.lat)
    selected = np.flatnonzero(
        station_square_mask(
            lon,
            lat,
            km,
            locations.lon,
            locations.lat,
        )
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
                raise ValueError(f"站点 '{key}' 重复且坐标或观测值冲突。")
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
                f"rsplot_radius_{station_id}_{prod.sensor}_{options['product']}_"
                f"{period}_{km:g}km{suffix}.png"
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
            f"{info.name}\n{prod.sensor.upper()} {options['product'].upper()} "
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
    result = build_radius_result(
        run.result,
        info,
        data,
        station_id,
        km,
        distances[selected],
        locations.source_file,
        matching,
        station_var,
    )
    emit_result(result, options["output"])
    console.print(f"[bold green]✓ 已保存:[/bold green] {options['output']}")
