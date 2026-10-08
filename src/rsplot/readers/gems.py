"""GEMS L2 scan readers; UTC archive names and China-time requests.

Daily ``read`` returns concatenated samples for BaseReader compatibility.
Scientific daily means use ``iter_scans`` and equal-scan grid averaging.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import numpy as np
from netCDF4 import Dataset

from rsplot.errors import RsplotError
from rsplot.readers.base import BaseReader, SwathData

# Default target-grid spacing, overridable with --res; not native resolution.
GEMS_DEFAULT_RESOLUTION = 0.05
# Compatibility alias for existing imports; no longer a forced spacing.
GEMS_ANALYSIS_RESOLUTION = GEMS_DEFAULT_RESOLUTION

CHINA_TIME = ZoneInfo("Asia/Shanghai")
EPOCH = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
FILE_RE = re.compile(r"^GK2_GEMS_L2_(\d{8})_(\d{4})_(NO2|HCHO|O3P)_.+\.nc$")


def parse_gems_time(value: str) -> datetime:
    """Parse an exact nominal scan time in Asia/Shanghai."""
    if not value.isdigit() or len(value) != 12:
        raise ValueError("GEMS 扫描时间应为 YYYYMMDDHHMM。")
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").replace(
            tzinfo=CHINA_TIME
        )
    except ValueError as error:
        raise ValueError(f"无效 GEMS 扫描时间: {value}") from error


def match_station_hour(
    scan: str, override: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Match a scan to an hour, or pair a daily mean with an explicit hour."""
    from rsplot.temporal import adapt_hourly_time, parse_yyyymmdd

    if len(scan) == 8:
        parse_yyyymmdd(scan, "GEMS 日均日期")
        if override is None:
            raise ValueError(
                "GEMS 日均叠加需通过 --station-datetime YYYYMMDDHH "
                "显式指定站点时次。"
            )
        hour = adapt_hourly_time(override).input_time.strftime("%Y%m%d%H")
        return hour, {
            "satellite_date": scan,
            "satellite_aggregation": "daily_mean",
            "station_datetime": hour,
            "difference_minutes": None,
            "manual_override": True,
            "reference": "daily_mean_with_explicit_station_hour",
        }

    time = parse_gems_time(scan)
    if override is None:
        station = (time + timedelta(minutes=30)).replace(minute=0)
    else:
        station = adapt_hourly_time(override).input_time
    hour = station.strftime("%Y%m%d%H")
    return hour, {
        "scan_datetime": scan,
        "station_datetime": hour,
        "difference_minutes": (station - time).total_seconds() / 60,
        "manual_override": override is not None,
        "reference": "nominal_scan_time",
    }


@dataclass(frozen=True)
class GemsSpec:
    file_product: str
    value: str
    cloud: str
    scale: float = 1e-15
    profile: bool = False


class GemsReader(BaseReader):
    """Read required fields, filter each scan, and retain provenance."""

    spec: ClassVar[GemsSpec]
    uses_footprints = True
    cloud_fraction_max: float = 0.5

    def discover(
        self, data_dir: str, request: str
    ) -> list[tuple[Path, datetime]]:
        exact = len(request) == 12
        if exact:
            start = parse_gems_time(request).replace(hour=0, minute=0)
        else:
            if len(request) != 8 or not request.isdigit():
                raise ValueError("GEMS 日期应为 YYYYMMDD 或 YYYYMMDDHHMM。")
            try:
                start = datetime.strptime(request, "%Y%m%d").replace(
                    tzinfo=CHINA_TIME
                )
            except ValueError as error:
                raise ValueError(f"无效 GEMS 日期: {request}") from error
        end = start + timedelta(days=1)
        utc_days = {
            start.astimezone(timezone.utc).date(),
            (end - timedelta(microseconds=1)).astimezone(timezone.utc).date(),
        }
        files = []
        for day in sorted(utc_days):
            folder = Path(data_dir) / day.strftime("%Y%m") / day.strftime("%d")
            for path in sorted(folder.glob("GK2_GEMS_L2_*.nc")):
                match = FILE_RE.match(path.name)
                if not match or match[3] != self.spec.file_product:
                    continue
                nominal = datetime.strptime(
                    match[1] + match[2], "%Y%m%d%H%M"
                ).replace(tzinfo=timezone.utc)
                if start <= nominal < end:
                    files.append((path, nominal))
        files.sort(key=lambda item: (item[1], str(item[0])))
        selected = (
            [item for item in files if item[1] == parse_gems_time(request)]
            if exact
            else files
        )
        if not selected:
            available = sorted(
                {
                    time.astimezone(CHINA_TIME).strftime("%Y%m%d%H%M")
                    for _, time in files
                }
            )
            raise RsplotError(
                "data_not_found",
                f"未找到 GEMS {request}；当日可用扫描: "
                + (", ".join(available) or "无"),
                details={"available": available},
            )
        times = [time for _, time in selected]
        if len(set(times)) != len(times):
            raise ValueError(
                "GEMS 同一标称时次存在多个文件，请使用仅含一个版本的数据目录。"
            )
        return selected

    def iter_scans(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> Iterator[SwathData]:
        """Yield empty diagnostic batches for unreadable files as well."""
        for path, nominal in self.discover(data_dir, date):
            try:
                yield self.read_file(path, nominal, extent)
            except (
                OSError,
                ValueError,
                KeyError,
                IndexError,
                AttributeError,
                RuntimeError,
            ) as error:
                empty = np.empty(0, dtype=float)
                yield SwathData(
                    empty,
                    empty,
                    empty,
                    0,
                    1,
                    1,
                    {
                        "file": str(path),
                        "nominal_utc": nominal.isoformat(),
                        "nominal_local": nominal.astimezone(
                            CHINA_TIME
                        ).isoformat(),
                        "error": str(error).splitlines()[0],
                    },
                )

    def read(
        self,
        data_dir: str,
        date: str,
        extent: tuple[float, float, float, float],
        qa_threshold: float = 0.5,
    ) -> SwathData:
        scans = list(self.iter_scans(data_dir, date, extent, qa_threshold))
        valid = [scan for scan in scans if scan.n_pixels]
        if not valid:
            raise ValueError(
                f"GEMS {date} 区域内无有效像元: "
                + str([scan.metadata for scan in scans])
            )
        return SwathData(
            np.concatenate([scan.lon for scan in valid]),
            np.concatenate([scan.lat for scan in valid]),
            np.concatenate([scan.values for scan in valid]),
            sum(scan.n_pixels for scan in scans),
            len(scans),
            sum(scan.n_broken for scan in scans),
            {"scans": [scan.metadata for scan in scans]},
            np.concatenate([scan.corner_lon for scan in valid]),
            np.concatenate([scan.corner_lat for scan in valid]),
        )

    def read_file(
        self,
        path: Path,
        nominal: datetime,
        extent: tuple[float, float, float, float],
    ) -> SwathData:
        spec = self.spec
        geo = "geolocation" if spec.profile else "Geolocation Fields"
        data = "product" if spec.profile else "Data Fields"
        names = (
            (
                "longitude",
                "latitude",
                "solar_zenith_angle",
                "viewing_zenith_angle",
            )
            if spec.profile
            else (
                "Longitude",
                "Latitude",
                "SolarZenithAngle",
                "ViewingZenithAngle",
            )
        )
        flag_path = data + (
            "/final_algorithm_flags"
            if spec.profile
            else "/FinalAlgorithmFlags"
        )
        with Dataset(path) as ds:

            def array(name: str) -> np.ndarray:
                return np.ma.asarray(ds[name][:], dtype=float).filled(np.nan)

            lon, lat, sza, vza = [array(f"{geo}/{name}") for name in names]
            value_var = ds[f"{data}/{spec.value}"]
            units = value_var.getncattr("units")
            expected = "DU" if spec.profile else "molecules cm-2"
            if units != expected:
                raise ValueError(
                    f"{spec.value} 单位不匹配: {units!r}，预期 {expected}"
                )
            value = array(f"{data}/{spec.value}")
            flags = array(flag_path)
            cloud = array(spec.cloud)
            if value.ndim != 2 or any(
                a.shape != value.shape
                for a in (lon, lat, sza, vza, flags, cloud)
            ):
                raise ValueError(
                    "GEMS 经纬度、数值和质量变量必须为同形状二维数组。"
                )
            from rsplot.geo.footprints import (
                inferred_corner_grid,
                pixel_corners,
            )

            valid_geo = (
                np.isfinite(lon)
                & np.isfinite(lat)
                & (np.abs(lon) <= 180)
                & (np.abs(lat) <= 90)
            )
            lon = np.where(valid_geo, lon, np.nan)
            lat = np.where(valid_geo, lat, np.nan)
            if (
                "CornerLongitude" in ds[geo].variables
                and "CornerLatitude" in ds[geo].variables
            ):
                corner_lon = array(f"{geo}/CornerLongitude")
                corner_lat = array(f"{geo}/CornerLatitude")
                footprint_source = "file_corner_coordinates"
            else:
                corner_lon = inferred_corner_grid(lon)
                corner_lat = inferred_corner_grid(lat)
                footprint_source = "estimated_from_unfiltered_native_centers"
            expected_shape = (value.shape[0] + 1, value.shape[1] + 1)
            if (
                corner_lon.shape != expected_shape
                or corner_lat.shape != expected_shape
            ):
                raise ValueError("GEMS 像元角点网格形状不匹配。")
            corner_lon, corner_lat = (
                pixel_corners(corner_lon),
                pixel_corners(corner_lat),
            )
            footprint_valid = (
                np.isfinite(corner_lon).all(axis=-1)
                & np.isfinite(corner_lat).all(axis=-1)
                & (np.abs(corner_lon) <= 180).all(axis=-1)
                & (np.abs(corner_lat) <= 90).all(axis=-1)
            )
            west, east, south, north = extent
            mask = (
                np.isfinite(value)
                & (np.abs(value) < 1e29)
                & np.isfinite(lon)
                & np.isfinite(lat)
                & footprint_valid
                & (corner_lon.max(axis=-1) > west)
                & (corner_lon.min(axis=-1) < east)
                & (corner_lat.max(axis=-1) > south)
                & (corner_lat.min(axis=-1) < north)
                & (np.abs(lon) <= 180)
                & (np.abs(lat) <= 90)
                & (flags == 0)
                & np.isfinite(sza)
                & (sza >= 0)
                & (sza < 70)
                & np.isfinite(vza)
                & (vza >= 0)
                & (vza < 70)
                & np.isfinite(cloud)
                & (cloud >= 0)
                & (cloud <= self.cloud_fraction_max)
            )
            settings = (
                ds if spec.profile else ds["METADATA/ALGORITHM_SETTINGS"]
            )
            version = (
                str(settings.getncattr("product_version"))
                if "product_version" in settings.ncattrs()
                else None
            )
            time_name = f"{geo}/" + ("time" if spec.profile else "Time")
            time = array(time_name)
            time_units = ds[time_name].getncattr("units")
            # NO2 v4 omits the epoch; it uses the GEMS mission epoch.
            known_units = (
                "second",
                "Seconds since 2000-01-01 12 UTC",
                "seconds since 2000-01-01 12:00:00 UTC",
            )
            if time_units not in known_units:
                raise ValueError(f"未知 GEMS 时间单位: {time_units!r}")
            time = time[np.isfinite(time) & (np.abs(time) < 1e12)]
            meta = {
                "file": str(path),
                "product_version": version,
                "variable": f"{data}/{spec.value}",
                "source_unit": units,
                "unit_scale": spec.scale,
                "nominal_utc": nominal.isoformat(),
                "nominal_local": nominal.astimezone(CHINA_TIME).isoformat(),
                "observation_start_utc": (
                    (EPOCH + timedelta(seconds=float(time.min()))).isoformat()
                    if time.size
                    else None
                ),
                "observation_end_utc": (
                    (EPOCH + timedelta(seconds=float(time.max()))).isoformat()
                    if time.size
                    else None
                ),
                "time_epoch": EPOCH.isoformat(),
                "quality": {
                    "flag_variable": flag_path,
                    "accepted_values": [0],
                    "solar_zenith_max_exclusive": 70,
                    "viewing_zenith_max_exclusive": 70,
                    "cloud_variable": spec.cloud,
                    "cloud_fraction_max": self.cloud_fraction_max,
                },
                "n_pixels": int(mask.sum()),
                "footprint_source": footprint_source,
                "footprint_geometry": "native_quadrilateral",
            }
            if not mask.any():
                meta["empty_reason"] = "区域内无通过质量筛选的像元"
            return SwathData(
                lon[mask],
                lat[mask],
                value[mask] * spec.scale,
                int(mask.sum()),
                1,
                0,
                meta,
                corner_lon[mask],
                corner_lat[mask],
            )


class GemsNO2Reader(GemsReader):
    spec = GemsSpec("NO2", "ColumnAmountNO2Trop", "Data Fields/CloudFraction")


class GemsHCHOReader(GemsReader):
    spec = GemsSpec(
        "HCHO", "ColumnAmount", "Data Fields/CloudRadianceFraction"
    )


class GemsO3Reader(GemsReader):
    spec = GemsSpec(
        "O3P",
        "total_ozone_column",
        "support_data/effective_cloud_fraction",
        scale=1.0,
        profile=True,
    )


class GemsO3PRReader(GemsReader):
    spec = GemsSpec(
        "O3P",
        "troposphere_ozone_column",
        "support_data/effective_cloud_fraction",
        scale=1.0,
        profile=True,
    )
