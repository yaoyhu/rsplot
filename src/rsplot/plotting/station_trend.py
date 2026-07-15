"""Hourly line charts for national monitoring stations and regions."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.ticker import FuncFormatter

from rsplot.readers.guokong import RegionStationSeries, StationSeries

if TYPE_CHECKING:
    from matplotlib.axes import Axes


_DISPLAY_UNITS = {
    "ug/m3": "μg/m³",
    "mg/m3": "mg/m³",
}

_FOCUS_COLORS = (
    "#e6550d",
    "#31a354",
    "#756bb1",
    "#e7298a",
    "#1f9d8a",
    "#6b6ecf",
)


def plot_station_trend(
    series: StationSeries,
    *,
    unit: str,
    threshold: float | None,
    dpi: int,
    output: str,
    title: str | None = None,
) -> None:
    """Plot an hourly station series, preserving NaN gaps."""
    times = [
        datetime.strptime(timestamp, "%Y%m%d%H")
        for timestamp in series.timestamps
    ]
    width = min(16.0, max(10.0, 8.0 + series.n_hours / 96))
    fig, ax = plt.subplots(figsize=(width, 5.4), dpi=dpi)
    try:
        show_markers = series.n_hours <= 72
        ax.plot(
            times,
            series.values,
            color="#1769aa",
            linewidth=1.7,
            marker="o" if show_markers else None,
            markersize=3.5 if show_markers else None,
            label=series.var_name,
        )

        if threshold is not None:
            ax.axhline(
                threshold,
                color="#d62728",
                linestyle="--",
                linewidth=1.2,
                label=f"超标阈值 {threshold:g}",
            )

        _configure_time_axis(ax, times)
        padding = timedelta(minutes=30)
        ax.set_xlim(times[0] - padding, times[-1] + padding)
        display_unit = _DISPLAY_UNITS.get(unit, unit)
        ax.set_ylabel(
            (
                f"{series.var_name} ({display_unit})"
                if display_unit
                else series.var_name
            ),
            fontsize=10,
        )
        ax.set_xlabel("时间", fontsize=10, labelpad=8)
        ax.grid(True, color="#d9d9d9", linewidth=0.7, alpha=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", labelsize=9)

        use_title = title or (f"站点 {series.station_id} · {series.var_name}")
        fig.suptitle(use_title, fontsize=14, y=0.965)
        fig.text(
            0.5,
            0.9,
            (
                f"{series.timestamps[0]}–{series.timestamps[-1]}  ·  "
                f"位置 {series.lon:.3f}°E, {series.lat:.3f}°N  ·  "
                f"有效 {series.n_valid}/{series.n_hours} 小时"
            ),
            ha="center",
            va="center",
            fontsize=9,
            color="#555555",
        )
        ax.legend(loc="best", frameon=False, fontsize=9)
        fig.subplots_adjust(
            left=0.09,
            right=0.98,
            bottom=0.17,
            top=0.84,
        )

        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
    finally:
        plt.close(fig)


def plot_region_station_trend(
    series: RegionStationSeries,
    *,
    region_name: str,
    unit: str,
    threshold: float | None,
    view: str,
    focus_station_ids: list[str],
    dpi: int,
    output: str,
    title: str | None = None,
) -> None:
    """Plot regional station context, mean, and explicit focus stations."""
    times = [
        datetime.strptime(timestamp, "%Y%m%d%H")
        for timestamp in series.timestamps
    ]
    time_values = mdates.date2num(times)
    width = min(16.0, max(10.0, 8.0 + series.n_hours / 96))
    fig, ax = plt.subplots(figsize=(width, 5.8), dpi=dpi)
    try:
        focus_indices = {
            index
            for station_id in focus_station_ids
            if (index := series.station_index(station_id)) is not None
        }
        if view == "lines":
            segments = _background_segments(
                time_values,
                series.values,
                excluded_indices=focus_indices,
            )
            if segments:
                collection = LineCollection(
                    segments,
                    colors="#999999",
                    linewidths=0.55,
                    alpha=0.28,
                    zorder=1,
                    label=f"区域站点 ({series.n_stations})",
                )
                ax.add_collection(collection)

        ax.plot(
            times,
            series.hourly_mean,
            color="#1769aa",
            linewidth=2.2,
            label="区域站点均值",
            zorder=3,
        )

        show_markers = series.n_hours <= 72
        for color_index, station_id in enumerate(focus_station_ids):
            index = series.station_index(station_id)
            if index is None:
                continue
            canonical_id = str(series.station_ids[index])
            values = series.values[index]
            color = _FOCUS_COLORS[color_index % len(_FOCUS_COLORS)]
            ax.plot(
                times,
                values,
                color=color,
                linewidth=1.9,
                marker="o" if show_markers else None,
                markersize=3.2 if show_markers else None,
                label=f"重点站 {canonical_id}",
                zorder=4,
            )
            if threshold is not None:
                exceed = np.isfinite(values) & (values > threshold)
                if exceed.any():
                    ax.scatter(
                        np.asarray(times)[exceed],
                        values[exceed],
                        s=22,
                        facecolor="#d62728",
                        edgecolor="white",
                        linewidth=0.45,
                        zorder=6,
                    )

        if threshold is not None:
            ax.axhline(
                threshold,
                color="#d62728",
                linestyle="--",
                linewidth=1.2,
                label=f"超标阈值 {threshold:g}",
                zorder=2,
            )

        _configure_time_axis(ax, times)
        padding = timedelta(minutes=30)
        ax.set_xlim(times[0] - padding, times[-1] + padding)
        display_unit = _DISPLAY_UNITS.get(unit, unit)
        ax.set_ylabel(
            (
                f"{series.var_name} ({display_unit})"
                if display_unit
                else series.var_name
            ),
            fontsize=10,
        )
        ax.set_xlabel("时间", fontsize=10, labelpad=8)
        ax.grid(True, color="#d9d9d9", linewidth=0.7, alpha=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", labelsize=9)

        use_title = title or f"{region_name} · {series.var_name} 站点趋势"
        fig.suptitle(use_title, fontsize=14, y=0.965)
        hours_with_data = int((series.hourly_valid_counts > 0).sum())
        fig.text(
            0.5,
            0.9,
            (
                f"{series.timestamps[0]}–{series.timestamps[-1]}  ·  "
                f"区域站点 {series.n_stations} 个  ·  "
                f"有效时次 {hours_with_data}/{series.n_hours}"
            ),
            ha="center",
            va="center",
            fontsize=9,
            color="#555555",
        )
        handles, labels = ax.get_legend_handles_labels()
        fig.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.855),
            ncol=min(6, len(labels)),
            frameon=False,
            fontsize=9,
            columnspacing=1.4,
            handlelength=2.4,
        )
        fig.subplots_adjust(
            left=0.09,
            right=0.98,
            bottom=0.17,
            top=0.78,
        )

        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
    finally:
        plt.close(fig)


def _background_segments(
    times: np.ndarray,
    values: np.ndarray,
    *,
    excluded_indices: set[int],
) -> list[np.ndarray]:
    """Build contiguous finite segments for one background collection."""
    segments: list[np.ndarray] = []
    for index, station_values in enumerate(values):
        if index in excluded_indices:
            continue
        finite_indices = np.flatnonzero(np.isfinite(station_values))
        if len(finite_indices) < 2:
            continue
        for run in np.split(
            finite_indices,
            np.flatnonzero(np.diff(finite_indices) > 1) + 1,
        ):
            if len(run) < 2:
                continue
            segments.append(np.column_stack((times[run], station_values[run])))
    return segments


def _configure_time_axis(ax: Axes, times: list[datetime]) -> None:
    """Choose readable ticks without Matplotlib's overlapping offset label."""
    span_hours = (times[-1] - times[0]).total_seconds() / 3600
    if span_hours <= 72:
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=(0, 6, 12, 18)))
        ax.xaxis.set_major_formatter(FuncFormatter(_format_hour_tick))
        return

    if span_hours <= 24 * 14:
        days = max(1, round(span_hours / 24))
        interval = max(1, round(days / 7))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=interval))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        return

    locator = mdates.AutoDateLocator(minticks=5, maxticks=10)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))


def _format_hour_tick(value: float, _position: int | None = None) -> str:
    timestamp = mdates.num2date(value)
    if timestamp.hour == 0:
        return timestamp.strftime("%m-%d\n%H:%M")
    return timestamp.strftime("%H:%M")
