"""CLI command definitions for rsplot."""

from __future__ import annotations

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


@app.callback()
def _callback() -> None:
    "CLI tool for Remote sensing raster plotting."


@app.command()
def raster(
    # FIXME: 如何应对区域重名如高新区
    region: str = typer.Argument(
        ..., help="区域名称，如 合肥、安徽、YRD、蜀山"
    ),
    date: str = typer.Argument(..., help="日期，格式 YYYYMMDD 如 20260208"),
    # --- optional overrides ---
    product: str = typer.Option(
        "o3",
        "--product",
        "-p",
        help="产品类型，如 no2, o3",
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: key_region / province / city / county",
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
        help="输出文件路径，不指定则保存到 /tmp。",
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
    qa: float | None = typer.Option(0.8, "--qa", help="QA 阈值 (0-1)"),
) -> None:
    """绘制卫星遥感栅格图。

    示例:
        rsplot raster --help
        rsplot raster YRD 20260208 --dpi 300 --output yrd.png
    """
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.gridding import grid_data, mask_to_region, smooth_grid
    from rsplot.plotting.raster import plot_raster
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange, get_product_info

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
        use_basemap = None  # let plot_raster use level default

    # --- 4. Expand extent for data reading (add buffer) ---
    buf = 1.0  # read 1° extra on each side to avoid edge artifacts
    read_extent = (
        info.extent[0] - buf,
        info.extent[1] + buf,
        info.extent[2] - buf,
        info.extent[3] + buf,
    )

    # --- 5. Read data ---
    use_data_dir = (
        data_dir if data_dir is not None else cfg.get_data_dir(product)
    )
    reader = prod_info.reader_cls()
    colorbar_label = prod_info.colorbar_label
    console.print(f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})")
    console.print(f"  日期: {date}, QA > {use_qa}")
    swath = reader.read(use_data_dir, date, read_extent, qa_threshold=use_qa)
    console.print(
        f"  → [green]{swath.n_pixels}[/green] 有效像元 "
        f"({swath.n_files} 文件, {swath.n_broken} 损坏)"
    )

    # --- 6. Grid + mask + smooth ---
    console.print(f"\n[bold]网格化:[/bold] {use_res}° 分辨率")
    LON, LAT, grid_raw = grid_data(
        swath.lon, swath.lat, swath.values, read_extent, use_res
    )
    grid_masked = mask_to_region(LON, LAT, grid_raw, info.geometry)

    coverage = float(np.isfinite(grid_masked).mean()) * 100
    console.print(f"  → 网格 {grid_masked.shape}, 覆盖率 {coverage:.1f}%")

    if use_smooth is not None:
        console.print(f"  → 高斯平滑 sigma={use_smooth}")
        grid_masked = smooth_grid(
            grid_masked, info.geometry, LON, LAT, sigma=use_smooth
        )

    # --- 7. Determine vmin/vmax (CLI > product default > auto) ---
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

    # --- 8. Plot ---
    if output is None:
        output = f"/tmp/rsplot_{info.name}_{date}.png"

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
