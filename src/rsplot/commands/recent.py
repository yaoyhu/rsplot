"""Implementation service for the ``recent`` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import (
    resolve_satellite,
    satellite_filter_label,
    validate_positive,
    validate_unit_interval,
)
from rsplot.config import AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console

    from rsplot.recent import RecentDaily

# Keyword argument -> CLI spellings, for recording where values came from.
RECENT_OPTIONS = {
    "days": ("--days",),
    "source": ("--source",),
    "sensor": ("--sensor",),
    "processing": ("--processing",),
    "product": ("--product",),
    "var": ("--var",),
    "output": ("--output",),
    "res": ("--res",),
    "qa": ("--qa",),
    "cf": ("--cf",),
}
RASTER_COLUMNS = [
    "date",
    "ok",
    "value",
    "n_valid",
    "coverage_fraction",
    "pixels",
    "error",
]
STATION_COLUMNS = [
    "date",
    "ok",
    "value",
    "hours",
    "n_valid",
    "n_stations",
    "n_exceed",
    "error",
]


def run_recent(**kwargs: Any) -> None:
    """Summarize recent days as JSON for an agent; no image is drawn."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        kwargs=kwargs,
        emit=lambda created: _emit_recent(created, **kwargs),
    )


def _emit_recent(
    created: list[Path],
    *,
    region: str,
    end_date: str,
    days: int,
    source: str,
    product: str | None,
    sensor: str = "tropomi",
    processing: str | None = None,
    var: str | None,
    output: str,
    res: float | None,
    qa: float | None,
    cf: float = 0.5,
    console: Console,
) -> None:
    from rsplot.config import STATION_VAR_META
    from rsplot.data_files import (
        data_path,
        write_source_manifest,
        write_table_csv,
    )
    from rsplot.geo.boundaries import resolve_region
    from rsplot.recent import (
        daily_limit,
        parse_recent_dates,
        summarize_recent_raster,
        summarize_recent_station,
        temporal_summary,
    )
    from rsplot.result_builders.envelope import (
        capped,
        coverage_block,
        flag,
        option_given,
        request_block,
        resolved,
        sidecar_path,
        stats_block,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.satellite import (
        FILES_LIMIT,
        collect_provenance,
    )
    from rsplot.stats import round_finite

    use_source = source.lower()
    if use_source not in ("raster", "station"):
        raise RsplotError(
            "invalid_argument",
            "--source 仅支持 raster / station",
            option="--source",
        )
    if use_source == "raster" and product is None:
        raise RsplotError(
            "invalid_argument",
            "--source raster 需要 --product 指定卫星产品。",
            option="--product",
        )
    if use_source == "station" and var is None:
        raise RsplotError(
            "invalid_argument",
            "--source station 需要 --var 指定站点变量。",
            option="--var",
        )
    if days < 1:
        raise RsplotError(
            "invalid_argument", "--days 必须 >= 1", option="--days"
        )
    try:
        dates = parse_recent_dates(end_date, days)
    except ValueError as error:
        raise RsplotError("invalid_time", str(error)) from error

    cfg = AppConfig.load()
    if use_source == "raster":
        prod_info, use_qa = resolve_satellite(
            product, sensor, qa, cfg, console, processing
        )
        sensor = prod_info.sensor
        processing = prod_info.processing
    elif processing is not None:
        raise RsplotError(
            "invalid_argument",
            "--processing 仅用于 --source raster。",
            option="--processing",
        )
    elif sensor.lower() != "tropomi":
        raise RsplotError(
            "invalid_argument",
            "--sensor gems 仅用于 --source raster。",
            option="--sensor",
        )
    elif var not in STATION_VAR_META:
        raise RsplotError(
            "invalid_argument",
            f"未知变量 '{var}'。可用: {', '.join(STATION_VAR_META)}",
            option="--var",
        )
    console.print(f"[bold]解析区域:[/bold] {region}")
    try:
        info = resolve_region(region, cfg)
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError(
            "region_not_found", str(error), details={"region": region}
        ) from error
    console.print(f"  → [green]{info.name}[/green] (级别: {info.level})")
    console.print(
        f"[bold]统计窗口:[/bold] {dates[0]} ~ {dates[-1]} ({len(dates)} 天)"
    )

    sidecar = sidecar_path(str(Path(output).resolve()))
    extra_data: list[dict[str, Any]] = []

    def source_of(name: str, value: Any, default: str) -> dict[str, Any]:
        if option_given(*RECENT_OPTIONS[name]):
            return resolved(value, "cli")
        return resolved(value, default)

    request: dict[str, Any] = {
        "region": resolved(region, "cli"),
        "end_date": resolved(end_date, "cli"),
        "days": source_of("days", days, "built_in"),
        "source": source_of("source", use_source, "built_in"),
        "level": resolved(info.level, "built_in", "from region"),
        "output": source_of("output", output, "built_in"),
    }

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
        except ValueError as error:
            raise RsplotError("invalid_argument", str(error)) from error
        use_data_dir = cfg.get_data_dir(prod_info.data_key or product)
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
        gems = sensor == "gems"
        layer_id = "satellite"
        quantity = {
            "name": prod_info.quantity,
            "unit": prod_info.unit,
            "scale": prod_info.unit_scale,
            "label": prod_info.colorbar_label,
        }
        time_zone = "Asia/Shanghai" if gems else "UTC"
        basis = (
            "asia_shanghai_calendar_day" if gems else "filename_start_date_utc"
        )
        files, failed, versions = collect_provenance(
            [row.meta for row in daily], str(use_data_dir)
        )
        source_block = {
            "sensor": sensor,
            "processing": (processing or "offl") if not gems else None,
            "data_root": str(use_data_dir),
            "files": files[:FILES_LIMIT],
            "files_total": len(files),
            "files_manifest": None,
            "failed_files": failed,
            "versions": versions,
        }
        method: dict[str, Any] = {
            "daily_value": "regional_mean_of_valid_cells",
            "cloud_fraction_max": cf,
            "grid_deg": use_res,
            "gap_fill": "none" if gems else "nearest_within_3_cells",
            "smoothing_sigma": 0,
            "cell_selection": "center_strictly_inside",
            "cell_weighting": "equal",
        }
        if gems:
            method["quality_filter"] = (
                "final_algorithm_flag_0_sza_vza_below_70"
            )
        else:
            method["qa_min_exclusive"] = use_qa
        rows = [_raster_row(row) for row in daily]
        columns = RASTER_COLUMNS
        request.update(
            product=source_of("product", product, "built_in"),
            sensor=source_of("sensor", sensor, "built_in"),
            processing=source_of(
                "processing", source_block["processing"], "built_in"
            ),
            data_dir=resolved(str(use_data_dir), "config"),
            res=source_of("res", use_res, "level_default"),
            qa=None if gems else source_of("qa", use_qa, "config"),
            cf=source_of("cf", cf, "built_in"),
        )
    else:
        use_data_dir = cfg.get_data_dir("guokong")
        unit = STATION_VAR_META[var][0]
        console.print(f"\n[bold]统计站点:[/bold] {use_data_dir} (变量: {var})")
        daily, hourly = summarize_recent_station(
            region=info,
            data_dir=use_data_dir,
            dates=dates,
            var_name=var,
            console=console,
        )
        layer_id = "station"
        quantity = {
            "name": var,
            "unit": unit or "1",
            "scale": 1,
            "label": f"{var} ({unit})" if unit else var,
        }
        time_zone = "Asia/Shanghai"
        basis = "asia_shanghai_calendar_day"
        files = sorted(
            Path(path).name for path in (hourly.source_files if hourly else [])
        )
        failed = {
            f"{stamp}.nc": reason
            for stamp, reason in sorted(
                (hourly.failed_files if hourly else {}).items()
            )
        }
        manifest = None
        if len(files) > FILES_LIMIT:
            manifest_path = data_path(sidecar, "sources", ".csv")
            created.append(manifest_path)
            manifest_entry = write_source_manifest(
                manifest_path, files, failed
            )
            extra_data.append(manifest_entry)
            manifest = manifest_entry["path"]
        source_block = {
            "sensor": "station",
            "processing": None,
            "data_root": str(use_data_dir),
            "files": files[:FILES_LIMIT],
            "files_total": len(files),
            "files_manifest": manifest,
            "failed_files": failed,
        }
        method = {
            "daily_value": "mean_of_station_daily_values",
            "station_daily_value": "mean_of_available_hours",
            "hours_per_day": 24,
            "daily_limit": daily_limit(var),
            "region_selection": "point_inside_region",
        }
        rows = [_station_row(row) for row in daily]
        columns = STATION_COLUMNS
        request.update(
            var=source_of("var", var, "built_in"),
            data_dir=resolved(str(use_data_dir), "config"),
        )

    values = np.array(
        [
            row.value if row.ok and row.value is not None else np.nan
            for row in daily
        ],
        dtype=float,
    )
    valid = np.isfinite(values)
    coverage = coverage_block(int(valid.sum()), len(dates), "days")
    order = np.flatnonzero(valid)[np.argsort(values[valid])[::-1]]
    table_path = data_path(sidecar, "daily", ".csv")
    layer = {
        "id": layer_id,
        "kind": "series",
        "quantity": quantity,
        "time": {
            "aggregation": "daily_series",
            "start": dates[0],
            "end": dates[-1],
            "timezone": time_zone,
            "basis": basis,
        },
        "source": source_block,
        "method": method,
        "coverage": coverage,
        "stats": stats_block(values),
        "by_admin": [],
        "extremes": capped(
            [
                {"date": dates[index], "value": round_finite(values[index])}
                for index in order
            ],
            coverage["valid"],
            "value_desc",
        ),
        "temporal_summary": temporal_summary(daily),
        "data": str(table_path),
    }
    failed_days = {row.date: row.error for row in daily if not row.ok}
    flags: list[dict[str, Any]] = []
    if coverage["valid"] == 0:
        flags.append(
            flag(
                "no_valid_data",
                "critical",
                "No requested day has a valid regional value.",
                layer=layer_id,
                evidence={"failed": failed_days},
            )
        )
    elif failed_days:
        flags.append(
            flag(
                "missing_days",
                "warning",
                f"{len(failed_days)} of {len(dates)} days have no valid "
                "regional value; window comparisons use fewer days.",
                layer=layer_id,
                evidence={"failed": failed_days},
            )
        )

    created.append(table_path)
    table_entry = write_table_csv(
        table_path,
        rows,
        columns,
        content="daily_table",
        layer=layer_id,
    )
    payload = success_envelope(
        command="recent",
        request=request_block(request),
        region=info,
        layers=[layer],
        flags=flags,
        render=None,
        artifacts={
            "image": None,
            "sidecar": sidecar,
            "data": [table_entry, *extra_data],
        },
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(
        f"\n[bold green]✓ 已保存:[/bold green] {sidecar} "
        f"(有效 {coverage['valid']}/{len(dates)} 天，失败 {len(failed_days)})"
    )


def _raster_row(row: RecentDaily) -> dict[str, Any]:
    stats = row.stats
    total = stats.get("total_region_pixels") or 0
    valid = stats.get("valid_region_pixels") or 0
    return {
        "date": row.date,
        "ok": int(row.ok),
        "value": float(row.value) if row.value is not None else np.nan,
        "n_valid": valid,
        "coverage_fraction": float(valid / total) if total else np.nan,
        "pixels": row.meta.get("n_pixels", ""),
        "error": row.error or "",
    }


def _station_row(row: RecentDaily) -> dict[str, Any]:
    return {
        "date": row.date,
        "ok": int(row.ok),
        "value": float(row.value) if row.value is not None else np.nan,
        "hours": row.meta.get("hours", ""),
        "n_valid": row.meta.get("n_valid", ""),
        "n_stations": row.meta.get("n_stations", ""),
        "n_exceed": row.meta.get("n_exceed", ""),
        "error": row.error or "",
    }
