"""Implementation service for the ``recent`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from rsplot.commands.common import (
    resolve_satellite,
    satellite_errors,
    satellite_filter_label,
    validate_positive,
    validate_unit_interval,
)
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


@satellite_errors
def run_recent(
    *,
    region: str,
    end_date: str,
    days: int,
    source: str,
    product: str,
    sensor: str = "tropomi",
    processing: str | None = None,
    var: str,
    level: str | None,
    data_dir: str | None,
    output: str | None,
    res: float | None,
    qa: float | None,
    cf: float = 0.5,
    console: Console,
) -> None:
    """Execute recent-day summaries without owning the Typer signature."""
    from rsplot.config import STATION_VAR_META
    from rsplot.geo.boundaries import resolve_region
    from rsplot.recent import (
        build_recent_result,
        parse_recent_dates,
        summarize_recent_raster,
        summarize_recent_station,
        write_recent_result,
    )

    use_source = source.lower()
    if use_source not in ("raster", "station"):
        console.print("[red]--source 仅支持 raster / station[/red]")
        raise typer.Exit(1)

    try:
        dates = parse_recent_dates(end_date, days)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    cfg = AppConfig.load()
    if use_source == "raster":
        prod_info, use_qa = resolve_satellite(
            product, sensor, qa, cfg, console, processing
        )
        sensor = prod_info.sensor
        processing = prod_info.processing
    elif processing is not None:
        raise ValueError("--processing 仅用于 --source raster。")
    elif sensor.lower() != "tropomi":
        raise ValueError("--sensor gems 仅用于 --source raster。")
    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    console.print(
        f"[bold]统计窗口:[/bold] {dates[0]} ~ {dates[-1]} ({len(dates)} 天)"
    )

    if output is None:
        if use_source == "raster":
            prefix = (
                "nrti_" if processing else "gems_" if sensor == "gems" else ""
            )
            output = (
                f"/tmp/rsplot_recent_{prefix}"
                f"{info.name}_{product}_"
                f"{dates[0]}_{dates[-1]}.json"
            )
        else:
            output = (
                f"/tmp/rsplot_recent_{info.name}_{var}_"
                f"{dates[0]}_{dates[-1]}.json"
            )

    if use_source == "raster":
        product_defaults = prod_info.defaults_for_level(info.level)
        use_res = (
            res
            if res is not None
            else product_defaults.res
            if product_defaults.res is not None
            else info.params.res
        )
        try:
            validate_positive(use_res, "--res")
            validate_unit_interval(use_qa, "--qa")
            validate_unit_interval(cf, "--cf")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        use_data_dir = (
            data_dir
            if data_dir is not None
            else cfg.get_data_dir(prod_info.data_key or product)
        )
        console.print(
            f"\n[bold]统计栅格:[/bold] {use_data_dir} "
            f"(产品: {product}, {satellite_filter_label(sensor, use_qa, cf)}, "
            f"res={use_res})"
        )
        daily = summarize_recent_raster(
            region=info,
            product=product,
            prod_info=prod_info,
            data_dir=use_data_dir,
            dates=dates,
            res=use_res,
            qa_threshold=use_qa,
            cloud_fraction_max=cf,
            console=console,
        )
        result = build_recent_result(
            region=info,
            source=use_source,
            dates=dates,
            daily=daily,
            params={
                "data_dir": use_data_dir,
                "qa_threshold": use_qa,
                "cloud_fraction_max": cf,
                "resolution_deg": use_res,
            },
            product=product,
            sensor=sensor,
            processing=processing,
            quantity=prod_info.quantity,
            unit=prod_info.colorbar_label,
            output=output,
        )
    else:
        if var not in STATION_VAR_META:
            available = ", ".join(STATION_VAR_META)
            console.print(f"[red]未知变量 '{var}'[/red]。可用: {available}")
            raise typer.Exit(1)
        use_data_dir = (
            data_dir if data_dir is not None else cfg.get_data_dir("guokong")
        )
        unit = STATION_VAR_META[var][0]
        console.print(f"\n[bold]统计站点:[/bold] {use_data_dir} (变量: {var})")
        daily = summarize_recent_station(
            region=info,
            data_dir=use_data_dir,
            dates=dates,
            var_name=var,
            console=console,
        )
        result = build_recent_result(
            region=info,
            source=use_source,
            dates=dates,
            daily=daily,
            params={"data_dir": use_data_dir},
            variable=var,
            unit=unit or None,
            output=output,
        )

    write_recent_result(result, output)
    found = result["availability"]["days_found"]
    failed = result["availability"]["days_failed"]
    console.print(
        f"\n[bold green]✓ 已保存:[/bold green] {output} "
        f"(有效 {found}/{len(dates)} 天，失败 {failed})"
    )
