"""Implementation service for the ``overlay`` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import (
    load_fallback_city_boundaries,
    resolve_satellite,
)
from rsplot.commands.raster import parse_raster_dates, prepare_raster
from rsplot.config import AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console


# Default station variable for each satellite product.
PRODUCT_STATION_PAIR = {
    "no2": "NO2",
    "o3": "O3_8h_24h",
    "o3pr": "O3_8h_24h",
    "hcho": "O3_8h_24h",
}

# Keyword argument -> CLI spellings, for recording where values came from.
OVERLAY_OPTIONS = {
    "sensor": ("--sensor",),
    "processing": ("--processing",),
    "product": ("--product",),
    "days": ("--days",),
    "n_min": ("--n-min",),
    "station_datetime": ("--station-datetime",),
    "var": ("--var",),
    "level": ("--level",),
    "output": ("--output",),
    "dpi": ("--dpi",),
    "res": ("--res",),
    "basemap": ("--basemap",),
    "vmin": ("--vmin",),
    "vmax": ("--vmax",),
    "cmap": ("--cmap",),
    "smooth": ("--smooth",),
    "qa": ("--qa",),
    "cf": ("--cf",),
    "title": ("--title",),
}


def resolve_station_hour(
    date_arg: str,
    sensor: str,
    days: int | None,
    n_min: int | None,
    station_datetime: str | None,
) -> tuple[str, dict[str, Any], list[str], bool]:
    """Resolve satellite dates and one station hour; never pick the latest.

    Returns the station hour, the ``time_matching`` relation, the satellite
    dates and whether they form a window.
    """
    from rsplot.readers.gems import match_station_hour, parse_gems_time
    from rsplot.temporal import adapt_hourly_time

    scan_mode = sensor == "gems" and len(date_arg) == 12
    if scan_mode:
        try:
            parse_gems_time(date_arg)
        except ValueError as error:
            raise RsplotError("invalid_time", str(error)) from error
        if days is not None or n_min is not None:
            raise RsplotError(
                "invalid_argument",
                "GEMS 单次扫描不能同时使用 --days 或 --n-min。",
                option="--days" if days is not None else "--n-min",
            )
        dates, window_mode = [date_arg[:8]], False
    else:
        dates, window_mode = parse_raster_dates(date_arg, days)
    if station_datetime is not None:
        try:
            adapt_hourly_time(station_datetime, label="--station-datetime ")
        except ValueError as error:
            raise RsplotError(
                "invalid_time", str(error), option="--station-datetime"
            ) from error
    if not scan_mode and station_datetime is None:
        raise RsplotError(
            "invalid_argument",
            "卫星日均或窗口均值叠加站点时，必须通过 --station-datetime "
            "YYYYMMDDHH（北京时间）指定一个站点小时；不会自动选择。",
            option="--station-datetime",
        )
    if scan_mode or (sensor == "gems" and not window_mode):
        hour, pairing = match_station_hour(date_arg, station_datetime)
    else:
        hour = station_datetime
        pairing = {
            "reference": "period_mean_with_explicit_station_hour",
            "difference_minutes": None,
            "manual_override": True,
        }
    matching = {
        "layers": ["satellite", "station"],
        "reference": pairing["reference"],
        "difference_minutes": pairing["difference_minutes"],
        "manual_override": pairing["manual_override"],
    }
    return hour, matching, dates, window_mode


def run_overlay(**kwargs: Any) -> None:
    """Overlay one station hour on a satellite layer."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        command="overlay",
        kwargs=kwargs,
        options=OVERLAY_OPTIONS,
        positionals={"region": kwargs["region"], "date": kwargs["date_arg"]},
        emit=lambda created: _emit_overlay(created, **kwargs),
    )


def _emit_overlay(
    created: list[Path],
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
    """Read one station hour, reuse raster preparation, write the sidecar."""
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.data_files import data_path, write_grid_netcdf, write_table_csv
    from rsplot.geo.boundaries import resolve_regions
    from rsplot.geo.processing import buffered_extent
    from rsplot.plotting.overlay import plot_overlay
    from rsplot.readers.guokong import read_stations, resolve_station_file
    from rsplot.result_builders.envelope import (
        request_block,
        resolved,
        sidecar_path,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.satellite import build_satellite_layer
    from rsplot.result_builders.station import build_station_display
    from rsplot.result_builders.station_layer import (
        TABLE_COLUMNS,
        StationInputs,
        build_station_layer,
        colocation_block,
        comparison_flags,
        satellite_at_stations,
    )

    cfg = AppConfig.load()
    prod_info, _ = resolve_satellite(
        product, sensor, qa, cfg, console, processing
    )
    sensor = prod_info.sensor
    processing = prod_info.processing
    station_hour, matching, dates, window_mode = resolve_station_hour(
        date_arg, sensor, days, n_min, station_datetime
    )

    var_given = var is not None
    if var is None:
        var = PRODUCT_STATION_PAIR[product.lower()]
    if var not in STATION_VAR_META:
        raise RsplotError(
            "invalid_argument",
            f"未知站点变量 '{var}'。可用: {', '.join(STATION_VAR_META)}",
            option="--var",
        )

    try:
        info = resolve_regions(region, cfg, level_override=level)
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError(
            "region_not_found", str(error), details={"region": region}
        ) from error

    use_station_dir = cfg.get_data_dir("guokong")
    console.print(f"\n[bold]读取站点数据:[/bold] {use_station_dir}")
    console.print(f"  时间: {station_hour} 北京时间, 变量: {var}")
    read, _ = read_stations(
        use_station_dir,
        station_hour,
        var,
        extent=buffered_extent(info.extent, 0.5),
    )
    from shapely import contains_xy

    in_region = contains_xy(info.geometry.buffer(1e-9), read.lon, read.lat)
    n_valid = int((np.isfinite(read.values) & in_region).sum())
    console.print(
        f"  → [green]{n_valid}[/green] 有效站点 (共 {int(in_region.sum())} 站)"
    )
    threshold = get_exceedance_threshold(var)
    unit, limit_key, limit_time = STATION_VAR_META[var]

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
    satellite_inputs = run.satellite
    assert satellite_inputs is not None
    image = str(Path(output).resolve())
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
            "quantity": prod_info.quantity,
            "unit": prod_info.unit,
            "scale": prod_info.unit_scale,
            "time_aggregation": satellite_inputs.time["aggregation"],
        },
        valid_days=satellite_inputs.valid_days,
    )

    station_path = data_path(image, "station", ".csv")
    station_inputs = StationInputs(
        read=read,
        in_region=in_region,
        var=var,
        unit=unit,
        threshold=threshold,
        standard=(
            f"AQ_LIMITS_2026 {limit_key} {limit_time}"
            if threshold is not None
            else None
        ),
        hour=station_hour,
        data_root=str(use_station_dir),
        source_file=resolve_station_file(use_station_dir, station_hour).name,
    )
    admin_gdf = (
        info.sub_boundary_gdf
        if info.sub_boundary_gdf is not None and len(info.sub_boundary_gdf)
        else load_fallback_city_boundaries(info, cfg.require_geojson_dir())
    )
    station_layer, station_flags, rows = build_station_layer(
        station_inputs,
        info,
        admin_gdf=admin_gdf,
        satellite_values=satellite_at_stations(
            satellite_inputs.lon,
            satellite_inputs.lat,
            satellite_inputs.grid,
            satellite_inputs.counted,
            read.lon,
            read.lat,
        ),
        data=str(station_path),
    )
    created.append(station_path)
    station_entry = write_table_csv(
        station_path,
        rows,
        TABLE_COLUMNS,
        content="station_table",
        layer="station",
    )

    region_stations = _subset(read, in_region)
    plot_options = dict(run.plot_options)
    for key in ("cmap", "vmin", "vmax"):
        plot_options[f"raster_{key}"] = plot_options.pop(key)
    plot_options["raster_label"] = plot_options.pop("colorbar_label")
    console.print("\n[bold]绘图中...[/bold]")
    created.append(Path(image))
    plot_overlay(
        run.lon,
        run.lat,
        run.grid,
        region_stations,
        info,
        station_threshold=threshold,
        station_label=f"{var} ({unit})" if unit else var,
        **plot_options,
    )

    satellite_layer, satellite_flags = build_satellite_layer(
        satellite_inputs, info, data=grid_entry["path"], files_manifest=None
    )
    relation_flags = comparison_flags(
        matching, satellite_layer["time"], station_hour
    )

    request = dict(run.resolved)
    request.pop("data_dir", None)
    request["raster_dir"] = resolved(satellite_inputs.data_root, "config")
    request["station_dir"] = resolved(str(use_station_dir), "config")
    request["station_var"] = (
        resolved(var, "cli")
        if var_given
        else resolved(var, "product_default", "station pairing")
    )
    request["station_datetime"] = (
        resolved(station_hour, "cli")
        if station_datetime is not None
        else resolved(station_hour, "built_in", "nearest scan hour")
    )
    station_display = build_station_display(region_stations) or {
        "range_method": "data_p5_p95"
    }
    render = {
        "image": image,
        **run.render,
        "layers": {
            **run.render["layers"],
            "station": station_display,
        },
    }
    payload = success_envelope(
        command="overlay",
        request=request_block(request),
        region=info,
        layers=[satellite_layer, station_layer],
        relations={
            "time_matching": matching,
            "colocation": colocation_block(rows, str(station_path)),
        },
        flags=satellite_flags + station_flags + relation_flags,
        render=render,
        artifacts={
            "image": image,
            "sidecar": sidecar,
            "data": [grid_entry, station_entry],
        },
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {image}")


def _subset(data: Any, mask: np.ndarray) -> Any:
    from rsplot.readers.guokong import StationData

    values = np.asarray(data.values)[mask]
    return StationData(
        id=np.asarray(data.id)[mask],
        lon=data.lon[mask],
        lat=data.lat[mask],
        values=values,
        var_name=data.var_name,
        n_stations=int(mask.sum()),
        n_valid=int(np.isfinite(values).sum()),
    )
