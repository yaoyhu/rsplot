"""Implementation service for the ``raster`` command."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import typer

from rsplot.commands.common import warn_missing_tianditu_key
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def default_raster_n_min(product: str, window_n: int) -> int:
    """Return the existing product-aware valid-day threshold."""
    if product.lower() == "hcho":
        return max(3, math.ceil(window_n * 0.25))
    return max(3, window_n // 2)


def parse_raster_dates(
    date_arg: str,
    days: int | None,
) -> tuple[list[str], bool]:
    """Return dates and the established single-day/window mode decision."""
    from rsplot.temporal import parse_date_window

    if "-" in date_arg:
        dates = parse_date_window(date_arg, default_days=0)
    elif days is not None:
        dates = parse_date_window(date_arg, default_days=days)
    else:
        if len(date_arg) != 8 or not date_arg.isdigit():
            raise ValueError(
                f"日期格式错误: '{date_arg}'，"
                "应为 YYYYMMDD 或 YYYYMMDD-YYYYMMDD"
            )
        dates = [date_arg]
    return dates, len(dates) > 1


def run_raster(
    *,
    region: str,
    date_arg: str,
    product: str,
    days: int | None,
    n_min: int | None,
    level: str | None,
    data_dir: str | None,
    output: str | None,
    dpi: int | None,
    res: float | None,
    basemap: str | None,
    vmin: float | None,
    vmax: float | None,
    cmap: str | None,
    smooth: float | None,
    title: str | None,
    qa: float | None,
    console: Console,
) -> None:
    """Execute raster orchestration without owning the Typer signature."""
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.processing import (
        buffered_extent,
        prepare_existing_grid,
        prepare_swath_grid,
    )
    from rsplot.plotting.raster import plot_raster
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange, get_product_info
    from rsplot.results import build_raster_result, emit_result
    from rsplot.temporal import compute_window_mean

    try:
        dates, window_mode = parse_raster_dates(date_arg, days)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    window_n = len(dates)
    use_n_min: int | None = None
    if window_mode:
        use_n_min = (
            n_min
            if n_min is not None
            else default_raster_n_min(product, window_n)
        )
        if use_n_min > window_n:
            console.print(
                f"[red]--n-min ({use_n_min}) 大于窗口天数 ({window_n})[/red]"
            )
            raise typer.Exit(1)

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
    prod_info = get_product_info(product)
    product_defaults = prod_info.defaults_for_level(info.level)
    use_res = (
        res
        if res is not None
        else product_defaults.res
        if product_defaults.res is not None
        else params.res
    )
    use_cmap = cmap if cmap is not None else prod_info.cmap
    use_qa = qa if qa is not None else cfg.qa_threshold
    use_smooth = (
        smooth
        if smooth is not None
        else product_defaults.smooth_sigma
        if product_defaults.smooth_sigma is not None
        else params.smooth_sigma
    )
    use_basemap = (
        basemap.lower() == "satellite" if basemap is not None else None
    )
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    read_extent = buffered_extent(info.extent, 1.0)
    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir(product)
    )
    reader = prod_info.reader_cls()
    swath_meta: dict[str, Any]
    window_meta: dict[str, Any] | None = None

    if not window_mode:
        console.print(
            f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})"
        )
        console.print(f"  日期: {dates[0]}, QA > {use_qa}")
        swath = reader.read(
            use_data_dir,
            dates[0],
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
        )
        swath_meta = {
            "n_pixels": int(swath.n_pixels),
            "n_files": int(swath.n_files),
            "n_broken": int(swath.n_broken),
            "qa_threshold": use_qa,
            "resolution_deg": use_res,
        }
    else:
        assert use_n_min is not None
        console.print(
            f"\n[bold]时间窗口:[/bold] {dates[0]} ~ {dates[-1]} "
            f"({window_n} 天，每像元至少 {use_n_min} 天有效)"
        )
        console.print(
            f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})"
        )
        console.print(f"  QA > {use_qa}")
        window = compute_window_mean(
            reader=reader,
            data_dir=use_data_dir,
            dates=dates,
            extent=read_extent,
            res=use_res,
            qa_threshold=use_qa,
            label=product.upper(),
            console=console,
        )
        console.print(
            f"  → 有效天数 [green]{len(window.dates_found)}[/green] / "
            f"{window_n} (失败 {len(window.dates_failed)})，累计 "
            f"[green]{window.n_pixels_total}[/green] 像元 "
            f"({window.n_files_total} 文件, {window.n_broken_total} 损坏)"
        )
        mean_grid = window.grid.copy()
        mean_grid[window.n_valid < use_n_min] = np.nan
        prepared = prepare_existing_grid(
            window.LON,
            window.LAT,
            mean_grid,
            info.geometry,
            fill_gaps=True,
        )

        covered = window.n_valid[window.n_valid > 0]
        coverage_days: dict[str, Any] = {
            "min": int(covered.min()) if len(covered) else 0,
            "max": int(covered.max()) if len(covered) else 0,
            "mean": round(float(covered.mean()), 1) if len(covered) else 0.0,
        }
        if len(covered):
            coverage_days.update(
                {
                    "p10": int(np.percentile(covered, 10)),
                    "p25": int(np.percentile(covered, 25)),
                    "median": int(np.percentile(covered, 50)),
                    "p75": int(np.percentile(covered, 75)),
                    "p90": int(np.percentile(covered, 90)),
                }
            )
        swath_meta = {
            "n_pixels_total": int(window.n_pixels_total),
            "n_files_total": int(window.n_files_total),
            "n_broken_total": int(window.n_broken_total),
            "qa_threshold": use_qa,
            "resolution_deg": use_res,
        }
        window_meta = {
            "start": dates[0],
            "end": dates[-1],
            "n_days_requested": window_n,
            "n_days_found": len(window.dates_found),
            "n_min": use_n_min,
            "n_min_default": n_min is None,
            "dates_failed": window.dates_failed,
            "coverage_days": coverage_days,
        }

    if not np.isfinite(prepared.values).any():
        console.print(
            "[red]窗口均值全区无有效像元，可能原因：窗口内覆盖不足，"
            "或 --n-min 太严。可放宽 --n-min / 扩大窗口。[/red]"
        )
        raise typer.Exit(1)

    if use_smooth is not None:
        console.print(f"  → 高斯平滑 sigma={use_smooth}")
        prepared = prepare_existing_grid(
            prepared.lon,
            prepared.lat,
            prepared.values,
            info.geometry,
            fill_gaps=False,
            smooth_sigma=use_smooth,
        )
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
        auto_min, auto_max = auto_vrange(prepared.values, prod_info)
        use_vmin = vmin if vmin is not None else auto_min
        use_vmax = vmax if vmax is not None else auto_max
    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    if output is None:
        if window_mode:
            output = f"/tmp/rsplot_{info.name}_{dates[0]}_{dates[-1]}.png"
        else:
            output = f"/tmp/rsplot_{info.name}_{dates[0]}.png"
    if title is None and window_mode:
        title = (
            f"TROPOMI {product.upper()} - {info.name} "
            f"({dates[0]}~{dates[-1]}, {window_n}d mean)"
        )

    console.print("\n[bold]绘图中...[/bold]")
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
        colorbar_label=prod_info.colorbar_label,
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    result = build_raster_result(
        region=info,
        product=product,
        date=dates[0] if not window_mode else dates[-1],
        prod_info=prod_info,
        LON=prepared.lon,
        LAT=prepared.lat,
        grid=prepared.values,
        swath_meta=swath_meta,
        vmin=use_vmin,
        vmax=use_vmax,
        output=output,
        window=window_meta,
    )
    emit_result(result, output)
