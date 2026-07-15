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
    from rsplot.plotting.station import plot_station
    from rsplot.plotting.styles import setup_fonts
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

    use_data_dir = data_dir or cfg.get_data_dir("guokong")
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

    use_dpi = dpi if dpi is not None else cfg.dpi
    use_basemap = (
        basemap.lower() == "satellite" if basemap is not None else None
    )
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=info.params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    unit = STATION_VAR_META[var][0]
    display_var = STATION_VAR_LABELS.get(var, var)
    colorbar_label = f"{display_var} ({unit})" if unit else display_var
    use_title = title
    if use_title is None and display_var != var:
        use_title = f"{display_var} - {info.name}"

    if output is None:
        output = f"/tmp/rsplot_station_{info.name}_{var}_{resolved_dt}.png"

    console.print("\n[bold]绘图中...[/bold]")
    plot_station(
        data,
        info,
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
    )
    emit_result(result, output)
