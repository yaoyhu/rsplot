"""Real files and CLI processes for raster acceptance scenarios."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

# Fixture values are in documented display units, not derived from rsplot.
PRODUCTS = {
    "no2": ("NO2____", "nitrogendioxide_tropospheric_column", 60221.4076),
    "hcho": (
        "HCHO___",
        "formaldehyde_tropospheric_vertical_column",
        60221.4076,
    ),
    "o3": ("O3_____", "ozone_total_vertical_column", 60221.4076 / 26.867),
    "o3pr": ("O3__PR_", "ozone_tropospheric_column", 2241.15),
}
# GEMS file token, column variable and cloud variable in "Data Fields".
GEMS_PRODUCTS = {
    "no2": ("NO2", "ColumnAmountNO2Trop", "CloudFraction"),
    "hcho": ("HCHO", "ColumnAmount", "CloudRadianceFraction"),
}


class RasterWorkspace:
    """An isolated on-disk archive, configuration, and output directory."""

    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.data.mkdir()
        self.output = root / "output" / "map.png"
        self.sidecar = self.output.with_suffix(".json")
        boundaries = root / "boundaries"
        boundaries.mkdir()
        for filename, features in (
            ("中国_省.geojson", [self.feature("FixtureProvince", 117, 119)]),
            (
                "中国_市.geojson",
                [
                    self.feature("FixtureCity", 117, 118),
                    self.feature("EastCity", 118, 119),
                ],
            ),
            (
                "中国_县.geojson",
                [
                    self.feature("FixtureCounty", 117, 118),
                    self.feature("EastCounty", 118, 119),
                ],
            ),
        ):
            (boundaries / filename).write_text(
                json.dumps(
                    {"type": "FeatureCollection", "features": features}
                ),
                encoding="utf-8",
            )
        self.boundaries = boundaries
        # Data paths come from configuration only (CLI rule 1): every
        # satellite archive is the fixture `data` folder.
        satellite = ("no2", "o3", "o3pr", "hcho")
        self.data_dirs = {
            **{key: self.data for key in satellite},
            **{f"tropomi_nrti_{key}": self.data for key in satellite},
            **{f"gems_{key}": self.data for key in ("no2", "hcho", "o3")},
            "guokong": root / "stations",
            "era5": root / "era5",
        }
        config = root / "config.toml"
        self.config = config
        self.write_config()
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("RSPLOT_")
            # FORCE_COLOR overrides NO_COLOR and would colour help output.
            and key not in ("TIANDITU_API_KEY", "FORCE_COLOR")
        }
        home = root / "home"
        home.mkdir()
        self.env.update(
            # A private HOME keeps ~/.config/rsplot/config.toml out of the
            # merge; cartopy keeps reading the real shapefile cache.
            HOME=str(home),
            CARTOPY_DATA_DIR=os.environ.get(
                "CARTOPY_DATA_DIR",
                str(Path.home() / ".local" / "share" / "cartopy"),
            ),
            RSPLOT_CONFIG=str(config),
            MPLBACKEND="Agg",
            MPLCONFIGDIR=str(root / "matplotlib"),
            PYTHONDONTWRITEBYTECODE="1",
            NO_COLOR="1",
            COLUMNS="180",
        )

    def write_config(self) -> None:
        """Write the TOML config with the current `data_dirs`."""
        data_dirs = "".join(
            f"{key} = {json.dumps(str(path))}\n"
            for key, path in self.data_dirs.items()
        )
        self.config.write_text(
            "[paths]\n"
            f"geojson_dir = {json.dumps(str(self.boundaries))}\n"
            f"font_dir = {json.dumps(str(self.root / 'fonts'))}\n"
            "[paths.data_dirs]\n"
            f"{data_dirs}"
            "[defaults]\nqa_threshold = 0.5\n",
            encoding="utf-8",
        )

    @staticmethod
    def feature(name: str, west: float, east: float) -> dict:
        return {
            "type": "Feature",
            "properties": {"name": name},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [west, 31],
                        [east, 31],
                        [east, 32],
                        [west, 32],
                        [west, 31],
                    ]
                ],
            },
        }

    def write_swath(
        self,
        date: str,
        value: float,
        *,
        product: str = "no2",
        orbit: int = 1,
        grouped: bool = False,
        nrti: bool = False,
        production: str = "120000",
        qa: float = 1.0,
        cloud: float = 0.1,
        sparse: bool = False,
        outside: bool = False,
        gradient: bool = False,
    ) -> Path:
        token, variable, conversion = PRODUCTS[product]
        stream = "NRTI" if nrti else "OFFL"
        name = (
            f"S5P_{stream}_L2__{token}{date}T040000_{date}T050000_"
            f"{orbit:05d}_03_020600_{date}T{production}.nc"
        )
        path = self.data / name
        lon, lat = np.meshgrid(
            np.arange(117.125, 118, 0.25),
            np.arange(31.125, 32, 0.25),
        )
        if outside:
            lon[:] = 118.875
            lat[:] = 32.875
        # A gradient adds 0, 1, 2, 3 west to east, so smoothing changes it.
        columns = value + (np.arange(4) if gradient else np.zeros(4))
        quality = np.full((4, 4), qa)
        if sparse:
            quality[:] = 0
            quality[0, 0] = qa
        with Dataset(path, "w") as dataset:
            dataset.createDimension("y", 4)
            dataset.createDimension("x", 4)
            dataset.processor_version = "02.06.00"
            dataset.product_version = "fixture"
            core = dataset.createGroup("PRODUCT") if grouped else dataset
            prefix = "" if grouped else "PRODUCT_"
            fields = {
                "longitude": lon,
                "latitude": lat,
                variable: np.tile(columns / conversion, (4, 1)),
                "qa_value": quality,
            }
            for key, values in fields.items():
                core.createVariable(prefix + key, "f8", ("y", "x"))[:] = values
            cloud_group = (
                dataset.createGroup("PRODUCT/SUPPORT_DATA/INPUT_DATA")
                if grouped
                else dataset
            )
            cloud_name = (
                "cloud_fraction_crb"
                if grouped
                else "PRODUCT_cloud_fraction_crb"
            )
            cloud_group.createVariable(cloud_name, "f8", ("y", "x"))[:] = cloud
            if nrti:
                times = core.createVariable(
                    prefix + "delta_time", "i8", ("y",)
                )
                times.units = f"milliseconds since {date[:4]}-{date[4:6]}-{date[6:]}T04:00:00Z"
                times[:] = [0, 1000, 2000, 3000]
                core.createVariable(prefix + "ground_pixel", "i4", ("x",))[
                    :
                ] = [0, 1, 2, 3]
        return path

    def write_blocking_swath(self, date: str) -> Path:
        """A FIFO named like a swath: reading it waits for a writer."""
        path = self.data / (
            f"S5P_OFFL_L2__NO2____{date}T040000_{date}T050000_"
            f"00001_03_020600_{date}T120000.nc"
        )
        os.mkfifo(path)
        return path

    def write_gems_scan(
        self, utc: str, value: float, *, product: str = "no2"
    ) -> None:
        token, variable, cloud = GEMS_PRODUCTS[product]
        folder = self.data / utc[:6] / utc[6:8]
        folder.mkdir(parents=True, exist_ok=True)
        path = (
            folder / f"GK2_GEMS_L2_{utc[:8]}_{utc[8:]}_{token}_FW_DPRO_ORI.nc"
        )
        lon, lat = np.meshgrid(
            np.arange(117.125, 118, 0.25), np.arange(31.125, 32, 0.25)
        )
        nominal = datetime.strptime(utc, "%Y%m%d%H%M").replace(
            tzinfo=timezone.utc
        )
        epoch = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
        with Dataset(path, "w") as dataset:
            dataset.createDimension("y", 4)
            dataset.createDimension("x", 4)
            data = dataset.createGroup("Data Fields")
            geo = dataset.createGroup("Geolocation Fields")
            settings = dataset.createGroup("METADATA/ALGORITHM_SETTINGS")
            settings.product_version = "4.0"
            for name, values in (
                ("Longitude", lon),
                ("Latitude", lat),
                ("SolarZenithAngle", 30),
                ("ViewingZenithAngle", 30),
            ):
                geo.createVariable(name, "f8", ("y", "x"))[:] = values
            column = data.createVariable(variable, "f8", ("y", "x"))
            column.units = "molecules cm-2"
            column[:] = value * 1e15
            data.createVariable("FinalAlgorithmFlags", "i4", ("y", "x"))[:] = 0
            data.createVariable(cloud, "f8", ("y", "x"))[:] = 0.1
            times = geo.createVariable("Time", "f8", ("x",))
            times.units = "seconds since 2000-01-01 12:00:00 UTC"
            times[:] = (nominal - epoch).total_seconds()

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.command(*arguments),
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def start(self, *arguments: str) -> subprocess.Popen:
        """Start rsplot without waiting, for scenarios that interrupt it."""
        return subprocess.Popen(
            self.command(*arguments),
            cwd=self.root,
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def command(self, *arguments: str) -> list[str]:
        command = [str(Path(sys.executable).with_name("rsplot"))]
        coverage_dir = os.environ.get("RSPLOT_E2E_COVERAGE_DIR")
        if coverage_dir:
            self.env["COVERAGE_FILE"] = str(Path(coverage_dir) / ".coverage")
            command = [
                sys.executable,
                "-B",
                "-m",
                "coverage",
                "run",
                "--branch",
                "--parallel-mode",
                "--source=rsplot",
                *command,
            ]
        return [*command, *arguments]

    def raster(
        self, date: str, *options: str, region: str = "FixtureCity"
    ) -> subprocess.CompletedProcess:
        return self.invoke(
            "raster",
            region,
            date,
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

    def payload(self) -> dict:
        return json.loads(self.sidecar.read_text(encoding="utf-8"))


def schema_errors(payload: dict) -> list[str]:
    """Validate a sidecar against the schema shipped inside the package."""
    from jsonschema import Draft202012Validator

    import rsplot

    path = Path(rsplot.__file__).parent / "schemas" / "result.schema.json"
    validator = Draft202012Validator(json.loads(path.read_text("utf-8")))
    return [
        f"{list(error.path)}: {error.message}"
        for error in validator.iter_errors(payload)
    ]


# Every rsplot time is China time, so no output names a time zone: not the
# console, the error line, the sidecar (titles included) or the help text.
ZONE_WORDING = re.compile(
    r"北京时间|中国时间|中国标准时间|\bCST\b|\bUTC\b|_utc\b|Asia/Shanghai"
    r"|\btimezone\b"
)


def zone_wording(result, payload: dict | None = None) -> list[str]:
    """Time-zone words in a run's console output and optional sidecar."""
    text = result.stdout + result.stderr
    if payload is not None:
        text += json.dumps(payload, ensure_ascii=False)
    return sorted(set(ZONE_WORDING.findall(text)))


ERROR_LINE = re.compile(
    r"^rsplot error (?P<code>[a-z_]+)(?: (?P<option>--[a-z0-9-]+))?: "
    r"(?P<rest>.*)$"
)
# Passed as `option` when a scenario does not care which option is named.
ANY_OPTION = object()


def error_line(stderr: str) -> dict:
    """Parse the single `rsplot error <code>[ <option>]: ...` stderr line."""
    lines = [
        line
        for line in stderr.splitlines()
        if line.startswith("rsplot error ")
    ]
    if len(lines) != 1:
        raise AssertionError(
            f"expected one error line, got {lines!r}:\n{stderr}"
        )
    match = ERROR_LINE.match(lines[0])
    if match is None:
        raise AssertionError(f"malformed error line: {lines[0]!r}")
    message, details = match["rest"], {}
    start = message.rfind(" {")
    if start >= 0 and message.endswith("}"):
        details = json.loads(message[start + 1 :])
        message = message[:start]
    return {
        "code": match["code"],
        "option": match["option"],
        "message": message,
        "details": details,
    }


COMMANDS = ("raster", "radius", "overlay", "station", "trend", "meteo", "fnr")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
# Options listed by each command's help, read once per test process.
HELP_OPTIONS: dict[str, set[str]] = {}


def unknown_options(workspace, result) -> list[str]:
    """Options an error line names that its command's help does not list."""
    command = next((arg for arg in result.args if arg in COMMANDS), None)
    if command is None:
        return []
    if command not in HELP_OPTIONS:
        help_text = workspace.invoke(command, "--help").stdout
        HELP_OPTIONS[command] = set(OPTION.findall(help_text))
    named = set(OPTION.findall(result.stderr))
    return sorted(named - HELP_OPTIONS[command])


def assert_failed(
    case,
    workspace,
    result,
    message,
    code,
    option=ANY_OPTION,
    *,
    zone_free=True,
):
    """Check a rejected run: exit 1, one error line, no files left behind.

    ``zone_free=False`` is only for the ERA5 missing-hour error, which keeps
    naming the UTC archive hour it looked for.
    """
    output = result.stdout + result.stderr
    case.assertEqual(result.returncode, 1, output)
    case.assertIn(message, result.stderr)
    error = error_line(result.stderr)
    case.assertEqual(error["code"], code, output)
    case.assertEqual(unknown_options(workspace, result), [], output)
    if zone_free:
        case.assertEqual(zone_wording(result), [], output)
    if option is not ANY_OPTION:
        case.assertEqual(error["option"], option, output)
    folder = workspace.output.parent
    left = sorted(p.name for p in folder.iterdir()) if folder.exists() else []
    case.assertEqual(left, [])
    return error
