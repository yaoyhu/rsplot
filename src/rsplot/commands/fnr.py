"""Implementation service for the ``fnr`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import (
    print_failed_dates,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def run_fnr(
    *,
    region: str,
    date_arg: str,
    days: int,
    n_min: int | None,
    no2_min: float,
    voc_threshold: float,
    nox_threshold: float,
    display_max: float,
    level: str | None,
    raster_dir_no2: str | None,
    raster_dir_hcho: str | None,
    output: str | None,
    dpi: int | None,
    res: float | None,
    basemap: str | None,
    smooth: float | None,
    qa: float | None,
    cf: float = 0.5,
    title: str | None,
    console: Console,
) -> None:
    """Execute FNR orchestration without owning the Typer signature."""
    from rsplot.fnr import (
        compute_fnr,
        regime_percentages,
        validate_fnr_thresholds,
    )
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.gridding import grid_coverage_in_region
    from rsplot.plotting.fnr import plot_fnr
    from rsplot.plotting.styles import setup_fonts
    from rsplot.results import build_fnr_result, emit_result
    from rsplot.temporal import parse_date_window

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    try:
        dates = parse_date_window(date_arg, default_days=days)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    window_n = len(dates)
    use_n_min = n_min if n_min is not None else max(3, window_n // 2)
    if use_n_min > window_n:
        console.print(
            f"[red]--n-min ({use_n_min}) 大于窗口天数 ({window_n})[/red]"
        )
        raise typer.Exit(1)
    try:
        use_voc_threshold, use_nox_threshold, use_display_max = (
            validate_fnr_thresholds(
                voc_threshold=voc_threshold,
                nox_threshold=nox_threshold,
                display_max=display_max,
            )
        )
    except ValueError as e:
        console.print(f"[red]FNR 阈值错误: {e}[/red]")
        raise typer.Exit(1) from e

    console.print(
        f"[bold]时间窗口:[/bold] {dates[0]} ~ {dates[-1]} "
        f"({window_n} 天，每像元至少 {use_n_min} 天有效)"
    )
    console.print(
        f"[bold]FNR 分级:[/bold] VOC<{use_voc_threshold:g}, "
        f"transition {use_voc_threshold:g}~{use_nox_threshold:g}, "
        f"NOx>{use_nox_threshold:g}"
    )

    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")

    params = info.params
    use_res = res if res is not None else params.res
    use_dpi = dpi if dpi is not None else cfg.dpi
    use_qa = qa if qa is not None else cfg.qa_threshold
    use_smooth = smooth if smooth is not None else params.smooth_sigma

    use_basemap = (
        basemap.lower() == "satellite" if basemap is not None else None
    )
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    use_no2_dir = (
        raster_dir_no2
        if raster_dir_no2 is not None
        else cfg.get_data_dir("no2")
    )
    use_hcho_dir = (
        raster_dir_hcho
        if raster_dir_hcho is not None
        else cfg.get_data_dir("hcho")
    )
    console.print("\n[bold]读取数据:[/bold]")
    console.print(f"  NO2 : {use_no2_dir}")
    console.print(f"  HCHO: {use_hcho_dir}")
    console.print(f"  QA > {use_qa}, CF <= {cf}")

    fnr_out = compute_fnr(
        info,
        dates,
        res=use_res,
        qa_threshold=use_qa,
        cloud_fraction_max=cf,
        n_min=use_n_min,
        raster_dir_no2=use_no2_dir,
        raster_dir_hcho=use_hcho_dir,
        no2_min_column=no2_min,
        smooth_sigma=use_smooth,
        console=console,
    )

    n_fail_no2 = len(fnr_out.dates_failed_no2)
    n_fail_hcho = len(fnr_out.dates_failed_hcho)
    n_found_no2 = len(fnr_out.dates_found_no2)
    n_found_hcho = len(fnr_out.dates_found_hcho)
    console.print(
        f"  → NO2 有效天数 {n_found_no2}/{window_n} (失败 {n_fail_no2})"
    )
    console.print(
        f"  → HCHO 有效天数 {n_found_hcho}/{window_n} (失败 {n_fail_hcho})"
    )
    if use_n_min > min(n_found_no2, n_found_hcho):
        console.print(
            f"  → [yellow]注意:[/yellow] n_min={use_n_min} 大于 NO2/HCHO "
            f"共同可用天数上限 {min(n_found_no2, n_found_hcho)}，"
            "本次不可能产生有效 FNR 像元。"
        )

    finite = fnr_out.fnr[np.isfinite(fnr_out.fnr)]
    if len(finite) == 0:
        print_failed_dates(
            "NO2",
            fnr_out.dates_failed_no2,
            console=console,
        )
        print_failed_dates(
            "HCHO",
            fnr_out.dates_failed_hcho,
            console=console,
        )
        console.print(
            "[red]FNR 全区无有效像元，可能原因：窗口内 NO2/HCHO 都覆盖不足，"
            "或 --n-min 太严。可放宽 --n-min / 扩大窗口。[/red]"
        )
        raise typer.Exit(1)

    coverage_pct, n_valid_region, total_region_pixels = (
        grid_coverage_in_region(
            fnr_out.LON,
            fnr_out.LAT,
            fnr_out.fnr,
            info.geometry,
        )
    )
    console.print(
        f"  → FNR 区域内覆盖率 {coverage_pct:.1f}% "
        f"({n_valid_region}/{total_region_pixels}), "
        f"中位数 {float(np.median(finite)):.2f}"
    )

    percentages = regime_percentages(
        fnr_out.fnr,
        voc_threshold=use_voc_threshold,
        nox_threshold=use_nox_threshold,
    )
    console.print(
        f"  → Regime: [red]VOC-limited {percentages['voc_limited']}%[/red] | "
        f"[yellow]transition {percentages['transition']}%[/yellow] | "
        f"[blue]NOx-limited {percentages['nox_limited']}%[/blue]"
    )

    if output is None:
        output = f"/tmp/rsplot_fnr_{info.name}_{dates[0]}_{dates[-1]}.png"

    subtitle = (
        f"{dates[0]}~{dates[-1]}  ·  N_days={window_n} "
        f"(n_min={use_n_min})  ·  NO2≥{no2_min:g}×10¹⁵ molec/cm²"
    )
    console.print("\n[bold]绘图中...[/bold]")
    plot_fnr(
        fnr_out.LON,
        fnr_out.LAT,
        fnr_out.fnr,
        info,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=title,
        output=output,
        subtitle=subtitle,
        voc_threshold=use_voc_threshold,
        nox_threshold=use_nox_threshold,
        display_max=use_display_max,
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    result = build_fnr_result(
        region=info,
        fnr_out=fnr_out,
        res=use_res,
        output=output,
        qa_threshold=use_qa,
        cloud_fraction_max=cf,
        voc_threshold=use_voc_threshold,
        nox_threshold=use_nox_threshold,
        display_max=use_display_max,
    )
    emit_result(result, output)
