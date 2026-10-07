"""Implementation service for the ``fnr`` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from rsplot.commands.common import (
    parse_basemap,
    parse_explicit_window,
    print_failed_dates,
    resolve_satellite,
    validate_non_negative,
    validate_positive,
    validate_unit_interval,
    warn_missing_tianditu_key,
)
from rsplot.config import AppConfig
from rsplot.errors import RsplotError

if TYPE_CHECKING:
    from rich.console import Console

# Keyword argument -> CLI spellings, for recording where values came from.
FNR_OPTIONS = {
    "days": ("--days",),
    "n_min": ("--n-min",),
    "no2_min": ("--no2-min",),
    "voc_threshold": ("--voc-threshold",),
    "nox_threshold": ("--nox-threshold",),
    "display_max": ("--display-max",),
    "output": ("--output",),
    "dpi": ("--dpi",),
    "res": ("--res",),
    "basemap": ("--basemap",),
    "smooth": ("--smooth",),
    "qa": ("--qa",),
    "cf": ("--cf",),
    "processing": ("--processing",),
    "title": ("--title",),
}
REGIMES = ("voc_limited", "transition", "nox_limited")


def run_fnr(**kwargs: Any) -> None:
    """Map the HCHO/NO2 ratio and its ozone-sensitivity regimes."""
    from rsplot.commands.sidecar import run_with_sidecar

    run_with_sidecar(
        command="fnr",
        kwargs=kwargs,
        options=FNR_OPTIONS,
        positionals={"region": kwargs["region"], "date": kwargs["date_arg"]},
        emit=lambda created: _emit_fnr(created, **kwargs),
    )


def _emit_fnr(
    created: list[Path],
    *,
    region: str,
    date_arg: str,
    days: int | None,
    n_min: int | None,
    no2_min: float,
    voc_threshold: float,
    nox_threshold: float,
    display_max: float,
    output: str,
    dpi: int | None,
    res: float | None,
    basemap: str | None,
    smooth: float | None,
    qa: float | None,
    cf: float = 0.5,
    processing: str | None = None,
    title: str | None,
    console: Console,
) -> None:
    """Compute FNR over a window, plot it, and write the sidecar."""
    from rsplot.data_files import data_path, write_grid_netcdf
    from rsplot.fnr import (
        compute_fnr,
        regime_percentages,
        validate_fnr_thresholds,
    )
    from rsplot.geo.boundaries import resolve_region
    from rsplot.geo.gridding import grid_coverage_in_region, region_grid_mask
    from rsplot.plotting.fnr import plot_fnr
    from rsplot.plotting.styles import setup_fonts
    from rsplot.result_builders.common import top_hotspots
    from rsplot.result_builders.envelope import (
        capped,
        coverage_block,
        coverage_flags,
        flag,
        option_given,
        request_block,
        resolved,
        sidecar_path,
        stats_block,
        subdivision_level,
        success_envelope,
        write_sidecar,
    )
    from rsplot.result_builders.fnr import fnr_per_admin_stats
    from rsplot.result_builders.satellite import (
        SatelliteInputs,
        build_satellite_layer,
    )

    cfg = AppConfig.load()
    no2_info, _ = resolve_satellite(
        "no2", "tropomi", qa, cfg, console, processing
    )
    hcho_info, _ = resolve_satellite(
        "hcho", "tropomi", qa, cfg, console, processing
    )
    processing = no2_info.processing
    setup_fonts(cfg.font_dir)

    dates = parse_explicit_window(date_arg, days)

    window_n = len(dates)
    if n_min is not None and n_min < 1:
        raise RsplotError(
            "invalid_argument", "--n-min 必须 >= 1。", option="--n-min"
        )
    use_n_min = (
        n_min if n_min is not None else min(window_n, max(3, window_n // 2))
    )
    if use_n_min > window_n:
        raise RsplotError(
            "invalid_argument",
            f"--n-min ({use_n_min}) 大于窗口天数 ({window_n})",
            option="--n-min",
        )
    try:
        use_voc_threshold, use_nox_threshold, use_display_max = (
            validate_fnr_thresholds(
                voc_threshold=voc_threshold,
                nox_threshold=nox_threshold,
                display_max=display_max,
            )
        )
    except ValueError as error:
        raise RsplotError(
            "invalid_argument", f"FNR 阈值错误 (threshold): {error}"
        ) from error

    console.print(
        f"[bold]时间窗口:[/bold] {dates[0]} ~ {dates[-1]} "
        f"({window_n} 天，每像元至少 {use_n_min} 天有效)"
    )
    console.print(
        f"[bold]FNR 分级:[/bold] VOC<{use_voc_threshold:g}, "
        f"transition {use_voc_threshold:g}~{use_nox_threshold:g}, "
        f"NOx>{use_nox_threshold:g}"
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

    params = info.params
    use_res = res if res is not None else params.res
    use_dpi = dpi if dpi is not None else cfg.dpi
    use_qa = qa if qa is not None else cfg.qa_threshold
    use_smooth = smooth if smooth is not None else params.smooth_sigma

    try:
        use_basemap = parse_basemap(basemap)
        validate_positive(use_dpi, "--dpi")
        validate_positive(use_res, "--res")
        validate_unit_interval(use_qa, "--qa")
        validate_unit_interval(cf, "--cf")
        validate_non_negative(no2_min, "--no2-min")
        if use_smooth is not None:
            validate_non_negative(use_smooth, "--smooth")
    except ValueError as error:
        raise RsplotError("invalid_argument", str(error)) from error
    if use_smooth == 0:
        use_smooth = None
    warn_missing_tianditu_key(
        basemap=use_basemap,
        default_basemap=params.basemap,
        tianditu_key=cfg.tianditu_key,
        console=console,
    )

    use_no2_dir = cfg.get_data_dir(no2_info.data_key or "no2")
    use_hcho_dir = cfg.get_data_dir(hcho_info.data_key or "hcho")
    console.print("\n[bold]读取数据:[/bold]")
    console.print(f"  NO2 : {use_no2_dir}")
    console.print(f"  HCHO: {use_hcho_dir}")
    console.print(f"  QA > {use_qa}, CF <= {cf}")

    try:
        fnr_out = compute_fnr(
            info,
            dates,
            res=use_res,
            qa_threshold=use_qa,
            cloud_fraction_max=cf,
            n_min=use_n_min,
            raster_dir_no2=use_no2_dir,
            raster_dir_hcho=use_hcho_dir,
            processing=processing,
            no2_min_column=no2_min,
            smooth_sigma=use_smooth,
            console=console,
        )
    except (RsplotError, OSError):
        raise
    except ValueError as error:
        # The window readers raise ValueError when every day failed.
        raise RsplotError("no_valid_data", str(error)) from error

    n_found_no2 = len(fnr_out.dates_found_no2)
    n_found_hcho = len(fnr_out.dates_found_hcho)
    console.print(
        f"  → NO2 有效天数 {n_found_no2}/{window_n} "
        f"(失败 {len(fnr_out.dates_failed_no2)})"
    )
    console.print(
        f"  → HCHO 有效天数 {n_found_hcho}/{window_n} "
        f"(失败 {len(fnr_out.dates_failed_hcho)})"
    )
    finite = fnr_out.fnr[np.isfinite(fnr_out.fnr)]
    if len(finite) == 0:
        print_failed_dates("NO2", fnr_out.dates_failed_no2, console=console)
        print_failed_dates("HCHO", fnr_out.dates_failed_hcho, console=console)
        raise RsplotError(
            "no_valid_data",
            "FNR 全区无有效像元，可能原因：窗口内 NO2/HCHO 都覆盖不足，"
            "或 --n-min 太严，或 --no2-min 过高。可放宽 --n-min / 扩大窗口。",
        )

    coverage_pct, n_valid_region, total_region_pixels = (
        grid_coverage_in_region(
            fnr_out.LON, fnr_out.LAT, fnr_out.fnr, info.geometry
        )
    )
    console.print(
        f"  → FNR 区域内覆盖率 {coverage_pct:.1f}% "
        f"({n_valid_region}/{total_region_pixels}), "
        f"中位数 {float(np.median(finite)):.2f}"
    )
    percentages = regime_percentages(
        fnr_out.fnr,
        voc_threshold=use_voc_threshold,
        nox_threshold=use_nox_threshold,
    )
    console.print(
        f"  → Regime: [red]VOC-limited {percentages['voc_limited']}%[/red] | "
        f"[yellow]transition {percentages['transition']}%[/yellow] | "
        f"[blue]NOx-limited {percentages['nox_limited']}%[/blue]"
    )

    if title is None and processing == "nrti":
        title = f"TROPOMI NRTI FNR - {info.name}"
    # The renderer's default title, recorded so the sidecar states it.
    use_title = title or f"FNR regime — {info.name}"
    image = str(Path(output).resolve())
    sidecar = sidecar_path(image)
    subtitle = (
        f"{dates[0]}~{dates[-1]}  ·  N_days={window_n} "
        f"(n_min={use_n_min})  ·  NO2≥{no2_min:g}×10¹⁵ molec/cm²"
    )

    lon, lat = fnr_out.LON, fnr_out.LAT
    counted = region_grid_mask(lon, lat, info.geometry)
    time = {
        "aggregation": "window_mean",
        "start": dates[0],
        "end": dates[-1],
        "timezone": "UTC",
        "basis": "filename_start_date_utc",
    }
    product_method = {
        "qa_min_exclusive": use_qa,
        "cloud_fraction_max": cf,
        "grid_deg": use_res,
        "gap_fill": "none",
        "day_weighting": "equal_days",
        "smoothing_sigma": 0,
        "cell_selection": "center_strictly_inside",
        "cell_weighting": "equal",
    }

    def days_block(found, failed, valid_days):
        return {
            "requested": window_n,
            "found": len(found),
            "failed": dict(failed),
            "n_min": use_n_min,
            "valid_days_per_cell": stats_block(
                valid_days[counted & (valid_days > 0)].astype(float)
            ),
        }

    layers: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    data_entries: list[dict[str, Any]] = []
    products = (
        (
            "no2",
            no2_info,
            fnr_out.no2_mean,
            fnr_out.n_valid_no2,
            fnr_out.dates_found_no2,
            fnr_out.dates_failed_no2,
            fnr_out.daily_metadata_no2,
            use_no2_dir,
        ),
        (
            "hcho",
            hcho_info,
            fnr_out.hcho_mean,
            fnr_out.n_valid_hcho,
            fnr_out.dates_found_hcho,
            fnr_out.dates_failed_hcho,
            fnr_out.daily_metadata_hcho,
            use_hcho_dir,
        ),
    )
    for name, prod, mean, valid_days, found, failed, daily, root in products:
        path = data_path(image, name, ".nc")
        created.append(path)
        entry = write_grid_netcdf(
            path,
            lon,
            lat,
            mean,
            counted,
            extent=info.extent,
            layer=name,
            attrs={
                "quantity": prod.quantity,
                "unit": prod.unit,
                "scale": prod.unit_scale,
                "time_aggregation": "window_mean",
            },
            valid_days=valid_days,
        )
        data_entries.append(entry)
        product_layer, product_flags = build_satellite_layer(
            SatelliteInputs(
                prod_info=prod,
                lon=lon,
                lat=lat,
                grid=mean,
                counted=counted,
                time=time,
                data_root=str(root),
                metadata=list(daily.values()),
                method=dict(product_method),
                valid_days=valid_days,
                days=days_block(found, failed, valid_days),
            ),
            info,
            data=entry["path"],
            files_manifest=None,
            layer_id=name,
            coverage_checks=False,
        )
        layers.append(product_layer)
        flags.extend(product_flags)

    both_valid = np.minimum(fnr_out.n_valid_no2, fnr_out.n_valid_hcho)
    fnr_path = data_path(image, "fnr", ".nc")
    created.append(fnr_path)
    fnr_entry = write_grid_netcdf(
        fnr_path,
        lon,
        lat,
        fnr_out.fnr,
        counted,
        extent=info.extent,
        layer="fnr",
        attrs={
            "quantity": "fnr",
            "unit": "1",
            "scale": 1.0,
            "time_aggregation": "window_mean",
        },
        valid_days=both_valid,
    )
    data_entries.append(fnr_entry)

    fnr_values = fnr_out.fnr[counted]
    fnr_valid = np.isfinite(fnr_values)
    coverage = coverage_block(
        int(fnr_valid.sum()), int(counted.sum()), "cells"
    )
    classified = fnr_values[fnr_valid]
    categories = {
        "voc_limited": int((classified < use_voc_threshold).sum()),
        "transition": int(
            (
                (classified >= use_voc_threshold)
                & (classified <= use_nox_threshold)
            ).sum()
        ),
        "nox_limited": int((classified > use_nox_threshold).sum()),
    }
    masks = {
        key: mask & counted for key, mask in fnr_out.diagnostic_masks.items()
    }
    sub_gdf = info.sub_boundary_gdf
    has_subdivisions = sub_gdf is not None and len(sub_gdf) > 0
    by_admin = []
    if has_subdivisions:
        level_name = subdivision_level(info)
        by_admin = [
            {
                "name": row["name"],
                "level": level_name,
                "n": int(row["n_pixels"]),
                "mean": row["mean_fnr"],
                "category": row["regime"],
            }
            for row in fnr_per_admin_stats(
                lon,
                lat,
                fnr_out.fnr,
                sub_gdf,
                voc_threshold=use_voc_threshold,
                nox_threshold=use_nox_threshold,
            )
        ]
    hotspots = top_hotspots(
        lon, lat, fnr_out.fnr, sub_gdf if has_subdivisions else None, n=10
    )
    found_both = sorted(
        set(fnr_out.dates_found_no2) & set(fnr_out.dates_found_hcho)
    )
    failed_either = {
        **{d: f"NO2: {m}" for d, m in fnr_out.dates_failed_no2.items()},
        **{d: f"HCHO: {m}" for d, m in fnr_out.dates_failed_hcho.items()},
    }
    fnr_layer: dict[str, Any] = {
        "id": "fnr",
        "kind": "grid",
        "quantity": {
            "name": "fnr",
            "unit": "1",
            "scale": 1,
            "label": "FNR (HCHO / NO2)",
        },
        "time": {
            **time,
            "days": days_block(found_both, failed_either, both_valid),
        },
        "source": {
            "sensor": "tropomi",
            "processing": processing or "offl",
            "data_root": str(use_no2_dir),
            "files": [],
            "files_total": 0,
            "files_manifest": None,
            "failed_files": {},
        },
        "method": {
            "ratio": "hcho_window_mean / no2_window_mean",
            "n_min_each_product": use_n_min,
            "no2_min_column": no2_min,
            "no2_min_unit": "1e15 molec/cm2",
            "hcho_min_column": 0,
            "smoothing_sigma": use_smooth or 0,
            "smoothing_affects": "values_not_coverage",
            "regime_thresholds": {
                "voc_limited_below": use_voc_threshold,
                "nox_limited_above": use_nox_threshold,
            },
            "mask_counts": {
                "region_cells": int(counted.sum()),
                "coverage_ge_n_min": int(masks["coverage_ok"].sum()),
                "no2_ge_threshold": int(masks["no2_ok"].sum()),
                "hcho_nonnegative": int(masks["hcho_ok"].sum()),
                "final_valid": coverage["valid"],
            },
            "inputs": ["no2", "hcho"],
            "cell_selection": "center_strictly_inside",
            "cell_weighting": "equal",
        },
        "coverage": coverage,
        "stats": stats_block(fnr_values),
        "categories": categories,
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
        "data": fnr_entry["path"],
    }
    layers.append(fnr_layer)
    flags.extend(coverage_flags("fnr", coverage))
    if use_smooth:
        flags.append(
            flag(
                "values_smoothed",
                "info",
                f"Gaussian smoothing (sigma {use_smooth:g}) changed FNR "
                "values; valid cells are unchanged. Use --smooth 0 for "
                "unsmoothed values.",
                layer="fnr",
                evidence={"sigma": use_smooth},
            )
        )

    console.print("\n[bold]绘图中...[/bold]")
    created.append(Path(image))
    plot_fnr(
        lon,
        lat,
        fnr_out.fnr,
        info,
        dpi=use_dpi,
        basemap=use_basemap,
        tianditu_key=cfg.tianditu_key,
        title=title,
        output=image,
        subtitle=subtitle,
        voc_threshold=use_voc_threshold,
        nox_threshold=use_nox_threshold,
        display_max=use_display_max,
    )

    def source_of(name: str, value: Any, default: str) -> dict[str, Any]:
        if option_given(*FNR_OPTIONS[name]):
            return resolved(value, "cli")
        return resolved(value, default)

    effective_basemap = (
        use_basemap if use_basemap is not None else params.basemap
    )
    request = {
        "region": resolved(region, "cli"),
        "date": resolved(date_arg, "cli"),
        "days": resolved(days, "cli") if days is not None else None,
        "n_min": source_of("n_min", use_n_min, "built_in"),
        "no2_min": source_of("no2_min", no2_min, "built_in"),
        "voc_threshold": source_of(
            "voc_threshold", use_voc_threshold, "built_in"
        ),
        "nox_threshold": source_of(
            "nox_threshold", use_nox_threshold, "built_in"
        ),
        "display_max": source_of("display_max", use_display_max, "built_in"),
        "level": resolved(info.level, "built_in", "from region"),
        "no2_dir": resolved(str(use_no2_dir), "config"),
        "hcho_dir": resolved(str(use_hcho_dir), "config"),
        "output": source_of("output", output, "built_in"),
        "dpi": source_of("dpi", use_dpi, "built_in"),
        "res": source_of("res", use_res, "level_default"),
        "basemap": source_of(
            "basemap",
            "satellite" if effective_basemap else "none",
            "level_default",
        ),
        "smooth": source_of("smooth", use_smooth or 0, "level_default"),
        "qa": source_of("qa", use_qa, "built_in"),
        "cf": source_of("cf", cf, "built_in"),
        "processing": source_of(
            "processing", processing or "offl", "built_in"
        ),
        "title": source_of("title", use_title, "built_in"),
    }
    payload = success_envelope(
        command="fnr",
        request=request_block(request),
        region=info,
        layers=layers,
        flags=flags,
        render={
            "image": image,
            "dpi": int(use_dpi),
            "basemap": "satellite" if effective_basemap else "none",
            "title": use_title,
            "layers": {
                "fnr": {
                    "voc_threshold": use_voc_threshold,
                    "nox_threshold": use_nox_threshold,
                    "display_max": use_display_max,
                    "display_smoothing_sigma": use_smooth or 0,
                    "subtitle": subtitle,
                }
            },
        },
        artifacts={"image": image, "sidecar": sidecar, "data": data_entries},
    )
    created.append(Path(sidecar))
    write_sidecar(payload, sidecar)
    console.print(f"\n[bold green]✓ 已保存:[/bold green] {image}")
