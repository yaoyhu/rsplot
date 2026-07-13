"""Hourly line charts for a single national monitoring station."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from rsplot.readers.guokong import StationSeries

if TYPE_CHECKING:
    from matplotlib.axes import Axes


_DISPLAY_UNITS = {
    "ug/m3": "μg/m³",
    "mg/m3": "mg/m³",
}


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

        use_title = title or (
            f"站点 {series.station_id} · {series.var_name}"
        )
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
