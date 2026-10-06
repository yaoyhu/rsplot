"""Real files and CLI processes for overlay acceptance scenarios."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from raster_support import RasterWorkspace

# Two stations inside FixtureCity and one in the adjacent EastCity.
STATIONS = (
    ("S001A", 117.3, 31.3, 40.0),
    ("S002A", 117.7, 31.7, 80.0),
    ("S003A", 118.5, 31.5, 999.0),
)
STATION_VARIABLES = ("AQI", "NO2", "O3", "O3_8h_24h")


class OverlayWorkspace(RasterWorkspace):
    """Satellite archive plus an hourly national-station archive."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.stations = root / "stations"
        self.stations.mkdir()

    def write_stations(self, hour: str, stations=STATIONS) -> Path:
        path = self.stations / f"{hour}.nc"
        with Dataset(path, "w") as dataset:
            dataset.createDimension("station", len(stations))
            ids = dataset.createVariable("id", str, ("station",))
            for index, (station_id, *_rest) in enumerate(stations):
                ids[index] = station_id
            dataset.createVariable("lon", "f8", ("station",))[:] = [
                row[1] for row in stations
            ]
            dataset.createVariable("lat", "f8", ("station",))[:] = [
                row[2] for row in stations
            ]
            values = np.array([row[3] for row in stations])
            for name in STATION_VARIABLES:
                dataset.createVariable(name, "f8", ("station",))[:] = values
        return path

    def overlay(
        self,
        date: str,
        *options: str,
        station: str | None = "2026010113",
        station_var: str | None = "NO2",
        region: str = "FixtureCity",
    ):
        station_options = (
            () if station is None else ("--station-datetime", station)
        )
        if station_var is not None:
            station_options += ("--station-var", station_var)
        return self.invoke(
            "overlay",
            region,
            date,
            *station_options,
            "--product",
            "no2",
            "--res",
            "0.25",
            "--dpi",
            "60",
            "--basemap",
            "none",
            "--output",
            str(self.output),
            *options,
        )
