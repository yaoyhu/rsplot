"""Real files and CLI processes for trend acceptance scenarios."""

from __future__ import annotations

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

    def trend(self, target: str, date: str, *options: str):
        return self.invoke(
            "trend",
            target,
            date,
            "--days",
            "1",
            "--var",
            "NO2",
            "--data-dir",
            str(self.stations),
            "--dpi",
            "60",
            "--output",
            str(self.output),
            *options,
        )
