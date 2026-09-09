"""Implementation service for the ``overlay`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import (
    load_fallback_city_boundaries,
    parse_basemap,
    resolve_satellite,
    satellite_errors,
    satellite_filter_label,
    validate_color_range,
    validate_non_negative,
    validate_positive,
    validate_unit_interval,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


PRODUCT_STATION_PAIR = {
    "no2": "NO2",
    "o3": "O3",
    "o3pr": "O3",
}


@satellite_errors
def run_overlay(
    *,
    region: str,
    datetime_str: str,
    product: str,
    sensor: str = "tropomi",
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
    """Execute satellite/station overlay orchestration."""
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.geo.boundaries import resolve_regions
    from rsplot.geo.processing import (
        buffered_extent,
        prepare_display_grid,
        prepare_existing_grid,
        prepare_swath_grid,
    )
    from rsplot.plotting.overlay import plot_overlay
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange
    from rsplot.readers.guokong import mask_stations_to_region, read_stations
    from rsplot.results import build_overlay_result, emit_result

    cfg = AppConfig.load()
    prod_info, use_qa = resolve_satellite(product, sensor, qa, cfg, console)
    sensor = prod_info.sensor
    pairing = None
    station_request = datetime_str
    if sensor == "gems":
        from rsplot.readers.gems import match_station_hour

        station_request, pairing = match_station_hour(
            datetime_str, station_datetime
        )
        if product.lower() == "hcho" and var is None:
            raise ValueError("GEMS HCHO 叠加需通过 --var 显式指定站点变量。")
    elif station_datetime is not None:
        raise ValueError("--station-datetime 在此命令中仅用于 GEMS。")
    setup_fonts(cfg.font_dir)

    if var is None:
        var = PRODUCT_STATION_PAIR.get(product.lower(), "AQI")
    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知站点变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)

    if sensor != "gems" and (
        not datetime_str.isdigit() or len(datetime_str) not in (8, 10)
    ):
        console.print(
            f"[red]datetime 参数 '{datetime_str}' 格式不正确[/red]，"
            "请使用 YYYYMMDD 或 YYYYMMDDHH。"
        )
        raise typer.Exit(1)
    date = datetime_str[:8]

    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_regions(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    if info.members:
        console.print(
            "  → 成员: "
            + "、".join(
                member.qualified_name or member.name for member in info.members
            )
        )
    console.print(
        f"  → 范围: {info.extent[0]:.2f}°~{info.extent[1]:.2f}°E, "
        f"{info.extent[2]:.2f}°~{info.extent[3]:.2f}°N"
    )

    params = info.params
    use_dpi = dpi if dpi is not None else cfg.dpi
    product_defaults = prod_info.defaults_for_level(info.level)
    use_res = (
        res
        if res is not None
        else product_defaults.res
        if product_defaults.res is not None
        else params.res
    )
    use_cmap = cmap if cmap is not None else prod_info.cmap
    use_smooth = (
        smooth
        if smooth is not None
        else product_defaults.smooth_sigma
        if product_defaults.smooth_sigma is not None
        else params.smooth_sigma
    )
    try:
        use_basemap = parse_basemap(basemap)
        validate_positive(use_dpi, "--dpi")
        validate_positive(use_res, "--res")
        validate_unit_interval(use_qa, "--qa")
        validate_unit_interval(cf, "--cf")
        validate_color_range(vmin, vmax)
        if use_smooth is not None:
            validate_non_negative(use_smooth, "--smooth")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if use_smooth == 0:
        use_smooth = None
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    use_raster_dir = (
        raster_dir
        if raster_dir is not None
        else cfg.get_data_dir(prod_info.data_key or product)
    )
    reader = prod_info.reader_cls()
    reader.cloud_fraction_max = cf
    if sensor == "gems":
        console.print(f"  → GEMS 目标网格 {use_res}°（分析与显示）")
    read_extent = buffered_extent(info.extent, 1.0)
    console.print(
        f"\n[bold]读取卫星数据:[/bold] {use_raster_dir} (产品: {product})"
    )
    console.print(
        f"  时间: {datetime_str}, {satellite_filter_label(sensor, use_qa, cf)}"
    )
    statistics_grid = None
    if sensor == "gems":
        from rsplot.temporal import read_scan_mean

        batch = read_scan_mean(
            reader=reader,
            data_dir=use_raster_dir,
            request=datetime_str,
            extent=read_extent,
            res=use_res,
        )
        prepared = prepare_existing_grid(
            batch.LON,
            batch.LAT,
            batch.grid,
            info.geometry,
            fill_gaps=False,
        )
        display_source = prepared.unmasked_values
        statistics_grid = prepared.values.copy()
        swath_meta = {
            "n_pixels": batch.n_pixels,
            "n_files": batch.n_files,
            "n_broken": batch.n_broken,
            "resolution_deg": use_res,
            "cloud_fraction_max": cf,
            **batch.metadata,
        }
    else:
        swath = reader.read(
            use_raster_dir,
            date,
            read_extent,
            qa_threshold=use_qa,
        )
        console.print(
            f"  → [green]{swath.n_pixels}[/green] 有效像元 "
            f"({swath.n_files} 文件, {swath.n_broken} 损坏)"
        )

        console.print(f"\n[bold]网格化:[/bold] {use_res}° 分辨率")
        prepared = prepare_swath_grid(
            swath.lon,
            swath.lat,
            swath.values,
            read_extent,
            use_res,
            info.geometry,
            smooth_sigma=use_smooth,
        )
        display_source = prepared.unmasked_values
        swath_meta = {
            "n_pixels": int(swath.n_pixels),
            "n_files": int(swath.n_files),
            "n_broken": int(swath.n_broken),
            "qa_threshold": use_qa,
            "cloud_fraction_max": cf,
            "resolution_deg": use_res,
        }
    display_lon, display_lat = prepared.lon, prepared.lat
    display_support = None
    if sensor == "gems":
        from rsplot.geo.footprints import prepare_footprint_display

        display = prepare_footprint_display(
            prepared.lon,
            prepared.lat,
            display_source,
            info.geometry,
            analysis_res=use_res,
            display_res=use_res,
            smooth_sigma=use_smooth,
        )
        display_lon, display_lat = display.lon, display.lat
        display_grid, display_support = display.values, display.support
        swath_meta["resolution_deg"] = use_res
        swath_meta["analysis_resolution_deg"] = use_res
        swath_meta["display_resolution_deg"] = use_res
        swath_meta["display_support"] = "analysis_valid_cells"
    else:
        display_grid = prepare_display_grid(
            prepared.lon,
            prepared.lat,
            display_source,
            info.geometry,
            smooth_sigma=use_smooth,
        )
    if not np.isfinite(display_grid).any():
        console.print("[red]目标区域没有相交的有效卫星网格。[/red]")
        raise typer.Exit(1)
    console.print(
        f"  → 网格 {prepared.values.shape}, "
        f"区域内覆盖率 {prepared.coverage_pct:.1f}% "
        f"({prepared.n_valid_region}/{prepared.total_region_pixels})"
    )

    if vmin is not None and vmax is not None:
        use_vmin, use_vmax = vmin, vmax
    elif prod_info.vmin is not None and prod_info.vmax is not None:
        use_vmin = vmin if vmin is not None else prod_info.vmin
        use_vmax = vmax if vmax is not None else prod_info.vmax
    else:
        auto_min, auto_max = auto_vrange(
            prepared.values
            if np.isfinite(prepared.values).any()
            else display_grid,
            prod_info,
        )
        use_vmin = vmin if vmin is not None else auto_min
        use_vmax = vmax if vmax is not None else auto_max
    try:
        validate_color_range(use_vmin, use_vmax)
    except ValueError as e:
        console.print(f"[red]色标范围无效：{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    use_station_dir = (
        station_dir if station_dir is not None else cfg.get_data_dir("guokong")
    )
    console.print(f"\n[bold]读取站点数据:[/bold] {use_station_dir}")
    console.print(f"  时间: {station_request}, 变量: {var}")
    station_extent = buffered_extent(info.extent, 0.5)
    data, resolved_dt = read_stations(
        use_station_dir,
        station_request,
        var,
        extent=station_extent,
    )
    data = mask_stations_to_region(data, info.geometry)
    if resolved_dt != station_request:
        console.print(f"  → 自动选择最新时次: [cyan]{resolved_dt}[/cyan]")
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

    if output is None and sensor == "gems":
        output = (
            f"/tmp/rsplot_overlay_gems_{info.name}_{product}_"
            f"{datetime_str}_{resolved_dt}.png"
        )
    if title is None and sensor == "gems":
        period = "daily mean" if len(datetime_str) == 8 else "scan"
        title = (
            f"GEMS {product.upper()} {datetime_str} {period} CST + "
            f"Station {var} {resolved_dt} CST - {info.name}"
        )
    if output is None:
        output = f"/tmp/rsplot_overlay_{info.name}_{product}_{resolved_dt}.png"
    unit = STATION_VAR_META[var][0]
    station_label = f"{var} ({unit})" if unit else var

    console.print("\n[bold]绘图中...[/bold]")
    plot_overlay(
        display_lon,
        display_lat,
        display_grid,
        data,
        info,
        raster_cmap=use_cmap,
        raster_vmin=use_vmin,
        raster_vmax=use_vmax,
        raster_label=prod_info.colorbar_label,
        station_threshold=threshold,
        station_label=station_label,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        hcho_cmap_file=cfg.hcho_cmap_file,
        title=title,
        output=output,
        **({"coverage_geometry": display_support} if sensor == "gems" else {}),
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    result = build_overlay_result(
        region=info,
        product=product,
        date=date,
        prod_info=prod_info,
        LON=prepared.lon,
        LAT=prepared.lat,
        grid=statistics_grid
        if statistics_grid is not None
        else prepared.values,
        swath_meta=swath_meta,
        time_matching=pairing,
        display_grid=display_grid,
        display_lon=display_lon,
        display_lat=display_lat,
        raster_vmin=use_vmin,
        raster_vmax=use_vmax,
        data=data,
        datetime_str=resolved_dt,
        threshold=threshold,
        unit=unit,
        cities_gdf=load_fallback_city_boundaries(
            info,
            cfg.require_geojson_dir(),
        ),
        output=output,
    )
    emit_result(result, output)
