"""Implementation service for the ``trend`` command."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import validate_positive
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.readers.guokong import RegionStationSeries


def run_trend(
    *,
    target: str,
    date_arg: str,
    days: int,
    var: str,
    region_mode: bool,
    view: str,
    focus_station_ids: list[str] | None,
    threshold: float | None,
    level: str | None,
    data_dir: str | None,
    output: str | None,
    dpi: int | None,
    title: str | None,
    console: Console,
) -> None:
    """Read and plot a single-station or regional hourly trend."""
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.geo.boundaries import resolve_region
    from rsplot.plotting.styles import setup_fonts
    from rsplot.temporal import parse_date_window

    if days < 1:
        console.print("[red]--days 必须 >= 1[/red]")
        raise typer.Exit(1)
    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)
    use_view = view.lower()
    if use_view not in ("lines", "mean"):
        console.print("[red]--view 仅支持 lines / mean[/red]")
        raise typer.Exit(1)
    if not region_mode and use_view != "lines":
        console.print("[red]--view 仅用于 --region 区域趋势[/red]")
        raise typer.Exit(1)
    if not region_mode and focus_station_ids:
        console.print("[red]--focus-station 仅用于 --region 区域趋势[/red]")
        raise typer.Exit(1)
    if not region_mode and level is not None:
        console.print("[red]--level 仅用于 --region 区域趋势[/red]")
        raise typer.Exit(1)
    if threshold is not None and (
        not math.isfinite(threshold) or threshold < 0
    ):
        console.print("[red]--threshold 必须是大于等于 0 的有限数字[/red]")
        raise typer.Exit(1)

    try:
        dates = parse_date_window(date_arg, default_days=days)
        requested_focus_ids = _normalize_focus_ids(focus_station_ids or [])
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)
    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir("guokong")
    )
    use_threshold = (
        threshold if threshold is not None else get_exceedance_threshold(var)
    )
    use_dpi = dpi if dpi is not None else cfg.dpi
    try:
        validate_positive(use_dpi, "--dpi")
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    if region_mode:
        try:
            info = resolve_region(target, cfg, level_override=level)
        except (FileNotFoundError, ValueError) as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1) from error
        _run_region_trend(
            info=info,
            dates=dates,
            var=var,
            data_dir=use_data_dir,
            view=use_view,
            focus_station_ids=requested_focus_ids,
            threshold=use_threshold,
            unit=STATION_VAR_META[var][0],
            dpi=use_dpi,
            output=output,
            title=title,
            console=console,
        )
        return

    _run_single_trend(
        station_id=target,
        dates=dates,
        var=var,
        data_dir=use_data_dir,
        threshold=use_threshold,
        unit=STATION_VAR_META[var][0],
        dpi=use_dpi,
        output=output,
        title=title,
        console=console,
    )


def _run_single_trend(
    *,
    station_id: str,
    dates: list[str],
    var: str,
    data_dir: str,
    threshold: float | None,
    unit: str,
    dpi: int,
    output: str | None,
    title: str | None,
    console: Console,
) -> None:
    from rsplot.plotting.station_trend import plot_station_trend
    from rsplot.readers.guokong import read_station_series
    from rsplot.results import build_station_trend_result, emit_result

    console.print(f"[bold]读取站点序列:[/bold] {data_dir}")
    console.print(
        f"  站点: {station_id}, 变量: {var}, "
        f"窗口: {dates[0]} ~ {dates[-1]} ({len(dates)} 天)"
    )
    try:
        series = read_station_series(data_dir, station_id, dates, var)
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

    use_output = output or (
        f"/tmp/rsplot_trend_{series.station_id}_{var}_"
        f"{dates[0]}_{dates[-1]}.png"
    )
    console.print("\n[bold]绘图中...[/bold]")
    plot_station_trend(
        series,
        unit=unit,
        threshold=threshold,
        dpi=dpi,
        output=use_output,
        title=title,
    )
    result = build_station_trend_result(
        series=series,
        dates=dates,
        threshold=threshold,
        unit=unit,
        output=use_output,
    )
    emit_result(result, use_output)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {use_output}")


def _run_region_trend(
    *,
    info: RegionInfo,
    dates: list[str],
    var: str,
    data_dir: str,
    view: str,
    focus_station_ids: list[str],
    threshold: float | None,
    unit: str,
    dpi: int,
    output: str | None,
    title: str | None,
    console: Console,
) -> None:
    from rsplot.plotting.station_trend import plot_region_station_trend
    from rsplot.readers.guokong import read_region_station_series
    from rsplot.results import build_region_trend_result, emit_result

    console.print(f"[bold]解析区域:[/bold] {info.name} ({info.level})")
    console.print(f"[bold]读取区域站点序列:[/bold] {data_dir}")
    console.print(
        f"  变量: {var}, 窗口: {dates[0]} ~ {dates[-1]} "
        f"({len(dates)} 天), 视图: {view}"
    )
    try:
        series = read_region_station_series(
            data_dir,
            dates,
            var,
            info.geometry,
        )
    except (FileNotFoundError, ValueError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    if series.n_valid == 0:
        console.print("[red]指定窗口内目标区域没有有效观测值。[/red]")
        raise typer.Exit(1)
    try:
        canonical_focus_ids = _resolve_focus_ids(series, focus_station_ids)
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error
    console.print(
        f"  → [green]{series.n_stations}[/green] 个站点，"
        f"[green]{series.n_valid}[/green] 个有效观测值，"
        f"缺少文件 {len(series.missing_files)}，"
        f"读取失败 {len(series.failed_files)}"
    )
    if canonical_focus_ids:
        console.print(f"  → 重点站: {', '.join(canonical_focus_ids)}")
    if threshold is not None:
        exceed_mask = np.isfinite(series.values) & (series.values > threshold)
        n_exceed_stations = int(exceed_mask.any(axis=1).sum())
        console.print(
            f"  → 超标阈值: {threshold:g}, "
            f"窗口内超标站点: [red]{n_exceed_stations}[/red]"
        )

    use_output = output or (
        f"/tmp/rsplot_trend_{info.name}_{var}_{dates[0]}_{dates[-1]}.png"
    )
    console.print("\n[bold]绘图中...[/bold]")
    plot_region_station_trend(
        series,
        region_name=info.name,
        unit=unit,
        threshold=threshold,
        view=view,
        focus_station_ids=canonical_focus_ids,
        dpi=dpi,
        output=use_output,
        title=title,
    )
    result = build_region_trend_result(
        series=series,
        region=info,
        dates=dates,
        threshold=threshold,
        unit=unit,
        view=view,
        focus_station_ids=canonical_focus_ids,
        output=use_output,
    )
    emit_result(result, use_output)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {use_output}")


def _normalize_focus_ids(station_ids: list[str]) -> list[str]:
    """Normalize and de-duplicate requested focus IDs in input order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for station_id in station_ids:
        value = station_id.strip().upper()
        if not value:
            raise ValueError("--focus-station 不能为空")
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _resolve_focus_ids(
    series: RegionStationSeries,
    requested: list[str],
) -> list[str]:
    """Return canonical focus IDs after region and data validation."""
    missing: list[str] = []
    empty: list[str] = []
    canonical: list[str] = []
    for station_id in requested:
        index = series.station_index(station_id)
        if index is None:
            missing.append(station_id)
            continue
        if not np.isfinite(series.values[index]).any():
            empty.append(station_id)
            continue
        canonical.append(str(series.station_ids[index]))
    if missing:
        raise ValueError(
            f"--focus-station 不在目标区域内: {', '.join(missing)}"
        )
    if empty:
        raise ValueError(
            f"--focus-station 在窗口内没有有效值: {', '.join(empty)}"
        )
    return canonical
