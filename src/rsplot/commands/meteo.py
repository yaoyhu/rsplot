"""Implementation service for the ``meteo`` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import typer

from rsplot.commands.common import warn_missing_tianditu_key
from rsplot.config import AppConfig

if TYPE_CHECKING:
    from rich.console import Console


def run_meteo(
    *,
    region: str,
    datetime_str: str,
    temp_level: str | None,
    wind_level: str | None,
    station_var: str | None,
    level: str | None,
    data_dir: str | None,
    station_data_dir: str | None,
    input_timezone: str,
    output: str | None,
    dpi: int | None,
    basemap: str | None,
    cmap: str | None,
    vmin: float | None,
    vmax: float | None,
    wind_stride: int | None,
    wind_scale: float | None,
    wind_width: float,
    title: str | None,
    console: Console,
) -> None:
    """Execute meteorological plotting and optional station overlay."""
    from rsplot.config import (
        STATION_VAR_LABELS,
        STATION_VAR_META,
        get_exceedance_threshold,
    )
    from rsplot.geo.boundaries import load_city_boundaries, resolve_region
    from rsplot.geo.processing import buffered_extent
    from rsplot.plotting.meteo import plot_meteo
    from rsplot.plotting.styles import setup_fonts
    from rsplot.plotting.wind import wind_stride_for_shape
    from rsplot.readers.era5 import (
        mask_era5_field_to_region,
        read_era5_temperature,
    )
    from rsplot.readers.era5_wind import (
        mask_wind_to_region,
        read_era5_wind,
    )
    from rsplot.readers.guokong import mask_stations_to_region, read_stations
    from rsplot.results import build_meteo_result, emit_result

    if station_var is not None and wind_level is None:
        console.print(
            "[red]--station-var 必须与 --wind-level 一起使用。[/red]"
        )
        raise typer.Exit(1)
    if temp_level is None and wind_level is None:
        console.print(
            "[red]请至少指定 --temp-level 或 --wind-level 中的一个。[/red]"
        )
        raise typer.Exit(1)
    if station_var is not None and station_var not in STATION_VAR_META:
        available = ", ".join(STATION_VAR_META)
        console.print(
            f"[red]未知站点变量 '{station_var}'[/red]。可用: {available}"
        )
        raise typer.Exit(1)
    if temp_level is None and any(
        value is not None for value in (cmap, vmin, vmax)
    ):
        console.print(
            "[red]--cmap/--vmin/--vmax 只用于温度底图；"
            "当前命令没有指定 --temp-level。[/red]"
        )
        raise typer.Exit(1)
    error = _wind_option_error(
        stride=wind_stride,
        scale=wind_scale,
        width=wind_width,
    )
    if error is not None:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)
    console.print(f"[bold]解析区域:[/bold] {region}")
    info = resolve_region(region, cfg, level_override=level)
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    read_extent = buffered_extent(info.extent, 0.5)

    station = None
    station_threshold = None
    station_unit = ""
    station_colorbar_label = ""
    resolved_datetime = datetime_str
    if station_var is not None:
        use_station_dir = station_data_dir or cfg.get_data_dir("guokong")
        console.print(f"\n[bold]读取站点数据:[/bold] {use_station_dir}")
        console.print(f"  时间: {datetime_str}, 变量: {station_var}")
        try:
            station, resolved_datetime = read_stations(
                use_station_dir,
                datetime_str,
                station_var,
                extent=read_extent,
            )
            station = mask_stations_to_region(station, info.geometry)
        except (FileNotFoundError, ValueError) as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1) from error
        if resolved_datetime != datetime_str:
            console.print(
                f"  → 自动选择最新时次: [cyan]{resolved_datetime}[/cyan]"
            )
        console.print(
            f"  → [green]{station.n_valid}[/green] 有效站点 "
            f"(共 {station.n_stations} 站)"
        )
        station_threshold = get_exceedance_threshold(station_var)
        station_unit = STATION_VAR_META[station_var][0]
        display_var = STATION_VAR_LABELS.get(station_var, station_var)
        station_colorbar_label = (
            f"{display_var} ({station_unit})" if station_unit else display_var
        )
        if station_threshold is not None:
            finite = station.values[np.isfinite(station.values)]
            n_exceed = int(np.sum(finite > station_threshold))
            console.print(
                f"  → 超标阈值: {station_threshold}, "
                f"超标站点: [red]{n_exceed}[/red]"
            )

    use_data_dir = data_dir or cfg.get_data_dir("era5")
    console.print(f"\n[bold]读取 ERA5:[/bold] {use_data_dir}")
    console.print(f"  输入时次: {resolved_datetime} (时区: {input_timezone})")
    if temp_level is not None:
        console.print(f"  温度图层: {temp_level}")
    if wind_level is not None:
        console.print(f"  风场图层: {wind_level}")

    field = None
    wind = None
    try:
        if temp_level is not None:
            field = read_era5_temperature(
                use_data_dir,
                resolved_datetime,
                temp_level,
                read_extent,
                input_timezone=input_timezone,
            )
            field = mask_era5_field_to_region(field, info.geometry)
            if field.n_valid == 0:
                raise ValueError("目标区域内没有有效 ERA5 温度网格。")
        if wind_level is not None:
            wind = read_era5_wind(
                use_data_dir,
                resolved_datetime,
                wind_level,
                read_extent,
                station_timezone=input_timezone,
            )
            wind = mask_wind_to_region(wind, info.geometry)
        if wind is not None and wind.n_valid == 0:
            raise ValueError("目标区域内没有有效 ERA5 风矢量。")
    except (FileNotFoundError, ValueError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    use_wind_stride = None
    if wind is not None:
        use_wind_stride = (
            wind_stride
            if wind_stride is not None
            else wind_stride_for_shape(wind.speed.shape, info.level)
        )

    use_cmap = cmap or "RdYlBu_r"
    use_vmin = None
    use_vmax = None
    if field is not None:
        try:
            use_vmin, use_vmax = _temperature_range(
                field.values,
                vmin=vmin,
                vmax=vmax,
            )
        except ValueError as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1) from error

    datetime_utc = (
        field.datetime_utc if field is not None else wind.datetime_utc
    )
    console.print(f"  → ERA5 UTC 时次: [cyan]{datetime_utc}[/cyan]")
    if field is not None:
        console.print(
            f"  → 温度有效网格: [green]{field.n_valid}[/green], "
            f"色阶: {use_vmin:.2f} ~ {use_vmax:.2f} °C"
        )
    if wind is not None:
        console.print(
            f"  → 风场层次: {wind.level}, "
            f"有效网格: [green]{wind.n_valid}[/green], "
            f"抽稀步长: {use_wind_stride}"
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

    use_title = title or _default_title(
        region=info.name,
        datetime_str=resolved_datetime,
        temp_level=field.level if field is not None else None,
        station_var=station_var,
        wind_level=wind.level if wind is not None else None,
    )
    if output is None:
        layer_suffix = _output_layer_suffix(
            temp_level=field.level if field is not None else None,
            station_var=station_var,
            wind_level=wind.level if wind is not None else None,
        )
        output = (
            f"/tmp/rsplot_meteo_{info.name}_{layer_suffix}_"
            f"{resolved_datetime}.png"
        )
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold]绘图中...[/bold]")
    plot_meteo(
        info,
        field=field,
        wind=wind,
        station=station,
        station_threshold=station_threshold,
        station_colorbar_label=station_colorbar_label,
        field_cmap=use_cmap,
        field_vmin=use_vmin,
        field_vmax=use_vmax,
        wind_stride=use_wind_stride or 1,
        wind_scale=wind_scale,
        wind_width=wind_width,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=use_title,
        output=output,
    )
    result = build_meteo_result(
        region=info,
        variable="temperature" if field is not None else "wind",
        input_datetime=datetime_str,
        input_timezone=input_timezone,
        datetime_utc=datetime_utc,
        output=output,
        field=field,
        field_cmap=use_cmap if field is not None else None,
        field_vmin=use_vmin,
        field_vmax=use_vmax,
        wind=wind,
        wind_stride=use_wind_stride,
        station=station,
        station_datetime=resolved_datetime if station is not None else None,
        station_threshold=station_threshold,
        station_unit=station_unit,
        cities_gdf=(
            load_city_boundaries(cfg.require_geojson_dir())
            if station is not None
            else None
        ),
    )
    sidecar = emit_result(result, output)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {output}")
    console.print(f"[bold green]✓ JSON:[/bold green] {sidecar}")


def _temperature_range(
    values: np.ndarray,
    *,
    vmin: float | None,
    vmax: float | None,
) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        raise ValueError("目标区域内没有可用于温度色阶的有效值。")
    use_vmin = float(np.percentile(finite, 2)) if vmin is None else vmin
    use_vmax = float(np.percentile(finite, 98)) if vmax is None else vmax
    if use_vmax <= use_vmin:
        if vmin is None and vmax is None:
            midpoint = float(np.mean(finite))
            return midpoint - 0.5, midpoint + 0.5
        raise ValueError("--vmax 必须大于 --vmin 或自动计算的色阶下限。")
    return use_vmin, use_vmax


def _wind_option_error(
    *,
    stride: int | None,
    scale: float | None,
    width: float,
) -> str | None:
    if stride is not None and stride < 1:
        return "--wind-stride 必须大于等于 1。"
    if scale is not None and scale <= 0:
        return "--wind-scale 必须大于 0。"
    if width <= 0:
        return "--wind-width 必须大于 0。"
    return None


def _default_title(
    *,
    region: str,
    datetime_str: str,
    temp_level: str | None,
    station_var: str | None,
    wind_level: str | None,
) -> str:
    layers: list[str] = []
    if temp_level is not None:
        layers.append(f"{_level_label(temp_level)} 温度")
    if station_var is not None:
        layers.append(f"{station_var} 站点")
    if wind_level is not None:
        layers.append(f"{_level_label(wind_level)} 风场")
    return f"{' + '.join(layers)} - {region} - {datetime_str}"


def _output_layer_suffix(
    *,
    temp_level: str | None,
    station_var: str | None,
    wind_level: str | None,
) -> str:
    if temp_level is not None:
        suffix = f"temperature_{temp_level}"
    elif station_var is not None:
        suffix = f"station_{station_var}"
    else:
        suffix = f"wind_{wind_level}"
    if station_var is not None and temp_level is not None:
        suffix += f"_station_{station_var}"
    if wind_level is not None and (
        temp_level is not None or station_var is not None
    ):
        suffix += f"_wind{wind_level}"
    return suffix


def _level_label(level: str) -> str:
    return level if level.endswith("m") else f"{level} hPa"
