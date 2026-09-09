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

Primary CLI commands are `raster`, `forecast`, `meteo`, `station`,
`trend`, `overlay`, `recent`, and `fnr`.
The `forecast` command can optionally overlay station observations with
`--station-overlay`; its JSON uses `mode` to distinguish pure forecast from
forecast/station overlay output.
The `station` command draws national monitoring-station pollutant maps only.
The `meteo` command is the sole ERA5 wind-map entry point. It draws temperature,
black wind arrows, station observations plus wind, or all three layers. Wind
magnitude is encoded by arrow length and a reference arrow; wind has no
colorbar. Its `DATETIME` is China standard time by default and is converted
internally to the matching ERA5 UTC archive hour. With `--station-var`, an
8-digit date first resolves to the latest station hour, which is then used for
all meteorological layers. `--level` retains the repository-wide
administrative-level meaning.
The `trend` command plots hourly lines over a trailing or explicit date
window. Its default mode targets one station ID; `--region` switches TARGET
to an administrative region and plots grey station lines plus the hourly
regional station mean. `--focus-station` may be repeated to highlight explicit
stations, and `--view mean` hides the grey background lines. Missing hours
remain gaps, and its JSON sidecar records missing/failed files and hourly
values or compact regional summaries.
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
- `src/rsplot/readers/era5.py`: shared ERA5 scalar-grid reader and temperature
  support with China-time to UTC archive matching.
- `src/rsplot/readers/era5_wind.py`: paired U/V ERA5 wind reader using the
  shared temporal and grid-reading helpers.
- `src/rsplot/plotting/station_trend.py`: station and regional hourly trends.
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

`tests/test_gems.py` contains self-contained unittest regressions. Run:

```bash
uv run python -m unittest discover -s tests -p 'test_gems.py' -v
```

Other local tests may be ignored/untracked and require pytest, which is not
currently a project dependency. Do not assume full test discovery is isolated
from local files. If adding pytest-based tests, add the dependency deliberately.

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
- ERA5 files are indexed in UTC. `meteo` input and station hours are fixed to
  `Asia/Shanghai`, and rsplot converts that hour to the matching ERA5 UTC
  archive time.
- Forecast files are grouped as
  `forecast{lead}/{YYYYMMDDHH}_forecast{lead}.nc`, where the filename is the
  UTC initialization time. Forecast input and station hours are fixed to
  `Asia/Shanghai`; rsplot converts the input initialization hour to UTC for
  lookup, adds the lead in UTC, then converts the valid hour back for display
  and station matching.
- Forecast station overlays default the station datetime to the converted local
  `forecast.valid_datetime`. Use `--station-datetime` only when intentionally
  comparing against a different observation hour.

## GEMS Integration

- `raster`, `recent --source raster`, and `overlay` accept `--sensor gems`;
  the default remains TROPOMI. `recent --source` retains raster/station semantics.
  GEMS FNR and satellite trend analysis are outside the current scope.
- Product lookup is `get_product_info(product, sensor="gems")`. Preserve
  `PRODUCT_REGISTRY` and the default lookup for existing TROPOMI callers.
- `readers/gems.py` reads NO2/HCHO from `Data Fields` / `Geolocation Fields`
  and O3P from `product` / `geolocation` / `support_data`. `o3` and `o3pr`
  read total and tropospheric columns from the same O3P archive root.
- Configure `gems_no2`, `gems_hcho`, and `gems_o3`; matching env vars are
  `RSPLOT_DATA_DIR_GEMS_NO2`, `RSPLOT_DATA_DIR_GEMS_HCHO`, and
  `RSPLOT_DATA_DIR_GEMS_O3`. Do not hard-code site paths.
- Archive layout is `YYYYMM/DD/GK2_GEMS_L2_YYYYMMDD_HHMM_*.nc` in UTC.
  GEMS input uses Asia/Shanghai: 12 digits selects an exact nominal scan,
  8 digits requests a daily mean. Daily selection may span UTC month boundaries.
  Missing scans list available times; duplicate nominal times are errors.
- `BaseReader.iter_scans` defaults to one daily batch. GEMS yields each scan
  plus metadata; unreadable files yield empty diagnostic batches. Its `read`
  concatenates raw samples for compatibility, **not** equal-scan daily means.
  Use `temporal.read_scan_mean` for GEMS scientific aggregation, then
  `compute_window_mean` for equal-day means. `--n-min` still counts days.
- Default GEMS filtering uses final flag 0, SZA/VZA < 70°, and product-specific
  cloud measure <= `--cf` (0.5). NO2 flags are bit-encoded in the checked v4
  archive; HCHO/O3P differ. Never synthesize TROPOMI QA scores. Explicit
  `--qa` is rejected for GEMS. Preserve valid negative retrievals.
- GEMS statistics use unfilled/unsmoothed region-masked grids. Display
  smoothing must restore the original valid mask. Preserve source versions,
  variables, cloud definitions, scan counts, failed files, and time provenance
  in sidecars, including daily diagnostics in window and recent outputs.
- GEMS overlay accepts a 12-digit scan and pairs the nearest station hour
  (ties forward, <=30 minutes), with `--station-datetime` as an explicit
  local-hour override. An 8-digit daily mean requires `--station-datetime`;
  label the daily/hourly comparison and set its time difference to null. HCHO requires `--var`. Keep column and surface units
  separate. Existing TROPOMI JSON fields and behavior remain compatible.

## Raster Boundary Display

- `PreparedGrid.values` retains the center-masked statistical grid;
  `unmasked_values` retains the prepared grid before administrative masking.
  Build display arrays with `prepare_display_grid` from the latter, before
  any subsequent statistics preparation replaces the `PreparedGrid`.
- Display selects valid intersecting grid cells and preserves its input valid
  mask during smoothing. `clip_raster_to_region` clips only the colored layer
  to the administrative polygon, with ring orientation normalized before
  projection so holes and islands remain correct.
- Statistics use strictly interior grid centers and equal cell weights;
  boundary centers are excluded. Coverage counts centers, not polygon area.
  Preserve existing product-specific statistical preprocessing, including
  unfilled/unsmoothed GEMS statistics. Never pass a display grid as statistics.
- `raster`, `overlay`, `forecast`, and `reconstruct` sidecars add
  `boundary_policy` (under `raster` for `overlay`). Keep statistics valid when
  only exterior-center cells overlap: zero selected cells, null summaries.
- Run `uv run python -m unittest discover -s tests -p
  'test_boundary_display.py' -v` for boundary and projection regressions.

## GEMS Footprint Remapping

- GEMS `SwathData` includes `(n_pixels, 4)` corner arrays. Prefer the file's
  shared corner grids; otherwise estimate corners from the original 2-D
  geolocation before QA filtering. Preserve missing geolocation. Record
  `footprint_source`; never present estimated corners as official footprints.
- `geo/footprints.py` remaps valid native polygons using overlap areas in
  EPSG:6933. Empty/boundary-touch-only targets stay NaN. Average scans and
  then days with the existing equal-time weighting rules.
- GEMS `raster`, `overlay`, and `recent` remap native footprints directly to
  the globally aligned target spacing selected by `--res`; the default is
  0.05° at every administrative level. There is no fixed intermediate grid.
  This is numerical spacing, not a claimed native satellite resolution.
- Draw the target grid directly, clipping to its valid-cell union AND the
  administrative geometry. Preserve coverage holes during display smoothing.
  Statistics use the unfilled, unsmoothed center-selected target grid and may
  change with `--res`; use identical spacing for comparisons. Smoothing and
  DPI must not change statistics. Subcell gaps remain unresolved.
- Sidecars record the selected spacing for both analysis and display, with
  `display_support` set to `analysis_valid_cells`.
- Preserve separate analysis/display coordinates in result builders and
  record the remapping, resolution, and footprint provenance in JSON.

## Comma-Selected Regions

- Only `raster` and `overlay` call `resolve_regions`; other commands retain
  `resolve_region`. Single inputs delegate unchanged. Lists accept ASCII or
  Chinese commas, strip surrounding whitespace and line breaks, reject empty
  or invalid items, and deduplicate canonical names in first-occurrence order.
- `RegionInfo.members` stores each selected region. `qualified_name` retains
  the canonical city prefix for county/township selections without changing
  the single-region JSON name. Mixed levels use the coarsest member defaults.
- Read/process the combined extent once; clip to the geometric union, keeping
  member boundaries and labels. Multi-region axes use automatic tick counts.
- Combined JSON adds `region.members` and `member_stats`; overlay keeps member
  statistics under each layer. Compute members from the shared statistical
  grid/data, never sum overlapping members for the union total. Empty members
  retain zero counts and null summaries. Keep `spatial_summary` separate.
- Run `uv run python -m unittest discover -s tests -p 'test_multi_regions.py' -v`.
