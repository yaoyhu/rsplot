"""Real ERA5 and station files for meteo acceptance scenarios."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from overlay_support import OverlayWorkspace

LONS = np.arange(116.5, 118.51, 0.25)
LATS = np.arange(32.5, 30.49, -0.25)  # ERA5 stores latitude descending


class MeteoWorkspace(OverlayWorkspace):
    """An ERA5 archive (UTC days) plus hourly station files.

    Files name the time coordinate `valid_time`, as the real CDS archive
    does; set `time_name` to write the older `time` name instead.
    """

    def __init__(self, root: Path):
        super().__init__(root)
        self.era5 = root / "era5"
        self.era5.mkdir()
        self.time_name = "valid_time"

    def _write(self, path: Path, variable: str, utc: str, value: float, unit):
        path.parent.mkdir(parents=True, exist_ok=True)
        hours = (
            datetime.strptime(utc, "%Y%m%d%H") - datetime(1970, 1, 1)
        ).total_seconds() / 3600
        with Dataset(path, "w") as dataset:
            dataset.createDimension(self.time_name, 1)
            dataset.createDimension("latitude", len(LATS))
            dataset.createDimension("longitude", len(LONS))
            time = dataset.createVariable(
                self.time_name, "f8", (self.time_name,)
            )
            time.units = "hours since 1970-01-01 00:00:00"
            time.calendar = "standard"
            time[:] = [hours]
            dataset.createVariable("latitude", "f8", ("latitude",))[:] = LATS
            dataset.createVariable("longitude", "f8", ("longitude",))[:] = LONS
            field = dataset.createVariable(
                variable, "f4", (self.time_name, "latitude", "longitude")
            )
            field.units = unit
            field[:] = np.full((1, len(LATS), len(LONS)), value)

    def write_temperature(self, utc: str, kelvin: float = 293.15) -> None:
        self._write(self.temperature_path(utc), "t2m", utc, kelvin, "K")

    def temperature_path(self, utc: str) -> Path:
        day = self.era5 / utc[:8] / "single_level"
        return day / "2m_temperature" / "surface.nc"

    def write_wind(self, utc: str, u: float = 3.0, v: float = 4.0) -> None:
        day = self.era5 / utc[:8] / "single_level"
        self._write(
            day / "10m_u_component_of_wind" / "surface.nc",
            "u10",
            utc,
            u,
            "m s**-1",
        )
        self._write(
            day / "10m_v_component_of_wind" / "surface.nc",
            "v10",
            utc,
            v,
            "m s**-1",
        )

    def meteo(self, hour: str, *options: str, region: str = "FixtureCity"):
        return self.invoke(
            "meteo",
            region,
            hour,
            "--dpi",
            "60",
            "--basemap",
            "none",
            "--output",
            str(self.output),
            *options,
        )
