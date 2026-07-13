"""Implementation service for the station-trend command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def run_station_trend(
    *,
    station_id: str,
    date_arg: str,
    days: int,
    var: str,
    data_dir: str | None,
    output: str | None,
    dpi: int | None,
    title: str | None,
    console: Console,
) -> None:
    """Read and plot one station's hourly observations."""
    from rsplot.config import (
        STATION_VAR_META,
        get_exceedance_threshold,
    )
    from rsplot.plotting.station_trend import plot_station_trend
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers.guokong import read_station_series
    from rsplot.results import build_station_trend_result, emit_result
    from rsplot.temporal import parse_date_window

    if days < 1:
        console.print("[red]--days 必须 >= 1[/red]")
        raise typer.Exit(1)
    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)
    try:
        dates = parse_date_window(date_arg, default_days=days)
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)
    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir("guokong")
    )
    console.print(f"[bold]读取站点序列:[/bold] {use_data_dir}")
    console.print(
        f"  站点: {station_id}, 变量: {var}, "
        f"窗口: {dates[0]} ~ {dates[-1]} ({len(dates)} 天)"
    )
    try:
        series = read_station_series(
            use_data_dir,
            station_id,
            dates,
            var,
        )
    except (FileNotFoundError, ValueError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    console.print(
        f"  → [green]{series.n_valid}[/green]/{series.n_hours} 小时有效，"
        f"缺少文件 {len(series.missing_files)}，"
        f"读取失败 {len(series.failed_files)}"
    )
    if series.n_valid == 0:
        console.print("[red]指定窗口内该站点没有有效观测值。[/red]")
        raise typer.Exit(1)

    if output is None:
        output = (
            f"/tmp/rsplot_station_trend_{series.station_id}_{var}_"
            f"{dates[0]}_{dates[-1]}.png"
        )

    unit = STATION_VAR_META[var][0]
    threshold = get_exceedance_threshold(var)
    use_dpi = dpi if dpi is not None else cfg.dpi

    console.print("\n[bold]绘图中...[/bold]")
    plot_station_trend(
        series,
        unit=unit,
        threshold=threshold,
        dpi=use_dpi,
        output=output,
        title=title,
    )
    result = build_station_trend_result(
        series=series,
        dates=dates,
        threshold=threshold,
        unit=unit,
        output=output,
    )
    emit_result(result, output)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")
