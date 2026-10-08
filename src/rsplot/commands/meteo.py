"""Implementation service for the ``meteo`` command."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import (
    load_fallback_city_boundaries,
    parse_basemap,
    validate_color_range,
    validate_positive,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig
from rsplot.errors import RsplotError
from rsplot.result_builders.provenance import input_fingerprint

if TYPE_CHECKING:
    from rich.console import Console


def run_meteo(**kwargs: Any) -> None:
    """Map ERA5 temperature, wind and an optional station hour."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        kwargs=kwargs,
        emit=lambda created: _emit_meteo(created, **kwargs),
    )


def _emit_meteo(
    created: list[Path],
    *,
    region: str,
    datetime_str: str,
    temp_level: str | None,
    wind_level: str | None,
    station_var: str | None,
    output: str,
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
    """Read ERA5 (and stations) for one China-time hour and write results."""
    from rsplot.config import (
        STATION_VAR_LABELS,
        STATION_VAR_META,
        get_exceedance_threshold,
    )
    from rsplot.data_files import data_path, write_grid_netcdf, write_table_csv
    from rsplot.geo.boundaries import resolve_regions
    from rsplot.geo.processing import buffered_extent
    from rsplot.plotting.meteo import plot_meteo
    from rsplot.plotting.styles import setup_fonts
    from rsplot.plotting.wind import wind_stride_for_shape
    from rsplot.readers.era5 import (
        mask_era5_field_to_region,
        normalize_temperature_level,
        read_era5_temperature,
    )
    from rsplot.readers.era5_wind import (
        mask_wind_to_region,
        normalize_wind_level,
        read_era5_wind,
    )
    from rsplot.readers.guokong import (
        mask_stations_to_region,
        read_stations,
    )
    from rsplot.result_builders.envelope import (
        command_line,
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
    from rsplot.temporal import adapt_hourly_time

    # Station observations and ERA5 share one explicit China-time hour; a
    # date-only input would have to pick a "latest" hour, which is forbidden.
    try:
        adapt_hourly_time(datetime_str, label="meteo 时次")
    except ValueError as error:
        raise RsplotError(
            "invalid_time",
            f"meteo 时次必须是 YYYYMMDDHH，不会自动选择最新小时。 ({error})",
        ) from error
    if station_var is not None and wind_level is None:
        raise RsplotError(
            "invalid_argument",
            "--station-var 必须与 --wind-level 一起使用。",
            option="--station-var",
        )
    if temp_level is None and wind_level is None:
        raise RsplotError(
            "invalid_argument",
            "请至少指定 --temp-level 或 --wind-level 中的一个。",
        )
    if station_var is not None and station_var not in STATION_VAR_META:
        raise RsplotError(
            "invalid_argument",
            f"未知站点变量 '{station_var}'。可用: "
            + ", ".join(STATION_VAR_META),
            option="--station-var",
        )
    if temp_level is None:
        for option, value in (
            ("--cmap", cmap),
            ("--vmin", vmin),
            ("--vmax", vmax),
        ):
            if value is not None:
                raise RsplotError(
                    "invalid_argument",
                    "--cmap/--vmin/--vmax 只用于温度底图；"
                    "当前命令没有指定 --temp-level。",
                    option=option,
                )
    for option, check, value in (
        ("--temp-level", normalize_temperature_level, temp_level),
        ("--wind-level", normalize_wind_level, wind_level),
    ):
        if value is not None:
            try:
                check(value)
            except ValueError as error:
                raise RsplotError(
                    "invalid_argument", str(error), option=option
                ) from error
    error_text, error_option = _wind_option_error(
        stride=wind_stride, scale=wind_scale, width=wind_width
    )
    if error_text is not None:
        raise RsplotError("invalid_argument", error_text, option=error_option)

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)
    console.print(f"[bold]解析区域:[/bold] {region}")
    try:
        info = resolve_regions(region, cfg)
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError(
            "region_not_found", str(error), details={"region": region}
        ) from error
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    read_extent = buffered_extent(info.extent, 0.5)
    use_dpi = dpi if dpi is not None else cfg.dpi
    try:
        use_basemap = parse_basemap(basemap)
        validate_positive(use_dpi, "--dpi")
        validate_color_range(vmin, vmax)
    except ValueError as error:
        raise RsplotError("invalid_argument", str(error)) from error
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=info.params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    read = station = None
    station_threshold = None
    station_unit = ""
    station_colorbar_label = ""
    use_station_dir = None
    if station_var is not None:
        use_station_dir = cfg.get_data_dir("guokong")
        console.print(f"\n[bold]读取站点数据:[/bold] {use_station_dir}")
        console.print(f"  时间: {datetime_str}, 变量: {station_var}")
        read, _ = read_stations(
            use_station_dir, datetime_str, station_var, extent=read_extent
        )
        station = mask_stations_to_region(read, info.geometry)
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

    use_data_dir = str(cfg.get_data_dir("era5"))
    console.print(f"\n[bold]读取 ERA5:[/bold] {use_data_dir}")
    console.print(f"  输入时次: {datetime_str}")
    field = wind = None
    try:
        if temp_level is not None:
            field = mask_era5_field_to_region(
                read_era5_temperature(
                    use_data_dir, datetime_str, temp_level, read_extent
                ),
                info.geometry,
            )
        if wind_level is not None:
            wind = mask_wind_to_region(
                read_era5_wind(
                    use_data_dir, datetime_str, wind_level, read_extent
                ),
                info.geometry,
            )
    except (FileNotFoundError, RsplotError):
        raise
    except ValueError as error:
        raise RsplotError("read_failed", str(error)) from error
    if field is not None and field.n_valid == 0:
        raise RsplotError(
            "no_valid_data", "目标区域内没有有效 ERA5 温度网格。"
        )
    if wind is not None and wind.n_valid == 0:
        raise RsplotError("no_valid_data", "目标区域内没有有效 ERA5 风矢量。")

    use_wind_stride = None
    if wind is not None:
        use_wind_stride = (
            wind_stride
            if wind_stride is not None
            else wind_stride_for_shape(wind.speed.shape, info.level)
        )
    use_cmap = cmap or "RdYlBu_r"
    use_vmin = use_vmax = None
    if field is not None:
        use_vmin, use_vmax = _temperature_range(
            field.values, vmin=vmin, vmax=vmax
        )
    use_title = title or _default_title(
        region=info.name,
        datetime_str=datetime_str,
        temp_level=field.level if field is not None else None,
        station_var=station_var,
        wind_level=wind.level if wind is not None else None,
    )
    image = str(Path(output).resolve())
    sidecar = sidecar_path(image)

    from shapely import contains_xy

    time = {
        "aggregation": "hourly",
        "at": datetime_str,
        "basis": "era5_hour",
    }
    layers: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    data_entries: list[dict[str, Any]] = []
    render_layers: dict[str, Any] = {}
    if field is not None:
        counted = contains_xy(info.geometry.buffer(1e-9), field.lon, field.lat)
        path = data_path(image, "temperature", ".nc")
        created.append(path)
        entry = write_grid_netcdf(
            path,
            field.lon,
            field.lat,
            field.values,
            counted,
            extent=info.extent,
            layer="temperature",
            attrs={
                "quantity": f"temperature_{field.level}",
                "unit": "degC",
                "scale": 1.0,
                "time_aggregation": "hourly",
            },
        )
        data_entries.append(entry)
        layer, layer_flags = _era5_grid_layer(
            layer_id="temperature",
            kind="grid",
            quantity={
                "name": f"temperature_{field.level}",
                "unit": "degC",
                "scale": 1,
                "label": f"{_level_label(field.level)} temperature (°C)",
            },
            time=time,
            data_root=use_data_dir,
            files=[field.source_file],
            method={
                "level": field.level,
                "conversion": "kelvin_minus_273.15",
                "cell_selection": "center_inside_region",
                "cell_weighting": "equal",
            },
            values=field.values,
            lon=field.lon,
            lat=field.lat,
            counted=counted,
            region=info,
            data=entry["path"],
        )
        layers.append(layer)
        flags.extend(layer_flags)
        render_layers["temperature"] = {
            "cmap": use_cmap,
            "vmin": use_vmin,
            "vmax": use_vmax,
            "range_method": (
                "manual"
                if vmin is not None and vmax is not None
                else "region_p02_p98"
            ),
        }
    if wind is not None:
        counted = contains_xy(info.geometry.buffer(1e-9), wind.lon, wind.lat)
        path = data_path(image, "wind", ".nc")
        created.append(path)
        entry = write_grid_netcdf(
            path,
            wind.lon,
            wind.lat,
            wind.speed,
            counted,
            extent=info.extent,
            layer="wind",
            attrs={
                "quantity": f"wind_{wind.level}",
                "unit": "m/s",
                "scale": 1.0,
                "time_aggregation": "hourly",
            },
            extra={"u": wind.u, "v": wind.v},
            content="vector_grid",
        )
        data_entries.append(entry)
        layer, layer_flags = _era5_grid_layer(
            layer_id="wind",
            kind="vector_grid",
            quantity={
                "name": f"wind_{wind.level}",
                "unit": "m/s",
                "scale": 1,
                "label": f"{_level_label(wind.level)} wind speed (m/s)",
            },
            time=time,
            data_root=use_data_dir,
            files=list(wind.source_files),
            method={
                "level": wind.level,
                "speed": "hypot(u, v)",
                "cell_selection": "center_inside_region",
                "cell_weighting": "equal",
            },
            values=wind.speed,
            lon=wind.lon,
            lat=wind.lat,
            counted=counted,
            region=info,
            data=entry["path"],
            unit="vectors",
        )
        layer["vector_summary"] = _vector_summary(wind)
        layers.append(layer)
        flags.extend(layer_flags)
        step = max(1, use_wind_stride or 1)
        render_layers["wind"] = {
            "color": "black",
            "colorbar": False,
            "stride": step,
            "scale": wind_scale,
            "width": wind_width,
            "arrows_plotted": int(
                np.isfinite(wind.speed[::step, ::step]).sum()
            ),
            "magnitude_encoding": "arrow_length_with_reference_arrow",
        }

    relations: dict[str, Any] = {}
    if read is not None and station is not None:
        assert station_var is not None and use_station_dir is not None
        in_region = contains_xy(info.geometry.buffer(1e-9), read.lon, read.lat)
        limit_key, limit_time = STATION_VAR_META[station_var][1:]
        station_path = data_path(image, "station", ".csv")
        admin_gdf = (
            info.sub_boundary_gdf
            if info.sub_boundary_gdf is not None and len(info.sub_boundary_gdf)
            else load_fallback_city_boundaries(info, cfg.require_geojson_dir())
        )
        station_layer, station_flags, rows = build_station_layer(
            StationInputs(
                read=read,
                in_region=in_region,
                var=station_var,
                unit=station_unit,
                threshold=station_threshold,
                standard=(
                    f"AQ_LIMITS_2026 {limit_key} {limit_time}"
                    if station_threshold is not None
                    else None
                ),
                hour=datetime_str,
                data_root=str(use_station_dir),
            ),
            info,
            admin_gdf=admin_gdf,
            satellite_values=None,
            data=str(station_path),
        )
        created.append(station_path)
        data_entries.append(
            write_table_csv(
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
        )
        layers.append(station_layer)
        flags.extend(station_flags)
        relations["time_matching"] = {
            "layers": ["wind", "station"],
            "reference": "same_hour",
            "difference_minutes": 0,
            "manual_override": False,
        }
        render_layers["station"] = {
            **(
                build_station_display(station)
                or {"range_method": "data_p5_p95"}
            ),
            "colorbar_label": station_colorbar_label,
        }

    console.print("\n[bold]绘图中...[/bold]")
    created.append(Path(image))
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
        output=image,
    )

    effective_basemap = (
        use_basemap if use_basemap is not None else info.params.basemap
    )
    payload = success_envelope(
        command="meteo",
        request=command_line(),
        region=info,
        layers=layers,
        relations=relations,
        flags=flags,
        render={
            "image": image,
            "dpi": int(use_dpi),
            "basemap": "satellite" if effective_basemap else "none",
            "title": use_title,
            "layers": render_layers,
        },
        artifacts={"image": image, "sidecar": sidecar, "data": data_entries},
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {image}")


def _era5_grid_layer(
    *,
    layer_id: str,
    kind: str,
    quantity: dict[str, Any],
    time: dict[str, Any],
    data_root: str,
    files: list[str],
    method: dict[str, Any],
    values: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    counted: np.ndarray,
    region: Any,
    data: str,
    unit: str = "cells",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """An ERA5 field as a grid layer with its coverage flags."""
    from rsplot.result_builders.common import (
        grid_per_admin_stats,
        top_hotspots,
    )
    from rsplot.result_builders.envelope import (
        capped,
        coverage_block,
        coverage_flags,
        stats_block,
        subdivision_level,
    )

    valid = np.isfinite(values) & counted
    coverage = coverage_block(int(valid.sum()), int(counted.sum()), unit)
    sub_gdf = region.sub_boundary_gdf
    has_subdivisions = sub_gdf is not None and len(sub_gdf) > 0
    by_admin = []
    if has_subdivisions:
        level_name = subdivision_level(region)
        by_admin = [
            {
                "name": row["name"],
                "level": level_name,
                "n": int(row["n_pixels"]),
                "mean": row["mean"],
                "min": row["min"],
                "max": row["max"],
            }
            for row in grid_per_admin_stats(lon, lat, values, sub_gdf)
        ]
    hotspots = top_hotspots(
        lon, lat, values, sub_gdf if has_subdivisions else None, n=10
    )
    layer = {
        "id": layer_id,
        "kind": kind,
        "quantity": quantity,
        "time": time,
        "source": {
            "sensor": "era5",
            "processing": None,
            "data_root": data_root,
            "files_total": len(files),
            "failed_files": {},
            **input_fingerprint(data_root, files),
        },
        "method": method,
        "coverage": coverage,
        "stats": stats_block(values[counted]),
        "by_admin": by_admin,
        "extremes": capped(
            [
                {
                    "lon": item["lon"],
                    "lat": item["lat"],
                    "value": item["value"],
                    "admin": item["city"],
                }
                for item in hotspots
            ],
            coverage["valid"],
            "value_desc",
        ),
        "data": data,
    }
    if region.members:
        layer["by_member"] = _member_rows(values, lon, lat, region)
    return layer, coverage_flags(layer_id, coverage)


def _member_rows(
    values: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    region: Any,
) -> list[dict[str, Any]]:
    """Select each member's cells with the layer's own counted rule."""
    from shapely import contains_xy

    from rsplot.result_builders.common import member_basic_stats

    rows = []
    for member in region.members:
        selected = contains_xy(member.geometry.buffer(1e-9), lon, lat)
        stats = member_basic_stats(values[selected])
        rows.append(
            {
                "name": member.qualified_name or member.name,
                "level": member.administrative_level or member.level,
                "n": int(stats["n"]),
                "mean": stats["mean"],
                "min": stats["min"],
                "max": stats["max"],
            }
        )
    return rows


def _vector_summary(wind: Any) -> dict[str, Any]:
    from rsplot.result_builders.envelope import stats_block
    from rsplot.stats import round_finite

    mean_u = float(np.nanmean(wind.u))
    mean_v = float(np.nanmean(wind.v))
    direction_to = (np.degrees(np.arctan2(mean_u, mean_v)) + 360.0) % 360.0
    index = np.unravel_index(int(np.nanargmax(wind.speed)), wind.speed.shape)
    return {
        "mean_u": round_finite(mean_u),
        "mean_v": round_finite(mean_v),
        "direction_to_deg": round_finite(direction_to, 1),
        "wind_from_deg": round_finite((direction_to + 180.0) % 360.0, 1),
        "u_stats": stats_block(wind.u),
        "v_stats": stats_block(wind.v),
        "max_speed_location": {
            "lon": round(float(wind.lon[index]), 3),
            "lat": round(float(wind.lat[index]), 3),
            "speed": round_finite(wind.speed[index]),
        },
    }


def _temperature_range(
    values: np.ndarray,
    *,
    vmin: float | None,
    vmax: float | None,
) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        raise RsplotError(
            "no_valid_data", "目标区域内没有可用于温度色阶的有效值。"
        )
    use_vmin = float(np.percentile(finite, 2)) if vmin is None else vmin
    use_vmax = float(np.percentile(finite, 98)) if vmax is None else vmax
    if use_vmax <= use_vmin:
        if vmin is None and vmax is None:
            midpoint = float(np.mean(finite))
            return midpoint - 0.5, midpoint + 0.5
        raise RsplotError(
            "invalid_argument",
            "--vmax 必须大于 --vmin 或自动计算的色阶下限。",
            option="--vmax",
        )
    return use_vmin, use_vmax


def _wind_option_error(
    *,
    stride: int | None,
    scale: float | None,
    width: float,
) -> tuple[str | None, str | None]:
    if stride is not None and (not math.isfinite(stride) or stride < 1):
        return "--wind-stride 必须大于等于 1。", "--wind-stride"
    if scale is not None and (not math.isfinite(scale) or scale <= 0):
        return "--wind-scale 必须大于 0。", "--wind-scale"
    if not math.isfinite(width) or width <= 0:
        return "--wind-width 必须大于 0。", "--wind-width"
    return None, None


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


def _level_label(level: str) -> str:
    return level if level.endswith("m") else f"{level} hPa"
