"""Real files and CLI processes for recent acceptance scenarios."""

from __future__ import annotations

from pathlib import Path

from overlay_support import OverlayWorkspace


class RecentWorkspace(OverlayWorkspace):
    """Daily satellite and station archives summarized as JSON."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.output = root / "output" / "recent.json"
        self.sidecar = self.output

    def write_station_day(self, date: str, offset: float) -> None:
        """At 13:00, S001A = 40 + offset and S002A = 80 + offset inside."""
        self.write_stations(
            f"{date}13",
            (
                ("S001A", 117.3, 31.3, 40.0 + offset),
                ("S002A", 117.7, 31.7, 80.0 + offset),
                ("S003A", 118.5, 31.5, 999.0),
            ),
        )

    def recent(self, end: str, *options: str, source: str = "raster"):
        return self.invoke(
            "recent",
            "FixtureCity",
            end,
            "--days",
            "3",
            "--source",
            source,
            "--output",
            str(self.output),
            *options,
        )

    def raster_recent(self, end: str, *options: str):
        return self.recent(end, "--product", "no2", "--res", "0.25", *options)

    def station_recent(self, end: str, *options: str):
        return self.recent(end, "--var", "NO2", *options, source="station")
