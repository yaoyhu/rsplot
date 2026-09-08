"""Implementation service for the ``reconstruct`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import (
    parse_basemap,
    validate_color_range,
    validate_non_negative,
    validate_positive,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


RECONSTRUCT_RESOLUTION_BY_LEVEL = {
    "country": 0.05,
    "key_region": 0.02,
    "province": 0.01,
    "city": 0.01,
    "county": 0.01,
}


def default_reconstruct_resolution(level: str) -> float:
    """Return a memory-aware display resolution for an admin level."""
    return RECONSTRUCT_RESOLUTION_BY_LEVEL.get(level, 0.01)


def run_reconstruct(
    *,
    region: str,
    datetime_str: str,
    var: str,
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
    console: Console,
) -> None:
    """Execute reconstructed-grid orchestration."""
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.processing import (
        buffered_extent,
        prepare_display_grid,
        prepare_existing_grid,
    )
    from rsplot.plotting.colormaps import STATION_CONCENTRATION_CMAP
    from rsplot.plotting.raster import plot_raster
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers.forecast import auto_forecast_vrange
    from rsplot.readers.reconstruct import (
        get_reconstruct_var_info,
        read_reconstruct,
    )
    from rsplot.results import build_reconstruct_result, emit_result

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
    use_res = (
        res if res is not None else default_reconstruct_resolution(info.level)
    )
    use_cmap = cmap if cmap is not None else STATION_CONCENTRATION_CMAP
    try:
        use_basemap = parse_basemap(basemap)
        validate_positive(use_dpi, "--dpi")
        validate_positive(use_res, "--res")
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
        var_info = get_reconstruct_var_info(var)
        use_data_dir = (
            data_dir
            if data_dir is not None
            else cfg.get_data_dir("reconstruct")
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    read_extent = buffered_extent(info.extent, max(0.05, use_res * 2))
    console.print(
        f"\n[bold]读取重构数据:[/bold] {use_data_dir} (变量: {var_info.label})"
    )
    console.print(f"  输入时次: {datetime_str} (中国时间)")
    try:
        data, resolved_dt = read_reconstruct(
            use_data_dir,
            datetime_str,
            var,
            read_extent,
            use_res,
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if resolved_dt != datetime_str:
        console.print(
            f"  → 自动选择最新完整时次: [cyan]{resolved_dt}[/cyan] (中国时间)"
        )
    console.print(
        f"  → UTC 归档时次: [cyan]{data.archive_datetime}[/cyan], "
        f"源文件: {data.source_file}"
    )
    console.print(
        f"  → 原生/输出分辨率: {data.native_resolution_deg:.2f}° / "
        f"{data.output_resolution_deg:.2f}°，有效输出网格: "
        f"[green]{data.n_output_valid}[/green] / {data.n_output_cells}"
    )

    prepared = prepare_existing_grid(
        data.lon,
        data.lat,
        data.values,
        info.geometry,
        fill_gaps=False,
    )
    display_source = prepared.unmasked_values
    display_grid = prepare_display_grid(
        prepared.lon,
        prepared.lat,
        display_source,
        info.geometry,
        smooth_sigma=smooth,
    )
    if not np.isfinite(display_grid).any():
        console.print("[red]目标区域内没有有效重构网格。[/red]")
        raise typer.Exit(1)
    if (
        smooth is not None
        and smooth > 0
        and np.isfinite(prepared.values).any()
    ):
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

    auto_min, auto_max = auto_forecast_vrange(
        prepared.values
        if np.isfinite(prepared.values).any()
        else display_grid,
        var_info,
    )
    use_vmin = vmin if vmin is not None else auto_min
    use_vmax = vmax if vmax is not None else auto_max
    try:
        validate_color_range(use_vmin, use_vmax)
    except ValueError as e:
        console.print(f"[red]色标范围无效：{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    if output is None:
        output = (
            f"/tmp/rsplot_reconstruct_{info.name}_{data.variable}_"
            f"{data.datetime}.png"
        )
    if title is None:
        title = (
            f"Reconstructed {data.label} - {info.name} "
            f"({data.datetime} CST / {data.archive_datetime} UTC)"
        )

    console.print("\n[bold]绘图中...[/bold]")
    plot_raster(
        prepared.lon,
        prepared.lat,
        display_grid,
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
        colorbar_label=f"{data.label} reconstructed ({data.unit})",
    )
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")

    result = build_reconstruct_result(
        region=info,
        data=data,
        LON=prepared.lon,
        LAT=prepared.lat,
        grid=prepared.values,
        display_grid=display_grid,
        vmin=use_vmin,
        vmax=use_vmax,
        output=output,
    )
    emit_result(result, output)
