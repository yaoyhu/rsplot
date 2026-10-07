"""Implementation service for the ``raster`` command."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import (
    parse_basemap,
    resolve_satellite,
    satellite_filter_label,
    validate_color_range,
    validate_non_negative,
    validate_positive,
    validate_unit_interval,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console

    from rsplot.geo.boundaries import RegionInfo
    from rsplot.result_builders.satellite import SatelliteInputs

# Keyword argument -> CLI spellings, for recording where values came from.
RASTER_OPTIONS = {
    "sensor": ("--sensor",),
    "processing": ("--processing",),
    "product": ("--product",),
    "days": ("--days",),
    "n_min": ("--n-min",),
    "output": ("--output",),
    "dpi": ("--dpi",),
    "res": ("--res",),
    "basemap": ("--basemap",),
    "vmin": ("--vmin",),
    "vmax": ("--vmax",),
    "cmap": ("--cmap",),
    "smooth": ("--smooth",),
    "title": ("--title",),
    "qa": ("--qa",),
    "cf": ("--cf",),
}


@dataclass
class RasterRun:
    """Prepared satellite layer and sidecar, independent of rendering."""

    lon: np.ndarray
    lat: np.ndarray
    grid: np.ndarray
    region: RegionInfo
    plot_options: dict[str, Any]
    # Inputs for the rsplot.result/2 satellite layer.
    satellite: SatelliteInputs | None = None
    resolved: dict[str, Any] = field(default_factory=dict)
    render: dict[str, Any] = field(default_factory=dict)


def run_raster(**kwargs: Any) -> None:
    """Prepare, render, and emit the administrative raster command."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        command="raster",
        kwargs=kwargs,
        options=RASTER_OPTIONS,
        positionals={"region": kwargs["region"], "date": kwargs["date_arg"]},
        emit=lambda created: _emit_raster(kwargs, created),
    )


def _emit_raster(kwargs: dict[str, Any], created: list[Path]) -> None:
    from rsplot.data_files import (
        data_path,
        write_grid_netcdf,
        write_source_manifest,
    )
    from rsplot.plotting.raster import plot_raster
    from rsplot.result_builders.envelope import (
        request_block,
        sidecar_path,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.satellite import (
        FILES_LIMIT,
        build_satellite_layer,
        collect_provenance,
    )

    run = prepare_raster(**kwargs)
    inputs = run.satellite
    assert inputs is not None
    image = str(Path(run.plot_options["output"]).resolve())
    sidecar = str(Path(sidecar_path(image)))

    grid_path = data_path(image, "satellite", ".nc")
    created.append(grid_path)
    grid_entry = write_grid_netcdf(
        grid_path,
        inputs.lon,
        inputs.lat,
        inputs.grid,
        inputs.counted,
        extent=run.region.extent,
        layer="satellite",
        attrs={
            "quantity": inputs.prod_info.quantity,
            "unit": inputs.prod_info.unit,
            "scale": inputs.prod_info.unit_scale,
            "time_aggregation": inputs.time["aggregation"],
        },
        valid_days=inputs.valid_days,
    )
    data_entries = [grid_entry]
    files, failed, _ = collect_provenance(inputs.metadata, inputs.data_root)
    manifest = None
    if len(files) > FILES_LIMIT:
        manifest_path = data_path(image, "sources", ".csv")
        created.append(manifest_path)
        manifest_entry = write_source_manifest(manifest_path, files, failed)
        data_entries.append(manifest_entry)
        manifest = manifest_entry["path"]

    created.append(Path(image))
    plot_raster(run.lon, run.lat, run.grid, run.region, **run.plot_options)
    layer, flags = build_satellite_layer(
        inputs,
        run.region,
        data=grid_entry["path"],
        files_manifest=manifest,
    )
    payload = success_envelope(
        command="raster",
        request=request_block(run.resolved),
        region=run.region,
        layers=[layer],
        flags=flags,
        render={"image": image, **run.render},
        artifacts={"image": image, "sidecar": sidecar, "data": data_entries},
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    kwargs["console"].print(f"[bold green]✓ 已保存:[/bold green] {image}")


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
        raise RsplotError(
            "invalid_argument", "--days 必须 >= 1。", option="--days"
        )
    if days is not None and "-" in date_arg:
        raise RsplotError(
            "invalid_argument",
            "日期区间不能与 --days 同时使用；"
            "请选择 YYYYMMDD-YYYYMMDD 或结束日期 YYYYMMDD 配合 --days N。",
            option="--days",
        )
    try:
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
    except RsplotError:
        raise
    except ValueError as error:
        raise RsplotError("invalid_time", str(error)) from error
    return dates, window_mode


def _source(
    name: str,
    value: Any,
    default_source: str,
    detail: str | None = None,
) -> dict[str, Any]:
    """Record a value as CLI-supplied when its option appears in argv."""
    from rsplot.result_builders.envelope import option_given, resolved

    if option_given(*RASTER_OPTIONS[name]):
        return resolved(value, "cli")
    return resolved(value, default_source, detail)


def prepare_raster(
    *,
    region: str | RegionInfo,
    date_arg: str,
    product: str,
    sensor: str = "tropomi",
    processing: str | None = None,
    days: int | None,
    n_min: int | None,
    output: str,
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
    from rsplot.geo.gridding import region_grid_mask
    from rsplot.geo.processing import (
        buffered_extent,
        prepare_display_grid,
        prepare_existing_grid,
        prepare_swath_grid,
    )
    from rsplot.plotting.styles import setup_fonts
    from rsplot.readers import auto_vrange
    from rsplot.result_builders.common import grid_boundary_policy
    from rsplot.result_builders.envelope import resolved, stats_block
    from rsplot.result_builders.satellite import SatelliteInputs
    from rsplot.temporal import compute_window_mean, read_scan_mean

    cfg = AppConfig.load()
    prod_info, use_qa = resolve_satellite(
        product, sensor, qa, cfg, console, processing
    )
    sensor = prod_info.sensor
    processing = prod_info.processing
    scan_mode = sensor == "gems" and len(date_arg) == 12
    scan_time = None
    if scan_mode:
        from rsplot.readers.gems import parse_gems_time

        try:
            scan_time = parse_gems_time(date_arg)
        except ValueError as error:
            raise RsplotError("invalid_time", str(error)) from error
        if days is not None or n_min is not None:
            raise RsplotError(
                "invalid_argument",
                "GEMS 单次扫描不能同时使用 --days 或 --n-min。",
                option="--days" if days is not None else "--n-min",
            )
    dates, window_mode = parse_raster_dates(
        date_arg[:8] if scan_mode else date_arg, days
    )

    window_n = len(dates)
    use_n_min: int | None = None
    if n_min is not None and n_min < 1:
        raise RsplotError(
            "invalid_argument", "--n-min 必须 >= 1。", option="--n-min"
        )
    if not window_mode and n_min is not None:
        raise RsplotError(
            "invalid_argument",
            "--n-min 仅用于日期范围或 --days 窗口。",
            option="--n-min",
        )
    if window_mode:
        use_n_min = (
            n_min
            if n_min is not None
            else default_raster_n_min(product, window_n)
        )
        if use_n_min > window_n:
            raise RsplotError(
                "invalid_argument",
                f"--n-min ({use_n_min}) 大于窗口天数 ({window_n})",
                option="--n-min",
            )

    setup_fonts(cfg.font_dir)

    if isinstance(region, RegionInfo):
        info = region
    else:
        try:
            info = resolve_regions(region, cfg)
        except RsplotError:
            raise
        except ValueError as error:
            raise RsplotError(
                "region_not_found", str(error), details={"region": region}
            ) from error
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
        raise RsplotError("invalid_argument", str(e)) from e
    if use_smooth == 0:
        use_smooth = None
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    read_extent = buffered_extent(info.extent, 1.0)
    use_data_dir = cfg.get_data_dir(prod_info.data_key or product)
    reader = prod_info.create_reader()
    reader.cloud_fraction_max = cf
    if sensor == "gems":
        console.print(f"  → GEMS 目标网格 {use_res}°（分析与显示）")
    scientific_valid_mask: np.ndarray | None = None
    provenance: list[dict[str, Any]] = []
    pixels_used = 0
    valid_days: np.ndarray | None = None

    try:
        if not window_mode:
            console.print(
                f"\n[bold]读取数据:[/bold] {use_data_dir} (产品: {product})"
            )
            console.print(
                f"  时间: {date_arg}, "
                f"{satellite_filter_label(sensor, use_qa, cf)}"
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
                scientific_valid_mask = np.isfinite(prepared.values)
                provenance = [batch.metadata]
                pixels_used = int(batch.n_pixels)
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
                scientific_valid_mask = np.isfinite(prepared.values)
                provenance = [swath.metadata]
                pixels_used = int(swath.n_pixels)
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
                f"({window.n_files_total} 文件, "
                f"{window.n_broken_total} 损坏)"
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
            provenance = list(window.daily_metadata.values())
            pixels_used = int(window.n_pixels_total)
            valid_days = window.n_valid

    except (RsplotError, OSError):
        raise
    except ValueError as error:
        # Readers raise ValueError when nothing valid survives filtering.
        raise RsplotError("no_valid_data", str(error)) from error

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
    else:
        display_grid = prepare_display_grid(
            prepared.lon,
            prepared.lat,
            display_source,
            info.geometry,
            smooth_sigma=use_smooth,
        )

    if not np.isfinite(display_grid).any():
        if window_mode:
            message = (
                "窗口均值全区无有效像元，可能原因：窗口内覆盖不足，"
                "或 --n-min 太严。可放宽 --n-min / 扩大窗口。"
            )
        else:
            message = (
                f"{date_arg} 在目标区域 {info.name} 内无有效像元。"
                "请检查所选日期、区域及质量/云量筛选条件。"
            )
        raise RsplotError("no_valid_data", message)

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
        vrange_source = "cli"
    elif prod_info.vmin is not None and prod_info.vmax is not None:
        use_vmin = vmin if vmin is not None else prod_info.vmin
        use_vmax = vmax if vmax is not None else prod_info.vmax
        vrange_source = "product_default"
    else:
        auto_min, auto_max = auto_vrange(
            prepared.values
            if np.isfinite(prepared.values).any()
            else display_grid,
            prod_info,
        )
        use_vmin = vmin if vmin is not None else auto_min
        use_vmax = vmax if vmax is not None else auto_max
        vrange_source = "built_in"
    try:
        validate_color_range(use_vmin, use_vmax)
    except ValueError as e:
        raise RsplotError("invalid_argument", f"色标范围无效：{e}") from e
    console.print(f"  → 色标范围: {use_vmin:.1f} ~ {use_vmax:.1f}")

    if processing == "nrti":
        period = f"{dates[0]}_{dates[-1]}" if window_mode else date_arg
        if title is None:
            label = " mean" if window_mode else ""
            title = (
                f"TROPOMI NRTI {product.upper()} - {info.name} "
                f"({period}{label})"
            )

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
    if title is None:
        # The renderer's own default, recorded so the sidecar states it.
        title = f"TROPOMI - {info.name}"

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

    # --- rsplot.result/2 inputs -------------------------------------------
    stat_grid = prepared.values if statistics_grid is None else statistics_grid
    counted = region_grid_mask(prepared.lon, prepared.lat, info.geometry)
    china = sensor == "gems"
    basis = (
        "asia_shanghai_calendar_day" if china else "filename_start_date_utc"
    )
    timezone_name = "Asia/Shanghai" if china else "UTC"
    if scan_mode:
        from datetime import timezone

        time = {
            "aggregation": "scan",
            "at": date_arg,
            "timezone": "Asia/Shanghai",
            "basis": "nominal_scan_time",
            "archive_time_utc": scan_time.astimezone(timezone.utc).strftime(
                "%Y%m%d%H%M"
            ),
        }
    else:
        time = {
            "aggregation": (
                "window_mean"
                if window_mode
                else "daily_scan_mean"
                if china
                else "daily"
            ),
            "start": dates[0],
            "end": dates[-1],
            "timezone": timezone_name,
            "basis": basis,
        }
    days_block = None
    if window_mode:
        assert use_n_min is not None and valid_days is not None
        days_block = {
            "requested": window_n,
            "found": len(window.dates_found),
            "failed": dict(window.dates_failed),
            "n_min": use_n_min,
            "valid_days_per_cell": stats_block(
                valid_days[counted & (valid_days > 0)].astype(float)
            ),
        }

    method: dict[str, Any] = {
        "cloud_fraction_max": cf,
        "grid_deg": use_res,
        "pixels_used": pixels_used,
        "cell_selection": "center_strictly_inside",
        "cell_weighting": "equal",
    }
    if china:
        scans = [scan for meta in provenance for scan in meta.get("scans", [])]
        method.update(
            quality_filter="final_algorithm_flag_0_sza_vza_below_70",
            spatial_aggregation="footprint_overlap_area_mean",
            area_crs="EPSG:6933",
            scan_weighting="equal_scans",
            scans_found=len(scans),
            scans_valid=sum(scan.get("n_pixels", 0) > 0 for scan in scans),
            footprint_source=sorted(
                {
                    scan["footprint_source"]
                    for scan in scans
                    if "footprint_source" in scan
                }
            ),
            gap_fill="none",
            smoothing_sigma=0,
        )
    else:
        method.update(
            qa_min_exclusive=use_qa,
            gap_fill="none" if window_mode else "nearest_within_3_cells",
            smoothing_sigma=use_smooth or 0,
            smoothing_affects="values_not_coverage",
        )
        if processing == "nrti":
            dedup = [m for m in provenance if "deduplication" in m]
            method["deduplication"] = (
                dedup[0]["deduplication"] if dedup else None
            )
            method["duplicates_removed"] = sum(
                int(m.get("n_duplicates_removed", 0)) for m in dedup
            )
    if window_mode:
        method["day_weighting"] = "equal_days"

    satellite = SatelliteInputs(
        prod_info=prod_info,
        lon=prepared.lon,
        lat=prepared.lat,
        grid=stat_grid,
        counted=counted,
        time=time,
        data_root=str(use_data_dir),
        metadata=provenance,
        method=method,
        valid_days=valid_days,
        days=days_block,
        smoothing_sigma=None if china else use_smooth,
    )

    if res is not None:
        res_entry = resolved(use_res, "cli")
    elif product_defaults.res is not None:
        res_entry = resolved(use_res, "product_default", info.level)
    else:
        res_entry = resolved(use_res, "level_default", info.level)
    if smooth is not None:
        smooth_entry = resolved(use_smooth or 0, "cli")
    elif product_defaults.smooth_sigma is not None:
        smooth_entry = resolved(use_smooth or 0, "product_default", info.level)
    else:
        smooth_entry = resolved(use_smooth or 0, "level_default", info.level)
    effective_basemap = (
        use_basemap if use_basemap is not None else params.basemap
    )
    resolved_values = {
        "region": resolved(
            region if isinstance(region, str) else info.name, "cli"
        ),
        "date": resolved(date_arg, "cli"),
        "sensor": _source("sensor", sensor, "built_in"),
        "processing": _source(
            "processing",
            processing or ("offl" if not china else None),
            "built_in",
        ),
        "product": _source("product", product, "built_in"),
        "days": _source("days", days, "built_in") if days else None,
        "n_min": (
            _source(
                "n_min",
                use_n_min,
                "product_default",
                "max(3, days // 2); HCHO max(3, ceil(days * 0.25)); "
                "capped at days",
            )
            if window_mode
            else None
        ),
        "level": resolved(info.level, "built_in", "from region"),
        "data_dir": resolved(str(use_data_dir), "config"),
        "res": res_entry,
        "smooth": smooth_entry,
        "qa": None if china else _source("qa", use_qa, "config"),
        "cf": _source("cf", cf, "built_in"),
        "dpi": _source("dpi", use_dpi, "built_in"),
        "basemap": _source(
            "basemap",
            "satellite" if effective_basemap else "none",
            "level_default",
            info.level,
        ),
        "cmap": _source("cmap", use_cmap, "product_default"),
        "vmin": resolved(
            use_vmin,
            "cli" if vmin is not None else vrange_source,
            None
            if vmin is not None or vrange_source != "built_in"
            else "auto_percentile",
        ),
        "vmax": resolved(
            use_vmax,
            "cli" if vmax is not None else vrange_source,
            None
            if vmax is not None or vrange_source != "built_in"
            else "auto_percentile",
        ),
        "title": _source("title", title, "built_in"),
        "output": _source("output", output, "built_in"),
    }
    display_policy = grid_boundary_policy(
        display_lon, display_lat, display_grid, info
    )["display"]
    if sensor == "gems":
        display_policy["clip"] += "_and_analysis_valid_cells"
    render = {
        "dpi": int(use_dpi),
        "basemap": "satellite" if effective_basemap else "none",
        "title": title,
        "layers": {
            "satellite": {
                "cmap": use_cmap,
                "vmin": use_vmin,
                "vmax": use_vmax,
                "display_smoothing_sigma": use_smooth or 0,
                "display_grid_shape": list(display_grid.shape),
                "display_selection": display_policy["selection"],
                "display_clip": display_policy["clip"],
                "display_valid_cells": display_policy[
                    "n_valid_intersecting_cells"
                ],
            }
        },
    }
    return RasterRun(
        display_lon,
        display_lat,
        display_grid,
        info,
        plot_options,
        satellite=satellite,
        resolved=resolved_values,
        render=render,
    )
