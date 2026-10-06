"""Implementation service for the ``trend`` command."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import validate_positive
from rsplot.config import AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console

    from rsplot.readers.guokong import RegionStationSeries

# Keyword argument -> CLI spellings, for recording where values came from.
TREND_OPTIONS = {
    "days": ("--days",),
    "var": ("--var",),
    "region_mode": ("--region",),
    "view": ("--view",),
    "focus_station_ids": ("--focus-station",),
    "threshold": ("--threshold",),
    "level": ("--level",),
    "output": ("--output",),
    "dpi": ("--dpi",),
    "title": ("--title",),
}


def run_trend(**kwargs: Any) -> None:
    """Plot a single-station or regional hourly trend."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        command="trend",
        kwargs=kwargs,
        options=TREND_OPTIONS,
        positionals={
            "target": kwargs["target"],
            "date": kwargs["date_arg"],
        },
        emit=lambda created: _emit_trend(created, **kwargs),
    )


def _emit_trend(
    created: list[Path],
    *,
    target: str,
    date_arg: str,
    days: int,
    var: str,
    region_mode: bool,
    view: str,
    focus_station_ids: list[str] | None,
    threshold: float | None,
    level: str | None,
    output: str | None,
    dpi: int | None,
    title: str | None,
    console: Console,
) -> None:
    """Read and plot the trend, then write the sidecar and series file."""
    from rsplot.config import STATION_VAR_META, get_exceedance_threshold
    from rsplot.data_files import (
        data_path,
        write_series_netcdf,
        write_source_manifest,
    )
    from rsplot.geo.boundaries import resolve_region
    from rsplot.plotting.styles import setup_fonts
    from rsplot.result_builders.envelope import (
        option_given,
        request_block,
        resolved,
        sidecar_path,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.satellite import FILES_LIMIT
    from rsplot.result_builders.series_layer import (
        region_series_layers,
        station_series_layer,
    )
    from rsplot.temporal import parse_date_window

    if days < 1:
        raise RsplotError(
            "invalid_argument", "--days 必须 >= 1", option="--days"
        )
    if var not in STATION_VAR_META:
        raise RsplotError(
            "invalid_argument",
            f"未知变量 '{var}'。可用: {', '.join(STATION_VAR_META)}",
            option="--var",
        )
    use_view = view.lower()
    if use_view not in ("lines", "mean"):
        raise RsplotError(
            "invalid_argument", "--view 仅支持 lines / mean", option="--view"
        )
    if not region_mode and use_view != "lines":
        raise RsplotError(
            "invalid_argument",
            "--view 仅用于 --region 区域趋势",
            option="--view",
        )
    if not region_mode and focus_station_ids:
        raise RsplotError(
            "invalid_argument",
            "--focus-station 仅用于 --region 区域趋势",
            option="--focus-station",
        )
    if not region_mode and level is not None:
        raise RsplotError(
            "invalid_argument",
            "--level 仅用于 --region 区域趋势",
            option="--level",
        )
    if threshold is not None and (
        not math.isfinite(threshold) or threshold < 0
    ):
        raise RsplotError(
            "invalid_argument",
            "--threshold 必须是大于等于 0 的有限数字",
            option="--threshold",
        )

    try:
        dates = parse_date_window(date_arg, default_days=days)
    except ValueError as error:
        raise RsplotError("invalid_time", str(error)) from error
    requested_focus_ids = _normalize_focus_ids(focus_station_ids or [])

    cfg = AppConfig.load()
    setup_fonts(cfg.font_dir)
    use_data_dir = cfg.get_data_dir("guokong")
    unit, limit_key, limit_time = STATION_VAR_META[var]
    use_threshold = (
        threshold if threshold is not None else get_exceedance_threshold(var)
    )
    standard = (
        "--threshold"
        if threshold is not None
        else f"AQ_LIMITS_2026 {limit_key} {limit_time}"
        if use_threshold is not None
        else None
    )
    use_dpi = dpi if dpi is not None else cfg.dpi
    try:
        validate_positive(use_dpi, "--dpi")
    except ValueError as error:
        raise RsplotError("invalid_argument", str(error)) from error

    info = None
    if region_mode:
        try:
            info = resolve_region(target, cfg, level_override=level)
        except RsplotError:
            raise
        except ValueError as error:
            raise RsplotError(
                "region_not_found", str(error), details={"region": target}
            ) from error

    if info is None:
        trend = _read_single_trend(
            station_id=target,
            dates=dates,
            var=var,
            data_dir=use_data_dir,
            console=console,
        )
        name = trend.station_id
        default_title = f"站点 {trend.station_id} · {var}"
    else:
        trend = _read_region_trend(
            info_name=info.name,
            info_level=info.level,
            geometry=info.geometry,
            dates=dates,
            var=var,
            data_dir=use_data_dir,
            view=use_view,
            console=console,
        )
        name = info.name
        default_title = f"{info.name} · {var} 站点趋势"
        canonical_focus_ids = _resolve_focus_ids(trend, requested_focus_ids)
        if canonical_focus_ids:
            console.print(f"  → 重点站: {', '.join(canonical_focus_ids)}")

    use_output = output or (
        f"/tmp/rsplot_trend_{name}_{var}_{dates[0]}_{dates[-1]}.png"
    )
    use_title = title or default_title
    image = str(Path(use_output).resolve())
    sidecar = sidecar_path(image)

    root = str(use_data_dir)
    files = sorted(os.path.relpath(path, root) for path in trend.source_files)
    failed = {
        f"{stamp}.nc": reason
        for stamp, reason in sorted(trend.failed_files.items())
    }
    data_entries = []
    manifest = None
    if len(files) > FILES_LIMIT:
        manifest_path = data_path(image, "sources", ".csv")
        created.append(manifest_path)
        manifest_entry = write_source_manifest(manifest_path, files, failed)
        data_entries.append(manifest_entry)
        manifest = manifest_entry["path"]
    source = {
        "sensor": "station",
        "processing": None,
        "data_root": root,
        "files": files[:FILES_LIMIT],
        "files_total": len(files),
        "files_manifest": manifest,
        "failed_files": failed,
    }

    series_path = data_path(image, "series", ".nc")
    created.append(series_path)
    attrs = {"quantity": var, "unit": unit or "1", "scale": 1}
    if info is None:
        series_entry = write_series_netcdf(
            series_path,
            station_ids=np.array([trend.station_id]),
            lon=np.array([trend.lon]),
            lat=np.array([trend.lat]),
            timestamps=trend.timestamps,
            values=trend.values,
            layer="station",
            attrs=attrs,
        )
        layer, flags = station_series_layer(
            station_id=trend.station_id,
            var=var,
            unit=unit,
            timestamps=trend.timestamps,
            values=np.asarray(trend.values, dtype=float),
            dates=dates,
            source=source,
            threshold=use_threshold,
            standard=standard,
            data=str(series_path),
        )
        layers = [layer]
        render_layer = {"threshold_line": use_threshold}
    else:
        series_entry = write_series_netcdf(
            series_path,
            station_ids=trend.station_ids,
            lon=trend.lon,
            lat=trend.lat,
            timestamps=trend.timestamps,
            values=trend.values,
            layer="station",
            attrs=attrs,
            regional_mean=trend.hourly_mean,
            hourly_counts=trend.hourly_valid_counts,
        )
        layers, flags = region_series_layers(
            station_ids=trend.station_ids,
            lon=trend.lon,
            lat=trend.lat,
            var=var,
            unit=unit,
            timestamps=trend.timestamps,
            values=np.asarray(trend.values, dtype=float),
            mean=trend.hourly_mean,
            counts=trend.hourly_valid_counts,
            dates=dates,
            source=source,
            threshold=use_threshold,
            standard=standard,
            data=str(series_path),
        )
        render_layer = {
            "view": use_view,
            "focus_station_ids": canonical_focus_ids,
            "threshold_line": use_threshold,
        }
    data_entries.insert(0, series_entry)

    console.print("\n[bold]绘图中...[/bold]")
    created.append(Path(image))
    if info is None:
        from rsplot.plotting.station_trend import plot_station_trend

        plot_station_trend(
            trend,
            unit=unit,
            threshold=use_threshold,
            dpi=use_dpi,
            output=image,
            title=use_title,
        )
    else:
        from rsplot.plotting.station_trend import plot_region_station_trend

        plot_region_station_trend(
            trend,
            region_name=info.name,
            unit=unit,
            threshold=use_threshold,
            view=use_view,
            focus_station_ids=canonical_focus_ids,
            dpi=use_dpi,
            output=image,
            title=use_title,
        )

    def source_of(name: str, value: Any, default: str) -> dict[str, Any]:
        if option_given(*TREND_OPTIONS[name]):
            return resolved(value, "cli")
        return resolved(value, default)

    request = {
        "target": resolved(target, "cli"),
        "date": resolved(date_arg, "cli"),
        "days": source_of("days", days, "built_in"),
        "var": source_of("var", var, "built_in"),
        "region_mode": source_of("region_mode", region_mode, "built_in"),
        "view": source_of("view", use_view, "built_in"),
        "focus_station_ids": (
            resolved(canonical_focus_ids, "cli")
            if info is not None and canonical_focus_ids
            else None
        ),
        "threshold": (
            resolved(use_threshold, "cli")
            if threshold is not None
            else resolved(use_threshold, "built_in", standard)
        ),
        "level": (
            source_of("level", info.level, "built_in")
            if info is not None
            else None
        ),
        "data_dir": resolved(root, "config"),
        "output": source_of("output", use_output, "built_in"),
        "dpi": source_of("dpi", use_dpi, "built_in"),
        "title": source_of("title", use_title, "built_in"),
    }
    payload = success_envelope(
        command="trend",
        request=request_block(request),
        region=info,
        layers=layers,
        flags=flags,
        render={
            "image": image,
            "dpi": int(use_dpi),
            "basemap": "none",
            "title": use_title,
            "layers": {"station": render_layer},
        },
        artifacts={"image": image, "sidecar": sidecar, "data": data_entries},
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {image}")


def _read_single_trend(
    *,
    station_id: str,
    dates: list[str],
    var: str,
    data_dir: str,
    console: Console,
):
    from rsplot.readers.guokong import read_station_series

    console.print(f"[bold]读取站点序列:[/bold] {data_dir}")
    console.print(
        f"  站点: {station_id}, 变量: {var}, "
        f"窗口: {dates[0]} ~ {dates[-1]} ({len(dates)} 天)"
    )
    series = read_station_series(data_dir, station_id, dates, var)
    console.print(
        f"  → [green]{series.n_valid}[/green]/{series.n_hours} 小时有效，"
        f"缺少文件 {len(series.missing_files)}，"
        f"读取失败 {len(series.failed_files)}"
    )
    if series.n_valid == 0:
        raise RsplotError("no_valid_data", "指定窗口内该站点没有有效观测值。")
    return series


def _read_region_trend(
    *,
    info_name: str,
    info_level: str,
    geometry: Any,
    dates: list[str],
    var: str,
    data_dir: str,
    view: str,
    console: Console,
) -> RegionStationSeries:
    from rsplot.readers.guokong import read_region_station_series

    console.print(f"[bold]解析区域:[/bold] {info_name} ({info_level})")
    console.print(f"[bold]读取区域站点序列:[/bold] {data_dir}")
    console.print(
        f"  变量: {var}, 窗口: {dates[0]} ~ {dates[-1]} "
        f"({len(dates)} 天), 视图: {view}"
    )
    try:
        series = read_region_station_series(data_dir, dates, var, geometry)
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError("read_failed", str(error)) from error
    if series.n_valid == 0:
        raise RsplotError(
            "no_valid_data", "指定窗口内目标区域没有有效观测值。"
        )
    console.print(
        f"  → [green]{series.n_stations}[/green] 个站点，"
        f"[green]{series.n_valid}[/green] 个有效观测值，"
        f"缺少文件 {len(series.missing_files)}，"
        f"读取失败 {len(series.failed_files)}"
    )
    return series


def _normalize_focus_ids(station_ids: list[str]) -> list[str]:
    """Normalize and de-duplicate requested focus IDs in input order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for station_id in station_ids:
        value = station_id.strip().upper()
        if not value:
            raise RsplotError(
                "invalid_argument",
                "--focus-station 不能为空",
                option="--focus-station",
            )
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _resolve_focus_ids(
    series: RegionStationSeries,
    requested: list[str],
) -> list[str]:
    """Return canonical focus IDs after region and data validation."""
    missing: list[str] = []
    empty: list[str] = []
    canonical: list[str] = []
    for station_id in requested:
        index = series.station_index(station_id)
        if index is None:
            missing.append(station_id)
            continue
        if not np.isfinite(series.values[index]).any():
            empty.append(station_id)
            continue
        canonical.append(str(series.station_ids[index]))
    if missing:
        raise RsplotError(
            "invalid_argument",
            f"--focus-station 不在目标区域内: {', '.join(missing)}",
            option="--focus-station",
        )
    if empty:
        raise RsplotError(
            "invalid_argument",
            f"--focus-station 在窗口内没有有效值: {', '.join(empty)}",
            option="--focus-station",
        )
    return canonical
