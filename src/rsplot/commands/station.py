"""Implementation service for the ``station`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import warn_missing_tianditu_key
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def run_station(
    *,
    region: str,
    datetime_str: str,
    var: str,
    level: str | None,
    data_dir: str | None,
    output: str | None,
    dpi: int | None,
    basemap: str | None,
    wind_level: str | None,
    wind_data_dir: str | None,
    station_timezone: str,
    wind_stride: int | None,
    wind_scale: float | None,
    wind_width: float,
    wind_cmap: str,
    wind_vmin: float | None,
    wind_vmax: float | None,
    title: str | None,
    console: Console,
) -> None:
    """Execute station plotting without owning the Typer signature."""
    from rsplot.config import (
        STATION_VAR_LABELS,
        STATION_VAR_META,
        get_exceedance_threshold,
    )
    from rsplot.geo.boundaries import (
        load_city_boundaries,
        resolve_region,
    )
    from rsplot.geo.processing import buffered_extent
    from rsplot.plotting.station import plot_station, wind_stride_for_shape
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers.era5_wind import mask_wind_to_region, read_era5_wind
    from rsplot.readers.guokong import mask_stations_to_region, read_stations
    from rsplot.results import build_station_result, emit_result

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)

    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    params = info.params

    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir("guokong")
    )
    console.print(f"\n[bold]读取站点数据:[/bold] {use_data_dir}")
    console.print(f"  时间: {datetime_str}, 变量: {var}")
    read_extent = buffered_extent(info.extent, 0.5)
    data, resolved_dt = read_stations(
        use_data_dir,
        datetime_str,
        var,
        extent=read_extent,
    )
    data = mask_stations_to_region(data, info.geometry)
    if resolved_dt != datetime_str:
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

    wind_data = None
    use_wind_stride = None
    if wind_level is not None:
        if wind_stride is not None and wind_stride < 1:
            console.print("[red]--wind-stride 必须大于等于 1。[/red]")
            raise typer.Exit(1)
        if wind_scale is not None and wind_scale <= 0:
            console.print("[red]--wind-scale 必须大于 0。[/red]")
            raise typer.Exit(1)
        if wind_width <= 0:
            console.print("[red]--wind-width 必须大于 0。[/red]")
            raise typer.Exit(1)
        if (
            wind_vmin is not None
            and wind_vmax is not None
            and wind_vmax <= wind_vmin
        ):
            console.print("[red]--wind-vmax 必须大于 --wind-vmin。[/red]")
            raise typer.Exit(1)

        use_wind_data_dir = (
            wind_data_dir
            if wind_data_dir is not None
            else cfg.get_data_dir("era5")
        )
        console.print(f"\n[bold]读取 ERA5 风场:[/bold] {use_wind_data_dir}")
        console.print(
            f"  站点时次: {resolved_dt} ({station_timezone}), "
            f"层次: {wind_level}"
        )
        try:
            wind_data = read_era5_wind(
                use_wind_data_dir,
                resolved_dt,
                wind_level,
                read_extent,
                station_timezone=station_timezone,
            )
            wind_data = mask_wind_to_region(wind_data, info.geometry)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        if wind_data.n_valid == 0:
            console.print("[red]目标区域内没有有效 ERA5 风矢量。[/red]")
            raise typer.Exit(1)

        use_wind_stride = (
            wind_stride
            if wind_stride is not None
            else wind_stride_for_shape(wind_data.speed.shape, info.level)
        )
        console.print(
            f"  → ERA5 UTC 时次: [cyan]{wind_data.datetime_utc}[/cyan], "
            f"有效网格: [green]{wind_data.n_valid}[/green], "
            f"抽稀步长: {use_wind_stride}"
        )

    use_dpi = dpi if dpi is not None else cfg.dpi
    use_basemap = (
        basemap.lower() == "satellite" if basemap is not None else None
    )
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    unit = STATION_VAR_META[var][0]
    display_var = STATION_VAR_LABELS.get(var, var)
    colorbar_label = f"{display_var} ({unit})" if unit else display_var
    use_title = title
    if use_title is None and display_var != var:
        if wind_data is None:
            use_title = f"{display_var} - {info.name}"
        else:
            use_title = (
                f"{display_var} + ERA5 {wind_data.level} wind - {info.name}"
            )

    if output is None:
        wind_suffix = (
            f"_wind{wind_data.level}" if wind_data is not None else ""
        )
        output = (
            f"/tmp/rsplot_station_{info.name}_{var}_{resolved_dt}"
            f"{wind_suffix}.png"
        )

    console.print("\n[bold]绘图中...[/bold]")
    plot_station(
        data,
        info,
        wind=wind_data,
        wind_stride=use_wind_stride or 1,
        wind_scale=wind_scale,
        wind_width=wind_width,
        wind_cmap=wind_cmap,
        wind_vmin=wind_vmin,
        wind_vmax=wind_vmax,
        threshold=threshold,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=use_title,
        output=output,
        colorbar_label=colorbar_label,
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    result = build_station_result(
        region=info,
        data=data,
        datetime_str=resolved_dt,
        threshold=threshold,
        unit=unit,
        cities_gdf=load_city_boundaries(cfg.require_geojson_dir()),
        output=output,
        wind=wind_data,
        wind_stride=use_wind_stride,
    )
    emit_result(result, output)
