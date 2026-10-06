"""Implementation service for the ``station`` command."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import (
    load_fallback_city_boundaries,
    parse_basemap,
    validate_positive,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console

# Keyword argument -> CLI spellings, for recording where values came from.
STATION_OPTIONS = {
    "var": ("--var",),
    "level": ("--level",),
    "output": ("--output",),
    "dpi": ("--dpi",),
    "basemap": ("--basemap",),
    "title": ("--title",),
}


def run_station(**kwargs: Any) -> None:
    """Map one station hour for a region."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        command="station",
        kwargs=kwargs,
        options=STATION_OPTIONS,
        positionals={
            "region": kwargs["region"],
            "datetime": kwargs["datetime_str"],
        },
        emit=lambda created: _emit_station(created, **kwargs),
    )


def _emit_station(
    created: list[Path],
    *,
    region: str,
    datetime_str: str,
    var: str,
    level: str | None,
    output: str,
    dpi: int | None,
    basemap: str | None,
    title: str | None,
    console: Console,
) -> None:
    """Read one station hour, plot it, and write the sidecar."""
    # Validate before configuration, boundary lookup, or any source reads.
    # The shared reader still supports date-only selection for other commands.
    try:
        if (
            len(datetime_str) != 10
            or not datetime_str.isascii()
            or not datetime_str.isdigit()
        ):
            raise ValueError("Expected ten ASCII digits")
        datetime.strptime(datetime_str, "%Y%m%d%H")
    except ValueError as error:
        raise RsplotError(
            "invalid_time",
            "station 时间必须是有效的北京时间 YYYYMMDDHH"
            "（10 位数字，小时 00–23），如 2026041415；"
            "不支持仅日期 YYYYMMDD，也不会自动选择最新小时。",
        ) from error

    from rsplot.config import (
        STATION_VAR_LABELS,
        STATION_VAR_META,
        get_exceedance_threshold,
    )
    from rsplot.data_files import data_path, write_table_csv
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.processing import buffered_extent
    from rsplot.plotting.station import plot_station
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers.guokong import (
        mask_stations_to_region,
        read_stations,
        resolve_station_file,
    )
    from rsplot.result_builders.envelope import (
        option_given,
        request_block,
        resolved,
        sidecar_path,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.station import build_station_display
    from rsplot.result_builders.station_layer import (
        TABLE_COLUMNS,
        StationInputs,
        build_station_layer,
    )

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)

    if var not in STATION_VAR_META:
        raise RsplotError(
            "invalid_argument",
            f"未知变量 '{var}'。可用: {', '.join(STATION_VAR_META)}",
            option="--var",
        )

    console.print(f"[bold]解析区域:[/bold] {region}")
    try:
        info = resolve_region(region, cfg, level_override=level)
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError(
            "region_not_found", str(error), details={"region": region}
        ) from error
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    use_dpi = dpi if dpi is not None else cfg.dpi
    try:
        use_basemap = parse_basemap(basemap)
        validate_positive(use_dpi, "--dpi")
    except ValueError as error:
        raise RsplotError("invalid_argument", str(error)) from error
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=info.params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    use_data_dir = cfg.get_data_dir("guokong")
    console.print(f"\n[bold]读取站点数据:[/bold] {use_data_dir}")
    console.print(f"  时间: {datetime_str}, 变量: {var}")
    read, resolved_dt = read_stations(
        use_data_dir,
        datetime_str,
        var,
        extent=buffered_extent(info.extent, 0.5),
    )
    data = mask_stations_to_region(read, info.geometry)
    console.print(
        f"  → [green]{data.n_valid}[/green] 有效站点 (共 {data.n_stations} 站)"
    )

    threshold = get_exceedance_threshold(var)
    if threshold is not None:
        n_exceed = int(
            np.sum(data.values[np.isfinite(data.values)] > threshold)
        )
        console.print(
            f"  → 超标阈值: {threshold}, 超标站点: [red]{n_exceed}[/red]"
        )

    unit, limit_key, limit_time = STATION_VAR_META[var]
    display_var = STATION_VAR_LABELS.get(var, var)
    colorbar_label = f"{display_var} ({unit})" if unit else display_var
    use_title = title
    if use_title is None and display_var != var:
        use_title = f"{display_var} - {info.name}"
    if use_title is None:
        # The renderer's default, recorded so the sidecar states it.
        use_title = f"{var} - {info.name}"

    image = str(Path(output).resolve())
    sidecar = sidecar_path(image)

    from shapely import contains_xy

    in_region = contains_xy(info.geometry.buffer(1e-9), read.lon, read.lat)
    admin_gdf = (
        info.sub_boundary_gdf
        if info.sub_boundary_gdf is not None and len(info.sub_boundary_gdf)
        else load_fallback_city_boundaries(info, cfg.require_geojson_dir())
    )
    station_path = data_path(image, "station", ".csv")
    layer, flags, rows = build_station_layer(
        StationInputs(
            read=read,
            in_region=in_region,
            var=var,
            unit=unit,
            threshold=threshold,
            standard=(
                f"AQ_LIMITS_2026 {limit_key} {limit_time}"
                if threshold is not None
                else None
            ),
            hour=resolved_dt,
            data_root=str(use_data_dir),
            source_file=resolve_station_file(use_data_dir, resolved_dt).name,
        ),
        info,
        admin_gdf=admin_gdf,
        satellite_values=None,
        data=str(station_path),
    )
    created.append(station_path)
    station_entry = write_table_csv(
        station_path,
        rows,
        [
            column
            for column in TABLE_COLUMNS
            if column not in ("satellite_value", "colocated")
        ],
        content="station_table",
        layer="station",
    )

    console.print("\n[bold]绘图中...[/bold]")
    created.append(Path(image))
    plot_station(
        data,
        info,
        threshold=threshold,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=use_title,
        output=image,
        colorbar_label=colorbar_label,
    )

    def source(name: str, value: Any, default: str) -> dict[str, Any]:
        if option_given(*STATION_OPTIONS[name]):
            return resolved(value, "cli")
        return resolved(value, default)

    effective_basemap = (
        use_basemap if use_basemap is not None else info.params.basemap
    )
    payload = success_envelope(
        command="station",
        request=request_block(
            {
                "region": resolved(region, "cli"),
                "datetime": resolved(datetime_str, "cli"),
                "var": source("var", var, "built_in"),
                "level": source("level", info.level, "built_in"),
                "data_dir": resolved(str(use_data_dir), "config"),
                "output": source("output", output, "built_in"),
                "dpi": source("dpi", use_dpi, "built_in"),
                "basemap": source(
                    "basemap",
                    "satellite" if effective_basemap else "none",
                    "level_default",
                ),
                "title": source("title", use_title, "built_in"),
            }
        ),
        region=info,
        layers=[layer],
        flags=flags,
        render={
            "image": image,
            "dpi": int(use_dpi),
            "basemap": "satellite" if effective_basemap else "none",
            "title": use_title,
            "layers": {
                "station": {
                    **(
                        build_station_display(data)
                        or {"range_method": "data_p5_p95"}
                    ),
                    "colorbar_label": colorbar_label,
                }
            },
        },
        artifacts={
            "image": image,
            "sidecar": sidecar,
            "data": [station_entry],
        },
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {image}")
