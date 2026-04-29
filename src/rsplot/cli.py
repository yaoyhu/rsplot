"""CLI command definitions for rsplot."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import typer
from rich.console import Console

from rsplot.config import AppConfig

console = Console()
app = typer.Typer(
    name="rsplot",
    help="CLI tool for Remote sensing raster plotting.",
    no_args_is_help=True,
)


def _warn_missing_tianditu_key(
    *,
    basemap: bool | None,
    default_basemap: bool,
    tianditu_key: str | None,
) -> None:
    """Warn when a requested TianDiTu basemap cannot be loaded."""
    use_basemap = basemap if basemap is not None else default_basemap
    if use_basemap and not tianditu_key:
        console.print(
            "[yellow]未设置天地图 API key，底图将不会加载。请设置 "
            "TIANDITU_API_KEY，或使用 --basemap none。[/yellow]"
        )


def _default_raster_n_min(product: str, window_n: int) -> int:
    """Return the product-aware default valid-day threshold for raster means.

    HCHO has much sparser day-to-day coverage than NO2/O3 after QA/cloud
    filtering. Requiring half the window for HCHO makes otherwise useful
    monthly means look holey, so use a softer default while still avoiding
    one-off pixels.
    """
    if product.lower() == "hcho":
        return max(3, math.ceil(window_n * 0.25))
    return max(3, window_n // 2)


@app.callback()
def _callback() -> None:
    "CLI tool for Remote sensing raster plotting."


@app.command()
def raster(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    date_arg: str = typer.Argument(
        ...,
        help="单日 YYYYMMDD 走单日路径；带 --days 或写成 YYYYMMDD-YYYYMMDD "
        "时切换为窗口均值（HCHO 单日覆盖率低，月均更可读）",
    ),
    # --- optional overrides ---
    product: str = typer.Option(
        "o3",
        "--product",
        "-p",
        help="产品类型: no2 / o3 / hcho",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help="时间窗口天数；不指定且 DATE 为单日时走单日路径。"
        "推荐值: 30 (月均，HCHO 首选) / 7 (周均) / 显式区间用 YYYYMMDD-YYYYMMDD",
    ),
    n_min: int | None = typer.Option(
        None,
        "--n-min",
        help=(
            "窗口模式下每像元最少有效天数。默认: NO2/O3=max(3, 天数//2), "
            "HCHO=max(3, ceil(天数*0.25))"
        ),
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径，不指定则弹窗显示。",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(None, "--vmin", help="Colorbar 最小值"),
    vmax: float | None = typer.Option(None, "--vmax", help="Colorbar 最大值"),
    cmap: str | None = typer.Option(None, "--cmap", help="Colormap 名称"),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
    qa: float | None = typer.Option(0.5, "--qa", help="QA 阈值 (0-1)"),
) -> None:
    """绘制卫星遥感栅格图。

    示例:
        rsplot raster 北京    20260108 --dpi 300 --output yrd.png        # 单日
        rsplot raster 安徽    20260131 -p hcho --days 30                 # 月均（推荐 HCHO）
        rsplot raster 长三角  20260101-20260131 -p no2                   # 显式区间
    """
    from rsplot.fnr import compute_window_mean, parse_date_window
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.gridding import (
        fill_nan_gaps,
        grid_data,
        mask_to_region,
        smooth_grid,
    )
    from rsplot.plotting.raster import plot_raster
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange, get_product_info
    from rsplot.results import build_raster_result, emit_result

    # --- 0. Decide: single-day or window mode ---
    is_range = "-" in date_arg
    try:
        if is_range:
            dates = parse_date_window(date_arg, default_days=0)
        elif days is not None:
            dates = parse_date_window(date_arg, default_days=days)
        else:
            # Single date + no --days → single-day mode (validated below)
            if len(date_arg) != 8 or not date_arg.isdigit():
                raise ValueError(
                    f"日期格式错误: '{date_arg}'，"
                    f"应为 YYYYMMDD 或 YYYYMMDD-YYYYMMDD"
                )
            dates = [date_arg]
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    window_mode = len(dates) > 1
    if window_mode:
        window_n = len(dates)
        use_n_min = (
            n_min
            if n_min is not None
            else _default_raster_n_min(product, window_n)
        )
        if use_n_min > window_n:
            console.print(
                f"[red]--n-min ({use_n_min}) 大于窗口天数 ({window_n})[/red]"
            )
            raise typer.Exit(1)

    # --- 1. Load config ---
    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    # --- 2. Resolve region ---
    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    console.print(
        f"  → 范围: {info.extent[0]:.2f}°~{info.extent[1]:.2f}°E, "
        f"{info.extent[2]:.2f}°~{info.extent[3]:.2f}°N"
    )

    # --- 3. Merge params (level defaults + CLI overrides) ---
    params = info.params
    use_res = res if res is not None else params.res
    use_dpi = dpi if dpi is not None else cfg.dpi
    prod_info = get_product_info(product)
    use_cmap = cmap if cmap is not None else prod_info.cmap
    use_qa = qa if qa is not None else cfg.qa_threshold
    use_smooth = smooth if smooth is not None else params.smooth_sigma

    if basemap is not None:
        use_basemap: bool | None = basemap.lower() == "satellite"
    else:
        use_basemap = None
    _warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
    )

    # --- 4. Read extent (with buffer to avoid edge artifacts) ---
    buf = 1.0
    read_extent = (
        info.extent[0] - buf,
        info.extent[1] + buf,
        info.extent[2] - buf,
        info.extent[3] + buf,
    )

    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir(product)
    )
    reader = prod_info.reader_cls()
    colorbar_label = prod_info.colorbar_label

    # --- 5. Read + grid (branches on mode) ---
    swath_meta: dict[str, Any]
    window_meta: dict[str, Any] | None = None

    if not window_mode:
        # ---- Single-day path (unchanged) ----
        console.print(
            f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})"
        )
        console.print(f"  日期: {dates[0]}, QA > {use_qa}")
        swath = reader.read(
            use_data_dir, dates[0], read_extent, qa_threshold=use_qa
        )
        console.print(
            f"  → [green]{swath.n_pixels}[/green] 有效像元 "
            f"({swath.n_files} 文件, {swath.n_broken} 损坏)"
        )

        console.print(f"\n[bold]网格化:[/bold] {use_res}° 分辨率")
        LON, LAT, grid_raw = grid_data(
            swath.lon, swath.lat, swath.values, read_extent, use_res
        )
        grid_filled = fill_nan_gaps(LON, LAT, grid_raw)
        grid_masked = mask_to_region(LON, LAT, grid_filled, info.geometry)

        swath_meta = {
            "n_pixels": int(swath.n_pixels),
            "n_files": int(swath.n_files),
            "n_broken": int(swath.n_broken),
            "qa_threshold": use_qa,
            "resolution_deg": use_res,
        }
    else:
        # ---- Window-mean path ----
        console.print(
            f"\n[bold]时间窗口:[/bold] {dates[0]} ~ {dates[-1]} "
            f"({window_n} 天，每像元至少 {use_n_min} 天有效)"
        )
        console.print(
            f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})"
        )
        console.print(f"  QA > {use_qa}")

        win = compute_window_mean(
            reader=reader,
            data_dir=use_data_dir,
            dates=dates,
            extent=read_extent,
            res=use_res,
            qa_threshold=use_qa,
            label=product.upper(),
            console=console,
        )
        n_failed = len(win.dates_failed)
        console.print(
            f"  → 有效天数 [green]{len(win.dates_found)}[/green] / "
            f"{window_n} (失败 {n_failed})，累计 "
            f"[green]{win.n_pixels_total}[/green] 像元 "
            f"({win.n_files_total} 文件, {win.n_broken_total} 损坏)"
        )

        LON, LAT = win.LON, win.LAT
        grid_mean = win.grid.copy()
        # Apply n_min mask: pixels below threshold → NaN
        grid_mean[win.n_valid < use_n_min] = np.nan

        # Same post-processing as single-day path (fill small gaps from
        # neighbours, then region mask) so visual treatment stays consistent.
        grid_filled = fill_nan_gaps(LON, LAT, grid_mean)
        grid_masked = mask_to_region(LON, LAT, grid_filled, info.geometry)

        # Per-pixel coverage stats (where any day was valid)
        covered = win.n_valid[win.n_valid > 0]
        coverage_days = {
            "min": int(covered.min()) if len(covered) else 0,
            "max": int(covered.max()) if len(covered) else 0,
            "mean": (
                round(float(covered.mean()), 1) if len(covered) else 0.0
            ),
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
            "n_pixels_total": int(win.n_pixels_total),
            "n_files_total": int(win.n_files_total),
            "n_broken_total": int(win.n_broken_total),
            "qa_threshold": use_qa,
            "resolution_deg": use_res,
        }
        window_meta = {
            "start": dates[0],
            "end": dates[-1],
            "n_days_requested": window_n,
            "n_days_found": len(win.dates_found),
            "n_min": use_n_min,
            "n_min_default": n_min is None,
            "dates_failed": win.dates_failed,
            "coverage_days": coverage_days,
        }

    coverage = float(np.isfinite(grid_masked).mean()) * 100
    console.print(f"  → 网格 {grid_masked.shape}, 覆盖率 {coverage:.1f}%")
    if not np.isfinite(grid_masked).any():
        console.print(
            "[red]窗口均值全区无有效像元，可能原因：窗口内覆盖不足，"
            "或 --n-min 太严。可放宽 --n-min / 扩大窗口。[/red]"
        )
        raise typer.Exit(1)

    if use_smooth is not None:
        console.print(f"  → 高斯平滑 sigma={use_smooth}")
        grid_masked = smooth_grid(
            grid_masked, info.geometry, LON, LAT, sigma=use_smooth
        )

    # --- 6. Determine vmin/vmax (CLI > product default > auto) ---
    if vmin is not None and vmax is not None:
        use_vmin, use_vmax = vmin, vmax
    elif prod_info.vmin is not None and prod_info.vmax is not None:
        use_vmin = vmin if vmin is not None else prod_info.vmin
        use_vmax = vmax if vmax is not None else prod_info.vmax
    else:
        auto_min, auto_max = auto_vrange(grid_masked, prod_info)
        use_vmin = vmin if vmin is not None else auto_min
        use_vmax = vmax if vmax is not None else auto_max

    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    # --- 7. Plot ---
    if output is None:
        if window_mode:
            output = (
                f"/tmp/rsplot_{info.name}_{dates[0]}_{dates[-1]}.png"
            )
        else:
            output = f"/tmp/rsplot_{info.name}_{dates[0]}.png"

    if title is None and window_mode:
        title = (
            f"TROPOMI {product.upper()} - {info.name} "
            f"({dates[0]}~{dates[-1]}, {window_n}d mean)"
        )

    console.print("\n[bold]绘图中...[/bold]")
    plot_raster(
        LON,
        LAT,
        grid_masked,
        info,
        dpi=use_dpi,
        cmap=use_cmap,
        vmin=use_vmin,
        vmax=use_vmax,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=title,
        output=output,
        colorbar_label=colorbar_label,
    )

    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    # --- 8. Emit structured result for downstream agents ---
    result = build_raster_result(
        region=info,
        product=product,
        date=dates[0] if not window_mode else dates[-1],
        prod_info=prod_info,
        LON=LON,
        LAT=LAT,
        grid=grid_masked,
        swath_meta=swath_meta,
        vmin=use_vmin,
        vmax=use_vmax,
        output=output,
        window=window_meta,
    )
    emit_result(result, output)


@app.command()
def station(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ..., help="YYYYMMDDHH (精确小时) 或 YYYYMMDD (自动取最新小时)"
    ),
    # --- optional overrides ---
    var: str = typer.Option(
        "AQI",
        "--var",
        "-v",
        help="变量名: AQI, PM2.5, PM10, NO2, O3, SO2, CO, O3_8h, *_24h",
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none",
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制国控站点散点图。

    示例:
        rsplot station 安徽 20260414        (自动取当天最新小时)
        rsplot station 安徽 2026041415      (精确到15时)
        rsplot station 中国 20260414 --var PM2.5_24h
        rsplot station YRD 2026041415 --var NO2 -o logs/yrd_no2.png
    """
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.geo.boundaries import resolve_region
    from rsplot.plotting.station import plot_station
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers.guokong import mask_stations_to_region, read_stations

    # --- 1. Load config ---
    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    # --- 2. Validate variable ---
    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)

    # --- 3. Resolve region ---
    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")

    # --- 4. Read station data ---
    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir("guokong")
    )
    console.print(f"\n[bold]读取站点数据:[/bold] {use_data_dir}")
    console.print(f"  时间: {datetime_str}, 变量: {var}")

    # Read with buffer for edge stations
    buf = 0.5
    read_extent = (
        info.extent[0] - buf,
        info.extent[1] + buf,
        info.extent[2] - buf,
        info.extent[3] + buf,
    )
    data, resolved_dt = read_stations(
        use_data_dir, datetime_str, var, extent=read_extent
    )
    data = mask_stations_to_region(data, info.geometry)
    if resolved_dt != datetime_str:
        console.print(f"  → 自动选择最新时次: [cyan]{resolved_dt}[/cyan]")
    console.print(
        f"  → [green]{data.n_valid}[/green] 有效站点 "
        f"(共 {data.n_stations} 站)"
    )

    # --- 5. Exceedance threshold ---
    threshold = get_exceedance_threshold(var)
    if threshold is not None:
        n_exceed = int(np.sum(data.values[np.isfinite(data.values)] > threshold))
        console.print(
            f"  → 超标阈值: {threshold}, "
            f"超标站点: [red]{n_exceed}[/red]"
        )

    # --- 6. Plot ---
    use_dpi = dpi if dpi is not None else cfg.dpi

    if basemap is not None:
        use_basemap: bool | None = basemap.lower() == "satellite"
    else:
        use_basemap = None
    _warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
    )

    unit = STATION_VAR_META[var][0]
    colorbar_label = f"{var} ({unit})" if unit else var

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
        title=title,
        output=output,
        colorbar_label=colorbar_label,
    )

    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    # --- 7. Emit structured result for downstream agents ---
    from rsplot.geo.boundaries import _load_city
    from rsplot.results import build_station_result, emit_result

    result = build_station_result(
        region=info,
        data=data,
        datetime_str=resolved_dt,
        threshold=threshold,
        unit=unit,
        cities_gdf=_load_city(cfg.geojson_dir),
        output=output,
    )
    emit_result(result, output)


# ---------------------------------------------------------------------------
# Station variable defaults that pair naturally with each satellite product.
# Used when the user asks for an overlay but doesn't specify --var explicitly.
# ---------------------------------------------------------------------------
_PRODUCT_STATION_PAIR: dict[str, str] = {
    "no2": "NO2",
    "o3": "O3",
}


@app.command()
def overlay(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ...,
        help="YYYYMMDDHH (精确小时) 或 YYYYMMDD (自动取最新小时)；"
        "日期部分用于卫星，小时部分用于站点",
    ),
    # --- satellite product ---
    product: str = typer.Option(
        "o3",
        "--product",
        "-p",
        help="卫星产品类型: no2 / o3",
    ),
    # --- station variable ---
    var: str | None = typer.Option(
        None,
        "--var",
        "-v",
        help="站点变量名，省略时按 product 自动选同名变量 (NO2 / O3)",
    ),
    # --- overrides ---
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    raster_dir: str | None = typer.Option(
        None,
        "--raster-dir",
        help="卫星数据目录 (覆盖配置默认值)",
    ),
    station_dir: str | None = typer.Option(
        None,
        "--station-dir",
        help="国控站点数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径，不指定则弹窗显示。",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(None, "--vmin", help="卫星 colorbar 最小值"),
    vmax: float | None = typer.Option(None, "--vmax", help="卫星 colorbar 最大值"),
    cmap: str | None = typer.Option(None, "--cmap", help="卫星 colormap 名称"),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    qa: float | None = typer.Option(0.5, "--qa", help="QA 阈值 (0-1)"),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """叠加绘制卫星栅格+国控站点图。

    两种数据同时输出到一张 PNG 和一个合并的 JSON sidecar。
    日期部分 (YYYYMMDD) 用于卫星，整串 (YYYYMMDDHH) 用于站点；
    YYYYMMDD 会自动选当天最新小时的站点数据。

    示例:
        rsplot overlay YRD    20260208   -p no2
        rsplot overlay 安徽   2026041415 -p o3  -v O3_8h
        rsplot overlay 中国   20260208   -p no2 -o logs/overlay/china_no2.png
    """
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.geo.boundaries import _load_city, resolve_region
    from rsplot.geo.gridding import (
        fill_nan_gaps,
        grid_data,
        mask_to_region,
        smooth_grid,
    )
    from rsplot.plotting.overlay import plot_overlay
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange, get_product_info
    from rsplot.readers.guokong import mask_stations_to_region, read_stations
    from rsplot.results import build_overlay_result, emit_result

    # --- 1. Load config ---
    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    # --- 2. Resolve station variable default from product ---
    if var is None:
        var = _PRODUCT_STATION_PAIR.get(product.lower(), "AQI")
    if var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(f"[red]未知站点变量 '{var}'[/red]。可用: {available}")
        raise typer.Exit(1)

    # --- 3. Split datetime: first 8 chars = date for satellite ---
    if not datetime_str.isdigit() or len(datetime_str) not in (8, 10):
        console.print(
            f"[red]datetime 参数 '{datetime_str}' 格式不正确[/red]，"
            f"请使用 YYYYMMDD 或 YYYYMMDDHH。"
        )
        raise typer.Exit(1)
    date = datetime_str[:8]

    # --- 4. Resolve region ---
    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    console.print(
        f"  → 范围: {info.extent[0]:.2f}°~{info.extent[1]:.2f}°E, "
        f"{info.extent[2]:.2f}°~{info.extent[3]:.2f}°N"
    )

    # --- 5. Merge params ---
    params = info.params
    use_res = res if res is not None else params.res
    use_dpi = dpi if dpi is not None else cfg.dpi
    prod_info = get_product_info(product)
    use_cmap = cmap if cmap is not None else prod_info.cmap
    use_qa = qa if qa is not None else cfg.qa_threshold
    use_smooth = smooth if smooth is not None else params.smooth_sigma

    if basemap is not None:
        use_basemap: bool | None = basemap.lower() == "satellite"
    else:
        use_basemap = None
    _warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
    )

    # --- 6. Read satellite swath ---
    use_raster_dir = (
        raster_dir if raster_dir is not None else cfg.get_data_dir(product)
    )
    reader = prod_info.reader_cls()
    raster_label = prod_info.colorbar_label
    buf = 1.0
    read_extent = (
        info.extent[0] - buf,
        info.extent[1] + buf,
        info.extent[2] - buf,
        info.extent[3] + buf,
    )
    console.print(f"\n[bold]读取卫星数据:[/bold] {use_raster_dir} (产品: {product})")
    console.print(f"  日期: {date}, QA > {use_qa}")
    swath = reader.read(use_raster_dir, date, read_extent, qa_threshold=use_qa)
    console.print(
        f"  → [green]{swath.n_pixels}[/green] 有效像元 "
        f"({swath.n_files} 文件, {swath.n_broken} 损坏)"
    )

    # --- 7. Grid + mask + smooth ---
    console.print(f"\n[bold]网格化:[/bold] {use_res}° 分辨率")
    LON, LAT, grid_raw = grid_data(
        swath.lon, swath.lat, swath.values, read_extent, use_res
    )
    grid_filled = fill_nan_gaps(LON, LAT, grid_raw)
    grid_masked = mask_to_region(LON, LAT, grid_filled, info.geometry)
    coverage = float(np.isfinite(grid_masked).mean()) * 100
    console.print(f"  → 网格 {grid_masked.shape}, 覆盖率 {coverage:.1f}%")

    if use_smooth is not None:
        grid_masked = smooth_grid(
            grid_masked, info.geometry, LON, LAT, sigma=use_smooth
        )

    # --- 8. Raster vmin/vmax ---
    if vmin is not None and vmax is not None:
        use_vmin, use_vmax = vmin, vmax
    elif prod_info.vmin is not None and prod_info.vmax is not None:
        use_vmin = vmin if vmin is not None else prod_info.vmin
        use_vmax = vmax if vmax is not None else prod_info.vmax
    else:
        auto_min, auto_max = auto_vrange(grid_masked, prod_info)
        use_vmin = vmin if vmin is not None else auto_min
        use_vmax = vmax if vmax is not None else auto_max
    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    # --- 9. Read station data ---
    use_station_dir = (
        station_dir if station_dir is not None else cfg.get_data_dir("guokong")
    )
    console.print(f"\n[bold]读取站点数据:[/bold] {use_station_dir}")
    console.print(f"  时间: {datetime_str}, 变量: {var}")
    station_buf = 0.5
    station_extent = (
        info.extent[0] - station_buf,
        info.extent[1] + station_buf,
        info.extent[2] - station_buf,
        info.extent[3] + station_buf,
    )
    data, resolved_dt = read_stations(
        use_station_dir, datetime_str, var, extent=station_extent
    )
    data = mask_stations_to_region(data, info.geometry)
    if resolved_dt != datetime_str:
        console.print(f"  → 自动选择最新时次: [cyan]{resolved_dt}[/cyan]")
    console.print(
        f"  → [green]{data.n_valid}[/green] 有效站点 "
        f"(共 {data.n_stations} 站)"
    )

    # --- 10. Exceedance threshold ---
    threshold = get_exceedance_threshold(var)
    if threshold is not None:
        n_exceed = int(np.sum(data.values[np.isfinite(data.values)] > threshold))
        console.print(
            f"  → 超标阈值: {threshold}, 超标站点: [red]{n_exceed}[/red]"
        )

    # --- 11. Plot ---
    if output is None:
        output = (
            f"/tmp/rsplot_overlay_{info.name}_{product}_{resolved_dt}.png"
        )

    unit = STATION_VAR_META[var][0]
    station_label = f"{var} ({unit})" if unit else var

    console.print("\n[bold]绘图中...[/bold]")
    plot_overlay(
        LON,
        LAT,
        grid_masked,
        data,
        info,
        raster_cmap=use_cmap,
        raster_vmin=use_vmin,
        raster_vmax=use_vmax,
        raster_label=raster_label,
        station_threshold=threshold,
        station_label=station_label,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=title,
        output=output,
    )

    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    # --- 12. Emit combined result ---
    result = build_overlay_result(
        region=info,
        product=product,
        date=date,
        prod_info=prod_info,
        LON=LON,
        LAT=LAT,
        grid=grid_masked,
        swath_meta={
            "n_pixels": int(swath.n_pixels),
            "n_files": int(swath.n_files),
            "n_broken": int(swath.n_broken),
            "qa_threshold": use_qa,
            "resolution_deg": use_res,
        },
        raster_vmin=use_vmin,
        raster_vmax=use_vmax,
        data=data,
        datetime_str=resolved_dt,
        threshold=threshold,
        unit=unit,
        cities_gdf=_load_city(cfg.geojson_dir),
        output=output,
    )
    emit_result(result, output)


@app.command()
def fnr(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    date_arg: str = typer.Argument(
        ...,
        help="单日 (YYYYMMDD，默认向前 --days 天) 或范围 "
        "(YYYYMMDD-YYYYMMDD，闭区间)",
    ),
    # --- window ---
    days: int = typer.Option(
        7,
        "--days",
        help="时间窗口天数（仅当 date_arg 为单日时生效，默认 7）",
    ),
    n_min: int | None = typer.Option(
        None,
        "--n-min",
        help="每像元最少有效天数，默认 max(3, 窗口天数 // 2)",
    ),
    no2_min: float = typer.Option(
        0.5,
        "--no2-min",
        help="最小平均 NO2 柱浓度阈值 (x10^15 molec/cm2)；"
        "低于此值的像元 FNR 不可信，输出为 NaN",
    ),
    # --- overrides ---
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    raster_dir_no2: str | None = typer.Option(
        None,
        "--no2-dir",
        help="NO2 数据目录 (覆盖配置默认值)",
    ),
    raster_dir_hcho: str | None = typer.Option(
        None,
        "--hcho-dir",
        help="HCHO 数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none",
    ),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    qa: float | None = typer.Option(
        0.5,
        "--qa",
        help="QA 阈值 (0-1)，同时应用于 NO2 和 HCHO（OFFL L2 swath 推荐 ≥0.5）",
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制 FNR (HCHO / NO2) 区域控制 regime 图。

    时间窗口平均后再相除（避免日尺度 HCHO 覆盖率太低）。
    分级依据 Duncan 2010: FNR<1 VOC-limited, 1~2 过渡, >2 NOx-limited.

    示例:
        rsplot fnr 合肥   20260114                 (7日窗口)
        rsplot fnr 安徽   20260131 --days 30      (30日窗口)
        rsplot fnr 长三角 20260101-20260130       (显式范围)
    """
    from rsplot.fnr import compute_fnr, parse_date_window
    from rsplot.geo.boundaries import resolve_region
    from rsplot.plotting.fnr import plot_fnr
    from rsplot.plotting.styles import setup_fonts
    from rsplot.results import build_fnr_result, emit_result

    # --- 1. Load config ---
    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    # --- 2. Parse date window ---
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

    console.print(
        f"[bold]时间窗口:[/bold] {dates[0]} ~ {dates[-1]} "
        f"({window_n} 天，每像元至少 {use_n_min} 天有效)"
    )

    # --- 3. Resolve region ---
    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")

    # --- 4. Merge params ---
    params = info.params
    use_res = res if res is not None else params.res
    use_dpi = dpi if dpi is not None else cfg.dpi
    use_qa = qa if qa is not None else cfg.qa_threshold
    use_smooth = smooth if smooth is not None else params.smooth_sigma

    if basemap is not None:
        use_basemap: bool | None = basemap.lower() == "satellite"
    else:
        use_basemap = None
    _warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
    )

    # --- 5. Resolve data dirs ---
    use_no2_dir = (
        raster_dir_no2 if raster_dir_no2 is not None else cfg.get_data_dir("no2")
    )
    use_hcho_dir = (
        raster_dir_hcho
        if raster_dir_hcho is not None
        else cfg.get_data_dir("hcho")
    )
    console.print(f"\n[bold]读取数据:[/bold]")
    console.print(f"  NO2 : {use_no2_dir}")
    console.print(f"  HCHO: {use_hcho_dir}")

    # --- 6. Compute FNR ---
    fnr_out = compute_fnr(
        info,
        dates,
        res=use_res,
        qa_threshold=use_qa,
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
        f"  → NO2 有效天数 {n_found_no2}/{window_n} "
        f"(失败 {n_fail_no2})"
    )
    console.print(
        f"  → HCHO 有效天数 {n_found_hcho}/{window_n} "
        f"(失败 {n_fail_hcho})"
    )
    if use_n_min > min(n_found_no2, n_found_hcho):
        console.print(
            f"  → [yellow]注意:[/yellow] n_min={use_n_min} 大于 NO2/HCHO "
            f"共同可用天数上限 {min(n_found_no2, n_found_hcho)}，"
            "本次不可能产生有效 FNR 像元。"
        )

    finite = fnr_out.fnr[np.isfinite(fnr_out.fnr)]
    if len(finite) == 0:
        _print_failed_dates("NO2", fnr_out.dates_failed_no2)
        _print_failed_dates("HCHO", fnr_out.dates_failed_hcho)
        console.print(
            "[red]FNR 全区无有效像元，可能原因：窗口内 NO2/HCHO 都覆盖不足，"
            "或 --n-min 太严。可放宽 --n-min / 扩大窗口。[/red]"
        )
        raise typer.Exit(1)

    coverage_pct = 100 * len(finite) / fnr_out.fnr.size
    console.print(
        f"  → FNR 覆盖率 {coverage_pct:.1f}%, "
        f"中位数 {float(np.median(finite)):.2f}"
    )

    from rsplot.fnr import regime_percentages
    pct = regime_percentages(fnr_out.fnr)
    console.print(
        f"  → Regime: [red]VOC-limited {pct['voc_limited']}%[/red] | "
        f"[yellow]transition {pct['transition']}%[/yellow] | "
        f"[blue]NOx-limited {pct['nox_limited']}%[/blue]"
    )

    # --- 7. Plot ---
    if output is None:
        output = (
            f"/tmp/rsplot_fnr_{info.name}_{dates[0]}_{dates[-1]}.png"
        )

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
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    # --- 8. JSON sidecar ---
    result = build_fnr_result(
        region=info,
        fnr_out=fnr_out,
        res=use_res,
        output=output,
    )
    emit_result(result, output)


def _print_failed_dates(
    label: str, failed: dict[str, str], max_items: int = 8
) -> None:
    """Print a compact failed-date summary for window commands."""
    if not failed:
        return
    console.print(f"  → [yellow]{label} 失败日期示例:[/yellow]")
    items = list(failed.items())
    for d, msg in items[:max_items]:
        console.print(f"    - {d}: {msg}")
    if len(items) > max_items:
        console.print(f"    ... 另有 {len(items) - max_items} 天")
