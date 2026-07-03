# AGENTS.md

Guidance for future coding agents working in this repository.

## Project Overview

`rsplot` is a Python CLI package for plotting remote-sensing and air-quality
data. It is designed for agent workflows: plotting commands produce human
readable console output plus machine-readable JSON sidecars next to generated
images.

The package uses a `src/` layout and exposes the console command:

```bash
rsplot = rsplot.__main__:app
```

Primary CLI commands are `raster`, `forecast`, `station`, `overlay`,
`recent`, and `fnr`.
The `station` command can optionally overlay ERA5 horizontal wind vectors with
`--wind-level`.
The `recent` command writes JSON only; the other plotting commands write a PNG
and a same-basename `.json` sidecar.

## Repository Layout

- `pyproject.toml`: package metadata, runtime dependencies, CLI entry point,
  Ruff configuration, and pytest `testpaths`.
- `uv.lock`: lockfile managed by `uv`; do not hand-edit it.
- `README.md`: user installation/configuration examples and CLI usage.
- `config.example.toml`: safe placeholder config for local path setup.
- `src/rsplot/__main__.py`: imports and runs the Typer app.
- `src/rsplot/cli.py`: Typer command definitions and command orchestration.
- `src/rsplot/config.py`: safe path defaults, config loading, level defaults,
  key regions, AQ limits, and station variable metadata.
- `src/rsplot/readers/`: TROPOMI and station data readers.
- `src/rsplot/readers/era5_wind.py`: paired U/V ERA5 wind reader with station
  timezone to ERA5 UTC conversion.
- `src/rsplot/readers/forecast.py`: gridded air-quality forecast reader for
  `forecast6/12/24/48/72` NetCDF files.
- `src/rsplot/readers/__init__.py`: product registry and plotting defaults for
  `no2`, `o3`, `o3pr`, and `hcho`.
- `src/rsplot/geo/`: administrative boundary resolution and gridding helpers.
- `src/rsplot/plotting/`: Matplotlib/Cartopy renderers, styles, and colormaps.
- `src/rsplot/fnr.py`: FNR window parsing, window means, FNR computation, and
  regime classification helpers.
- `src/rsplot/recent.py`: read-only recent-day JSON summaries.
- `src/rsplot/results.py`: structured JSON sidecar builders and emitters.
- `src/rsplot/tiles/tianditu.py`: TianDiTu tile provider for Cartopy.
- `logs/`, `dist/`, `.venv/`, `.ruff_cache/`: local/generated artifacts.

## Setup Commands

Use `uv` for local development:

```bash
uv sync
uv run rsplot --help
```

The package requires Python `>=3.10,<3.14`. The geospatial stack includes
Cartopy, GeoPandas, Shapely, xarray, SciPy, Astropy, Matplotlib, and NetCDF4.

Most real commands require external data paths. Runtime paths are intentionally
not hard-coded in `src/rsplot/config.py`; use `~/.config/rsplot/config.toml`,
`RSPLOT_CONFIG`, environment variables, or CLI directory options.

Create a local config from the example. Optional paths such as `font_dir`
and `hcho_cmap_file` may be left unset; required runtime paths include the
GeoJSON boundary directory and whichever product data directories a command
uses.


```bash
mkdir -p ~/.config/rsplot
cp config.example.toml ~/.config/rsplot/config.toml
```

Useful environment variables:

```bash
export RSPLOT_CONFIG="/path/to/rsplot.toml"
export TIANDITU_API_KEY="your-key"        # optional satellite basemap
export RSPLOT_GEOJSON_DIR="/path/to/geojson"
export RSPLOT_FONT_DIR="/path/to/fonts"
export RSPLOT_DATA_DIR_NO2="/path/to/no2"
export RSPLOT_DATA_DIR_O3="/path/to/o3"
export RSPLOT_DATA_DIR_O3PR="/path/to/o3pr"
export RSPLOT_DATA_DIR_HCHO="/path/to/hcho"
export RSPLOT_DATA_DIR_GUOKONG="/path/to/guokong"
export RSPLOT_DATA_DIR_ERA5="/path/to/era5"
export RSPLOT_DATA_DIR_FORECAST="/path/to/forecast"
export RSPLOT_HCHO_CMAP_FILE="/path/to/256x3_rgb_table.txt"
```

The boundary resolver expects province, city, and county GeoJSON files in the
configured GeoJSON directory with the filenames used by
`src/rsplot/geo/boundaries.py`.

If no TianDiTu key is available, use `--basemap none` for commands that would
otherwise request satellite tiles.

## Validation Commands

Basic import/CLI smoke checks that do not require data:

```bash
uv run rsplot --help
uv run python -c "from rsplot.cli import app; print(app.info.name)"
```

Ruff is configured with `fix = true` in `pyproject.toml`, so plain
`uv run ruff check .` mutates files. Use `--no-fix` unless you explicitly mean
to apply lint fixes:

```bash
uv run ruff check --no-fix .
uv run ruff format --check .
```

Current repository state has pre-existing Ruff lint/format failures. Do not
silently reformat or lint-fix broad application code during unrelated work.
For focused changes, check the touched files with `--no-fix` and document any
unrelated existing failures.

There is no committed `tests/` directory, and `pytest` is not currently a
project dependency. `uv run python -m pytest` currently fails with
`No module named pytest`. If adding tests, add the test dependency deliberately
and then run pytest against `tests/`.

Package build command when needed:

```bash
uv build
```

This writes generated artifacts under `dist/`; do not hand-edit them.

## Coding Conventions

- Follow the existing Python style: type hints, dataclasses for structured
  payloads, small helper functions, and 79-character line length.
- Prefer existing project abstractions over new ones: `AppConfig`,
  `RegionInfo`, `ProductInfo`, `SwathData`, `StationData`, and result-builder
  functions.
- Keep CLI commands as orchestration layers. Data reading belongs in
  `readers/`, gridding/masking in `geo/`, plotting in `plotting/`, and JSON
  payload construction in `results.py` or `recent.py`.
- Preserve lazy imports inside CLI command bodies unless there is a concrete
  reason to change startup behavior.
- User-facing CLI text is largely Chinese. Keep existing tone and error style:
  print concise Rich messages and exit with `typer.Exit(1)` on expected input
  or data errors.
- The machine contract is the JSON sidecar, not stdout. When adding or changing
  command behavior, update the relevant result builder and preserve backward
  compatible aliases where they already exist.
- New satellite products should implement `BaseReader.read`, return
  `SwathData` in display units, and be registered in `PRODUCT_REGISTRY`.
  Update data-dir defaults, CLI help, and overlay station pairing if relevant.
- Readers should perform QA, spatial, finite-value filtering, and unit
  conversion. Reuse `read_tropomi_product_arrays` for TROPOMI files so both
  flattened and `/PRODUCT` group layouts remain supported.
- Plotters should accept already prepared arrays/data objects and `RegionInfo`;
  they should not read source data. Keep Cartopy transforms explicit and close
  figures after saving.
- For FNR, preserve the scientific masking rules: mean NO2 and HCHO are
  computed separately over the window, FNR is divided afterward, and smoothing
  must not create new valid FNR pixels.

## Files And Paths To Avoid Modifying

- Do not modify application code for documentation-only tasks.
- Do not hand-edit `uv.lock`; use `uv add`, `uv remove`, or `uv lock` for
  dependency changes.
- Do not edit `dist/`, `logs/`, `.venv/`, `.ruff_cache/`, or `__pycache__/`.
  They are generated or local artifacts.
- Do not change `LICENSE`.
- Do not add site-specific default data paths or change air-quality standard
  constants just to make a local run pass. Use env vars or config overrides.
- Do not write to configured external data directories such as satellite,
  GuoKong, GeoJSON, font, or colormap locations.

## Important Gotchas

- `src/rsplot/__init__.py` has a `__version__`, but the CLI `--version` uses
  package metadata via `importlib.metadata.version("rsplot")`.
- Region resolution loads and caches GeoJSON through `functools.lru_cache`;
  tests that change `RSPLOT_GEOJSON_DIR` may need cache clearing or separate
  processes.
- `emit_result()` writes `{image_path with .json suffix}`. Ensure output
  directories exist before emitting sidecars if adding new commands.
- `recent` writes its JSON path directly via `write_recent_result()` and sets
  `"image": null` in the payload.
- Many CLI commands use `/tmp/...` default outputs when `--output` is omitted.
  Prefer explicit `--output` paths in examples, tests, and agent workflows.
- ERA5 files are indexed in UTC, while station filenames default to
  `Asia/Shanghai` for wind matching. Use `--station-timezone` when a station
  archive follows a different convention.
- Forecast files are grouped as
  `forecast{lead}/{YYYYMMDDHH}_forecast{lead}.nc`, where the filename time is
  treated as initialization time and `valid_datetime = init + lead hours`.
