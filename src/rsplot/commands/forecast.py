"""Implementation service for the ``forecast`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import (
    FORECAST_STATION_PAIR,
    load_fallback_city_boundaries,
    parse_basemap,
    validate_color_range,
    validate_non_negative,
    validate_positive,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def run_forecast(
    *,
    region: str,
    datetime_str: str,
    var: str,
    lead: int,
    level: str | None,
    data_dir: str | None,
    station_overlay: bool,
    station_var: str | None,
    station_data_dir: str | None,
    station_datetime: str | None,
    output: str | None,
    dpi: int | None,
    basemap: str | None,
    vmin: float | None,
    vmax: float | None,
    cmap: str | None,
    smooth: float | None,
    title: str | None,
    console: Console,
) -> None:
    """Execute forecast orchestration without owning the Typer signature."""
    from rsplot.config import (
        STATION_VAR_LABELS,
        STATION_VAR_META,
        get_exceedance_threshold,
    )
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.processing import (
        buffered_extent,
        prepare_existing_grid,
    )
    from rsplot.plotting.colormaps import STATION_CONCENTRATION_CMAP
    from rsplot.plotting.overlay import plot_overlay
    from rsplot.plotting.raster import plot_raster
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers.forecast import (
        auto_forecast_vrange,
        get_forecast_var_info,
        read_forecast,
    )
    from rsplot.readers.guokong import mask_stations_to_region, read_stations
    from rsplot.results import build_forecast_result, emit_result

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    console.print(
        f"  → 范围: {info.extent[0]:.2f}°~{info.extent[1]:.2f}°E, "
        f"{info.extent[2]:.2f}°~{info.extent[3]:.2f}°N"
    )

    params = info.params
    use_dpi = dpi if dpi is not None else cfg.dpi
    use_cmap = cmap if cmap is not None else STATION_CONCENTRATION_CMAP
    try:
        use_basemap = parse_basemap(basemap)
        validate_positive(use_dpi, "--dpi")
        validate_color_range(vmin, vmax)
        if smooth is not None:
            validate_non_negative(smooth, "--smooth")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    try:
        var_info = get_forecast_var_info(var)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    try:
        use_data_dir = (
            data_dir if data_dir is not None else cfg.get_data_dir("forecast")
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    read_extent = buffered_extent(info.extent, 0.5)
    console.print(
        f"\n[bold]读取预报数据:[/bold] {use_data_dir} "
        f"(变量: {var_info.label}, 时效: {lead}h)"
    )
    console.print(f"  输入起报时次: {datetime_str} (中国时间)")
    try:
        forecast_data, resolved_dt = read_forecast(
            use_data_dir,
            datetime_str,
            lead,
            var,
            read_extent,
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if resolved_dt != datetime_str:
        console.print(
            f"  → 自动选择最新起报: [cyan]{resolved_dt}[/cyan] (中国时间)"
        )
    console.print(
        "  → UTC 归档起报: "
        f"[cyan]{forecast_data.archive_init_datetime}[/cyan], "
        "UTC 有效时次: "
        f"[cyan]{forecast_data.archive_valid_datetime}[/cyan]"
    )
    console.print(
        f"  → 预报有效时次: [cyan]{forecast_data.valid_datetime}[/cyan] "
        "(中国时间), 有效网格: "
        f"[green]{forecast_data.n_valid}[/green] / {forecast_data.n_cells}"
    )

    prepared = prepare_existing_grid(
        forecast_data.lon,
        forecast_data.lat,
        forecast_data.values,
        info.geometry,
        fill_gaps=False,
    )
    if not np.isfinite(prepared.values).any():
        console.print("[red]目标区域内没有有效预报网格。[/red]")
        raise typer.Exit(1)
    if smooth is not None and smooth > 0:
        console.print(f"  → 高斯平滑 sigma={smooth}")
        prepared = prepare_existing_grid(
            prepared.lon,
            prepared.lat,
            prepared.values,
            info.geometry,
            fill_gaps=False,
            smooth_sigma=smooth,
        )
    console.print(
        f"  → 区域网格 {prepared.values.shape}, "
        f"区域内覆盖率 {prepared.coverage_pct:.1f}% "
        f"({prepared.n_valid_region}/{prepared.total_region_pixels})"
    )

    auto_min, auto_max = auto_forecast_vrange(prepared.values, var_info)
    use_vmin = vmin if vmin is not None else auto_min
    use_vmax = vmax if vmax is not None else auto_max
    try:
        validate_color_range(use_vmin, use_vmax)
    except ValueError as e:
        console.print(f"[red]色标范围无效：{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    station_data = None
    station_resolved_dt = None
    station_threshold = None
    station_unit = ""
    station_colorbar_label = ""
    use_station_overlay = (
        station_overlay
        or station_var is not None
        or station_data_dir is not None
        or station_datetime is not None
    )
    if use_station_overlay:
        use_station_var = station_var or FORECAST_STATION_PAIR[var_info.name]
        if use_station_var not in STATION_VAR_META:
            available = ", ".join(STATION_VAR_META)
            console.print(
                f"[red]未知站点变量 '{use_station_var}'[/red]。"
                f"可用: {available}"
            )
            raise typer.Exit(1)
        try:
            use_station_data_dir = (
                station_data_dir
                if station_data_dir is not None
                else cfg.get_data_dir("guokong")
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e

        use_station_datetime = station_datetime or forecast_data.valid_datetime
        console.print(f"\n[bold]读取站点数据:[/bold] {use_station_data_dir}")
        console.print(
            f"  时间: {use_station_datetime}, 变量: {use_station_var}"
        )
        try:
            station_data, station_resolved_dt = read_stations(
                use_station_data_dir,
                use_station_datetime,
                use_station_var,
                extent=read_extent,
            )
        except (FileNotFoundError, KeyError, ValueError) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        station_data = mask_stations_to_region(station_data, info.geometry)
        if station_resolved_dt != use_station_datetime:
            console.print(
                f"  → 自动选择最新站点时次: [cyan]{station_resolved_dt}[/cyan]"
            )
        console.print(
            f"  → [green]{station_data.n_valid}[/green] 有效站点 "
            f"(共 {station_data.n_stations} 站)"
        )

        station_threshold = get_exceedance_threshold(use_station_var)
        if station_threshold is not None:
            n_exceed = int(
                np.sum(
                    station_data.values[np.isfinite(station_data.values)]
                    > station_threshold
                )
            )
            console.print(
                f"  → 超标阈值: {station_threshold}, "
                f"超标站点: [red]{n_exceed}[/red]"
            )
        station_unit = STATION_VAR_META[use_station_var][0]
        station_display_var = STATION_VAR_LABELS.get(
            use_station_var,
            use_station_var,
        )
        station_colorbar_label = (
            f"{station_display_var} ({station_unit})"
            if station_unit
            else station_display_var
        )

    if output is None:
        station_suffix = (
            f"_station{station_data.var_name}"
            if station_data is not None
            else ""
        )
        output = (
            f"/tmp/rsplot_forecast_{info.name}_{forecast_data.variable}_"
            f"{forecast_data.init_datetime}_f{forecast_data.lead_hour}"
            f"{station_suffix}.png"
        )
    if title is None:
        if station_data is None:
            title = (
                f"Forecast {forecast_data.label} - {info.name} "
                f"(valid {forecast_data.valid_datetime}, "
                f"+{forecast_data.lead_hour}h)"
            )
        else:
            title = (
                f"Forecast {forecast_data.label} + Station "
                f"{station_data.var_name} - {info.name} "
                f"(valid {forecast_data.valid_datetime}, "
                f"+{forecast_data.lead_hour}h)"
            )

    console.print("\n[bold]绘图中...[/bold]")
    if station_data is None:
        plot_raster(
            prepared.lon,
            prepared.lat,
            prepared.values,
            info,
            dpi=use_dpi,
            cmap=use_cmap,
            vmin=use_vmin,
            vmax=use_vmax,
            basemap=use_basemap,
            tianditu_key=cfg.tianditu_key,
            hcho_cmap_file=cfg.hcho_cmap_file,
            title=title,
            output=output,
            colorbar_label=var_info.colorbar_label,
        )
    else:
        plot_overlay(
            prepared.lon,
            prepared.lat,
            prepared.values,
            station_data,
            info,
            raster_cmap=use_cmap,
            raster_vmin=use_vmin,
            raster_vmax=use_vmax,
            raster_label=var_info.colorbar_label,
            station_threshold=station_threshold,
            station_label=station_colorbar_label,
            dpi=use_dpi,
            basemap=use_basemap,
            tianditu_key=cfg.tianditu_key,
            hcho_cmap_file=cfg.hcho_cmap_file,
            title=title,
            output=output,
        )

    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")
    result = build_forecast_result(
        region=info,
        data=forecast_data,
        LON=prepared.lon,
        LAT=prepared.lat,
        grid=prepared.values,
        vmin=use_vmin,
        vmax=use_vmax,
        output=output,
        station_data=station_data,
        station_datetime=station_resolved_dt,
        station_threshold=station_threshold,
        station_unit=station_unit,
        cities_gdf=(
            load_fallback_city_boundaries(
                info,
                cfg.require_geojson_dir(),
            )
            if station_data is not None
            else None
        ),
    )
    emit_result(result, output)
