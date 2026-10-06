"""Real files and CLI processes for station acceptance scenarios."""

from __future__ import annotations

from overlay_support import OverlayWorkspace


class StationWorkspace(OverlayWorkspace):
    """An hourly national-station archive and its CLI invocation."""

    def station(
        self,
        hour: str,
        *options: str,
        var: str = "NO2",
        region: str = "FixtureCity",
    ):
        return self.invoke(
            "station",
            region,
            hour,
            "--var",
            var,
            "--data-dir",
            str(self.stations),
            "--dpi",
            "60",
            "--basemap",
            "none",
            "--output",
            str(self.output),
            *options,
        )
