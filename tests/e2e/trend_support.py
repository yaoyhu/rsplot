"""Real files and CLI processes for trend acceptance scenarios."""

from __future__ import annotations

from pathlib import Path

from overlay_support import OverlayWorkspace


class TrendWorkspace(OverlayWorkspace):
    """Hourly station files whose values rise by one per hour."""

    def write_hours(self, date: str, hours=range(24)) -> None:
        """S001A = 10 + h and S002A = 20 + h inside; S003A = 999 outside."""
        for hour in hours:
            self.write_stations(
                f"{date}{hour:02d}",
                (
                    ("S001A", 117.3, 31.3, 10.0 + hour),
                    ("S002A", 117.7, 31.7, 20.0 + hour),
                    ("S003A", 118.5, 31.5, 999.0),
                ),
            )

    def set_matplotlib_timezone(self, timezone: str) -> None:
        """Write a matplotlibrc whose date timezone is ``timezone``."""
        config = Path(self.env["MPLCONFIGDIR"])
        config.mkdir(parents=True, exist_ok=True)
        (config / "matplotlibrc").write_text(f"timezone: {timezone}\n")

    def trend(
        self, target: str, date: str, *options: str, days: str | None = "1"
    ):
        window = () if days is None else ("--days", days)
        return self.invoke(
            "trend",
            target,
            date,
            *window,
            "--var",
            "NO2",
            "--dpi",
            "60",
            "--output",
            str(self.output),
            *options,
        )
