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

    def write_stations(self, hour: str) -> Path:
        path = self.stations / f"{hour}.nc"
        with Dataset(path, "w") as dataset:
            dataset.createDimension("station", len(STATIONS))
            ids = dataset.createVariable("id", str, ("station",))
            for index, (station_id, *_rest) in enumerate(STATIONS):
                ids[index] = station_id
            dataset.createVariable("lon", "f8", ("station",))[:] = [
                row[1] for row in STATIONS
            ]
            dataset.createVariable("lat", "f8", ("station",))[:] = [
                row[2] for row in STATIONS
            ]
            values = np.array([row[3] for row in STATIONS])
            for name in STATION_VARIABLES:
                dataset.createVariable(name, "f8", ("station",))[:] = values
        return path

    def overlay(
        self,
        date: str,
        *options: str,
        station: str | None = "2026010113",
        region: str = "FixtureCity",
    ):
        station_options = (
            () if station is None else ("--station-datetime", station)
        )
        return self.invoke(
            "overlay",
            region,
            date,
            *station_options,
            "--raster-dir",
            str(self.data),
            "--station-dir",
            str(self.stations),
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
