"""Small shared helpers for CLI command services."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


FORECAST_STATION_PAIR: dict[str, str] = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "so2": "SO2",
    "no2": "NO2",
    "co": "CO",
    "o3": "O3",
}


def warn_missing_tianditu_key(
    *,
    basemap: bool | None,
    default_basemap: bool,
    tianditu_key: str | None,
    console: Console,
) -> None:
    """Warn when a requested TianDiTu basemap cannot be loaded."""
    use_basemap = basemap if basemap is not None else default_basemap
    if use_basemap and not tianditu_key:
        console.print(
            "[yellow]未设置天地图 API key，底图将不会加载。请设置 "
            "TIANDITU_API_KEY，或使用 --basemap none。[/yellow]"
        )


def print_failed_dates(
    label: str,
    failed: dict[str, str],
    *,
    console: Console,
    max_items: int = 8,
) -> None:
    """Print a compact failed-date summary for window commands."""
    if not failed:
        return
    console.print(f"  → [yellow]{label} 失败日期示例:[/yellow]")
    items = list(failed.items())
    for date, message in items[:max_items]:
        console.print(f"    - {date}: {message}")
    if len(items) > max_items:
        console.print(f"    ... 另有 {len(items) - max_items} 天")
