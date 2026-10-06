"""Real files and CLI processes for FNR acceptance scenarios."""

from __future__ import annotations

from raster_support import RasterWorkspace


class FnrWorkspace(RasterWorkspace):
    """NO2 and HCHO swaths in one archive, mapped as an FNR window."""

    def write_days(self, no2: float, hcho: float, days=(1, 2, 3)) -> None:
        for day in days:
            date = f"202601{day:02d}"
            self.write_swath(date, no2, product="no2")
            self.write_swath(date, hcho, product="hcho")

    def fnr(self, end: str, *options: str, region: str = "FixtureCity"):
        return self.invoke(
            "fnr",
            region,
            end,
            "--days",
            "3",
            "--no2-dir",
            str(self.data),
            "--hcho-dir",
            str(self.data),
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
