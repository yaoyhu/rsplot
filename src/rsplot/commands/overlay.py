"""Implementation service for the ``overlay`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import typer

from rsplot.commands.common import (
    load_fallback_city_boundaries,
    resolve_satellite,
    satellite_errors,
)
from rsplot.commands.raster import parse_raster_dates, prepare_raster
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


# Default station variable for each satellite product.
PRODUCT_STATION_PAIR = {
    "no2": "NO2",
    "o3": "O3_8h_24h",
    "o3pr": "O3_8h_24h",
    "hcho": "O3_8h_24h",
}


def resolve_station_hour(
    date_arg: str,
    sensor: str,
    days: int | None,
    n_min: int | None,
    station_datetime: str | None,
) -> tuple[str, dict[str, Any], list[str], bool]:
    """Resolve satellite dates and one station hour; never pick the latest."""
    from rsplot.readers.gems import match_station_hour, parse_gems_time
    from rsplot.temporal import adapt_hourly_time

    scan_mode = sensor == "gems" and len(date_arg) == 12
    if scan_mode:
        parse_gems_time(date_arg)
        if days is not None or n_min is not None:
            raise ValueError("GEMS 单次扫描不能同时使用 --days 或 --n-min。")
        dates, window_mode = [date_arg[:8]], False
    else:
        dates, window_mode = parse_raster_dates(date_arg, days)
    if station_datetime is not None:
        adapt_hourly_time(station_datetime, label="--station-datetime ")
    if scan_mode:
        hour, matching = match_station_hour(date_arg, station_datetime)
        return hour, matching, dates, window_mode
    if station_datetime is None:
        raise ValueError(
            "卫星日均或窗口均值叠加站点时，必须通过 --station-datetime "
            "YYYYMMDDHH（北京时间）指定一个站点小时；不会自动选择。"
        )
    if sensor == "gems" and not window_mode:
        hour, matching = match_station_hour(date_arg, station_datetime)
        return hour, matching, dates, window_mode
    matching = {
        "satellite_period": {
            "start": dates[0],
            "end": dates[-1],
            "aggregation": "window_mean" if window_mode else "daily",
            "date_basis": (
                "asia_shanghai_calendar_day"
                if sensor == "gems"
                else "filename_start_date_utc"
            ),
        },
        "station_datetime": station_datetime,
        "timezone": "Asia/Shanghai",
        "difference_minutes": None,
        "manual_override": True,
        "reference": "period_mean_with_explicit_station_hour",
    }
    return station_datetime, matching, dates, window_mode


@satellite_errors
def run_overlay(
    *,
    region: str,
    date_arg: str,
    product: str,
    sensor: str = "tropomi",
    processing: str | None = None,
    days: int | None = None,
    n_min: int | None = None,
    station_datetime: str | None = None,
    var: str | None,
    level: str | None,
    raster_dir: str | None,
    station_dir: str | None,
    output: str | None,
    dpi: int | None,
    res: float | None,
    basemap: str | None,
    vmin: float | None,
    vmax: float | None,
    cmap: str | None,
    smooth: float | None,
    qa: float | None,
    cf: float = 0.5,
    title: str | None,
    console: Console,
) -> None:
    """Read one station hour, then reuse raster satellite preparation."""
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.geo.boundaries import resolve_regions
    from rsplot.geo.processing import buffered_extent
    from rsplot.plotting.overlay import plot_overlay
    from rsplot.readers.guokong import mask_stations_to_region, read_stations
    from rsplot.results import build_overlay_result, emit_result

    cfg = AppConfig.load()
    prod_info, _ = resolve_satellite(
        product, sensor, qa, cfg, console, processing
    )
    sensor = prod_info.sensor
    processing = prod_info.processing
    station_hour, pairing, dates, window_mode = resolve_station_hour(
        date_arg, sensor, days, n_min, station_datetime
    )

    if var is None:
        var = PRODUCT_STATION_PAIR[product.lower()]
    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知站点变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)

    info = resolve_regions(region, cfg, level_override=level)

    use_station_dir = (
        station_dir if station_dir is not None else cfg.get_data_dir("guokong")
    )
    console.print(f"\n[bold]读取站点数据:[/bold] {use_station_dir}")
    console.print(f"  时间: {station_hour} 北京时间, 变量: {var}")
    data, _ = read_stations(
        use_station_dir,
        station_hour,
        var,
        extent=buffered_extent(info.extent, 0.5),
    )
    data = mask_stations_to_region(data, info.geometry)
    console.print(
        f"  → [green]{data.n_valid}[/green] 有效站点 (共 {data.n_stations} 站)"
    )

    threshold = get_exceedance_threshold(var)
    if threshold is not None:
        n_exceed = int(
            np.sum(data.values[np.isfinite(data.values)] > threshold)
        )
        console.print(
            f"  → 超标阈值: {threshold}, 超标站点: [red]{n_exceed}[/red]"
        )

    source = "GEMS" if sensor == "gems" else "TROPOMI"
    if processing == "nrti":
        source += " NRTI"
    if window_mode:
        period = f"{dates[0]}~{dates[-1]} mean"
        period_name = f"{dates[0]}_{dates[-1]}"
    else:
        period = date_arg
        period_name = date_arg
        if sensor == "gems":
            period += " CST scan" if len(date_arg) == 12 else " CST daily mean"
    if output is None:
        output = (
            f"/tmp/rsplot_overlay_{source.lower().replace(' ', '_')}_"
            f"{info.name}_{product}_{period_name}_{station_hour}.png"
        )
    if title is None:
        title = (
            f"{source} {product.upper()} {period} + "
            f"Station {var} {station_hour} CST - {info.name}"
        )

    run = prepare_raster(
        region=info,
        date_arg=date_arg,
        product=product,
        sensor=sensor,
        processing=processing,
        days=days,
        n_min=n_min,
        level=level,
        data_dir=raster_dir,
        output=output,
        dpi=dpi,
        res=res,
        basemap=basemap,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        smooth=smooth,
        title=title,
        qa=qa,
        cf=cf,
        console=console,
    )

    unit = STATION_VAR_META[var][0]
    plot_options = dict(run.plot_options)
    for key in ("cmap", "vmin", "vmax"):
        plot_options[f"raster_{key}"] = plot_options.pop(key)
    plot_options["raster_label"] = plot_options.pop("colorbar_label")
    console.print("\n[bold]绘图中...[/bold]")
    plot_overlay(
        run.lon,
        run.lat,
        run.grid,
        data,
        info,
        station_threshold=threshold,
        station_label=f"{var} ({unit})" if unit else var,
        **plot_options,
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    result = build_overlay_result(
        raster=run.result,
        region=info,
        date=run.result["date"],
        prod_info=prod_info,
        time_matching=pairing,
        data=data,
        datetime_str=station_hour,
        threshold=threshold,
        unit=unit,
        cities_gdf=load_fallback_city_boundaries(
            info,
            cfg.require_geojson_dir(),
        ),
        output=output,
    )
    emit_result(result, output)
