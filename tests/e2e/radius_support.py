"""Real files and CLI processes for radius acceptance scenarios."""

from __future__ import annotations

from overlay_support import OverlayWorkspace

# A centre station, a neighbour about 7 km away, and one about 60 km away.
RADIUS_STATIONS = (
    ("C001A", 117.5, 31.5, 40.0),
    ("N002A", 117.55, 31.55, 80.0),
    ("F003A", 117.9, 31.9, 999.0),
)


class RadiusWorkspace(OverlayWorkspace):
    """Satellite and station archives for station-centred square maps."""

    def write_radius_stations(self, hour: str):
        return self.write_stations(hour, RADIUS_STATIONS)

    def radius(
        self,
        date: str,
        *options: str,
        station_id: str = "C001A",
        km: str = "20",
    ):
        return self.invoke(
            "radius",
            station_id,
            date,
            "--km",
            km,
            "--data-dir",
            str(self.data),
            "--station-data-dir",
            str(self.stations),
            "--product",
            "no2",
            "--res",
            "0.25",
            "--smooth",
            "0",
            "--dpi",
            "60",
            "--basemap",
            "none",
            "--output",
            str(self.output),
            *options,
        )
