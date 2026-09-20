"""Implementation service for the ``raster`` command."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import typer

from rsplot.commands.common import (
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

    from rsplot.geo.boundaries import RegionInfo


@dataclass
class RasterRun:
    """Prepared satellite layer and sidecar, independent of rendering."""

    lon: np.ndarray
    lat: np.ndarray
    grid: np.ndarray
    region: RegionInfo
    plot_options: dict[str, Any]
    result: dict[str, Any]


@satellite_errors
def run_raster(**kwargs: Any) -> None:
    """Prepare, render, and emit the administrative raster command."""
    from rsplot.plotting.raster import plot_raster
    from rsplot.results import emit_result

    run = prepare_raster(**kwargs)
    plot_raster(run.lon, run.lat, run.grid, run.region, **run.plot_options)
    emit_result(run.result, run.plot_options["output"])
    kwargs["console"].print(
        f"[bold green]✓ 已保存:[/bold green] {run.plot_options['output']}"
    )


def default_raster_n_min(product: str, window_n: int) -> int:
    """Return a product-aware threshold that fits the requested window."""
    if window_n < 1:
        raise ValueError("窗口至少需要 1 天。")
    if product.lower() == "hcho":
        preferred = max(3, math.ceil(window_n * 0.25))
    else:
        preferred = max(3, window_n // 2)
    return min(window_n, preferred)


def parse_raster_dates(
    date_arg: str,
    days: int | None,
) -> tuple[list[str], bool]:
    """Return validated dates and whether window semantics were requested."""
    from rsplot.temporal import parse_date_window, parse_yyyymmdd

    if days is not None and days < 1:
        raise ValueError("--days 必须 >= 1。")
    if "-" in date_arg:
        dates = parse_date_window(date_arg, default_days=0)
        window_mode = True
    elif days is not None:
        dates = parse_date_window(date_arg, default_days=days)
        window_mode = True
    else:
        if len(date_arg) != 8 or not date_arg.isdigit():
            raise ValueError(
                f"日期格式错误: '{date_arg}'，"
                "应为 YYYYMMDD 或 YYYYMMDD-YYYYMMDD"
            )
        parse_yyyymmdd(date_arg)
        dates = [date_arg]
        window_mode = False
    return dates, window_mode


def prepare_raster(
    *,
    region: str | RegionInfo,
    date_arg: str,
    product: str,
    sensor: str = "tropomi",
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
    cf: float = 0.5,
    console: Console,
) -> RasterRun:
    """Prepare a satellite layer for an administrative or supplied geometry."""
    from rsplot.geo.boundaries import RegionInfo, resolve_regions
    from rsplot.geo.processing import (
        buffered_extent,
        prepare_display_grid,
        prepare_existing_grid,
        prepare_swath_grid,
    )
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange
    from rsplot.results import build_raster_result
    from rsplot.temporal import compute_window_mean, read_scan_mean

    cfg = AppConfig.load()
    prod_info, use_qa = resolve_satellite(product, sensor, qa, cfg, console)
    sensor = prod_info.sensor
    scan_mode = sensor == "gems" and len(date_arg) == 12
    if scan_mode:
        from rsplot.readers.gems import parse_gems_time

        parse_gems_time(date_arg)
        if days is not None or n_min is not None:
            raise ValueError("GEMS 单次扫描不能同时使用 --days 或 --n-min。")
    try:
        dates, window_mode = parse_raster_dates(
            date_arg[:8] if scan_mode else date_arg, days
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    window_n = len(dates)
    use_n_min: int | None = None
    if n_min is not None and n_min < 1:
        console.print("[red]--n-min 必须 >= 1。[/red]")
        raise typer.Exit(1)
    if not window_mode and n_min is not None:
        console.print("[red]--n-min 仅用于日期范围或 --days 窗口。[/red]")
        raise typer.Exit(1)
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

    setup_fonts(cfg.font_dir)

    info = (
        region
        if isinstance(region, RegionInfo)
        else resolve_regions(region, cfg, level_override=level)
    )
    console.print(f"[bold]分析范围:[/bold] {info.name}")
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

    read_extent = buffered_extent(info.extent, 1.0)
    use_data_dir = (
        data_dir
        if data_dir is not None
        else cfg.get_data_dir(prod_info.data_key or product)
    )
    reader = prod_info.reader_cls()
    reader.cloud_fraction_max = cf
    if sensor == "gems":
        console.print(f"  → GEMS 目标网格 {use_res}°（分析与显示）")
    swath_meta: dict[str, Any]
    window_meta: dict[str, Any] | None = None
    scientific_valid_mask: np.ndarray | None = None

    if not window_mode:
        console.print(
            f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})"
        )
        console.print(
            f"  时间: {date_arg}, {satellite_filter_label(sensor, use_qa, cf)}"
        )
        if sensor == "gems":
            batch = read_scan_mean(
                reader=reader,
                data_dir=use_data_dir,
                request=date_arg,
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
            swath_meta = {
                "n_pixels": batch.n_pixels,
                "n_files": batch.n_files,
                "n_broken": batch.n_broken,
                "resolution_deg": use_res,
                "cloud_fraction_max": cf,
                **batch.metadata,
            }
            scientific_valid_mask = np.isfinite(prepared.values)
        else:
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
                "cloud_fraction_max": cf,
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
        console.print(f"  {satellite_filter_label(sensor, use_qa, cf)}")
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
            fill_gaps=False,
        )
        scientific_valid_mask = np.isfinite(prepared.values)

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
            "cloud_fraction_max": cf,
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

        if sensor == "gems":
            swath_meta.pop("qa_threshold", None)
            window_meta["aggregation"] = "equal_day_mean_of_equal_scan_means"
            window_meta["daily"] = window.daily_metadata

    display_source = prepared.unmasked_values
    statistics_grid = prepared.values.copy() if sensor == "gems" else None
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
        console.print(
            "[red]窗口均值全区无有效像元，可能原因：窗口内覆盖不足，"
            "或 --n-min 太严。可放宽 --n-min / 扩大窗口。[/red]"
        )
        raise typer.Exit(1)

    if (
        sensor != "gems"
        and use_smooth is not None
        and np.isfinite(prepared.values).any()
    ):
        console.print(f"  → 高斯平滑 sigma={use_smooth}")
        prepared = prepare_existing_grid(
            prepared.lon,
            prepared.lat,
            prepared.values,
            info.geometry,
            fill_gaps=False,
            smooth_sigma=use_smooth,
        )
        if scientific_valid_mask is not None:
            restored = np.where(
                scientific_valid_mask,
                prepared.values,
                np.nan,
            )
            prepared = prepare_existing_grid(
                prepared.lon,
                prepared.lat,
                restored,
                info.geometry,
                fill_gaps=False,
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

    if output is None and sensor == "gems":
        suffix = f"{dates[0]}_{dates[-1]}" if window_mode else date_arg
        output = f"/tmp/rsplot_gems_{product}_{info.name}_{suffix}.png"
    if output is None:
        if window_mode:
            output = f"/tmp/rsplot_{info.name}_{dates[0]}_{dates[-1]}.png"
        else:
            output = f"/tmp/rsplot_{info.name}_{dates[0]}.png"
    if title is None and sensor == "gems":
        period = (
            f"{dates[0]}~{dates[-1]} mean"
            if window_mode
            else (
                f"{date_arg} CST scan"
                if scan_mode
                else f"{date_arg} daily mean (CST)"
            )
        )
        title = f"GEMS {product.upper()} - {info.name} ({period})"
    if title is None and window_mode:
        title = (
            f"TROPOMI {product.upper()} - {info.name} "
            f"({dates[0]}~{dates[-1]}, {window_n}d mean)"
        )

    plot_options = dict(
        dpi=use_dpi,
        cmap=use_cmap,
        vmin=use_vmin,
        vmax=use_vmax,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=title,
        output=output,
        **({"coverage_geometry": display_support} if sensor == "gems" else {}),
        colorbar_label=prod_info.colorbar_label,
    )

    result = build_raster_result(
        region=info,
        product=product,
        date=dates[0] if not window_mode else dates[-1],
        prod_info=prod_info,
        LON=prepared.lon,
        LAT=prepared.lat,
        grid=statistics_grid
        if statistics_grid is not None
        else prepared.values,
        swath_meta=swath_meta,
        vmin=use_vmin,
        vmax=use_vmax,
        output=output,
        window=window_meta,
        display_grid=display_grid,
        display_lon=display_lon,
        display_lat=display_lat,
    )
    return RasterRun(
        display_lon, display_lat, display_grid, info, plot_options, result
    )
