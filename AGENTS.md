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

Primary CLI commands are `raster`, `radius`, `forecast`, `meteo`, `station`,
`trend`, `overlay`, `recent`, and `fnr`.
The `forecast` command can optionally overlay station observations with
`--station-overlay`; its JSON uses `mode` to distinguish pure forecast from
forecast/station overlay output.
The `station` command draws national monitoring-station pollutant maps only.
Its datetime argument requires a valid 10-digit `YYYYMMDDHH` in
`Asia/Shanghai`; reject date-only inputs before configuration/data access.
Do not auto-select the latest hour or fall back when that hour is missing.
The shared station reader retains date-only support for other commands.
The `overlay` command's `DATE` selects satellite time exactly as `raster`
does, including date ranges and `--days`/`--n-min` windows; TROPOMI stays
daily. Station observations are one explicit China-time hour: require
`--station-datetime YYYYMMDDHH` for TROPOMI and for GEMS daily/window means.
Only a GEMS 12-digit scan matches the nearest station hour automatically.
Never auto-select the latest station hour. Its satellite layer comes from
`commands.raster.prepare_raster`; do not reintroduce a separate satellite
preparation path. Every overlay sidecar has `time_matching`; TROPOMI and
window requests use `reference=period_mean_with_explicit_station_hour` with a
`satellite_period` (`date_basis` is `filename_start_date_utc` for TROPOMI,
`asia_shanghai_calendar_day` for GEMS windows) and null time difference.
Default station variables are `NO2` for `no2` and `O3_8h_24h` for `o3`,
`o3pr`, and `hcho`; `--var` overrides them.
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
may be left unset; required runtime paths include the
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

### Testing Rules

Review and validate one CLI subcommand at a time. Apply these rules to new
tests and changes to existing tests:

1. **Behavior over implementation.** Assert on user-visible outcomes such as
   exit status, responses, persisted state, rendered images, and JSON files.
   Never assert on internal calls or private functions. Test one behavior per
   test and keep test bodies free of logic.
2. **Scenarios first.** Write acceptance scenarios before implementation,
   using Given/When/Then. Name scenarios `user ...`; use `test_user_...` for
   Python test functions or methods so test discovery still works. Never
   implement first and retrofit tests. For bugs, reproduce the failure in a
   failing test before fixing it.
3. **No mocks.** Do not mock readers, region resolution, plotters, or other
   internals. Use real input files; small isolated fixtures are acceptable.
   Where needed, use real Postgres/Redis, for example via Testcontainers.
   External-system fakes must be verified by contract tests against the real
   system. Use fake clocks and seeded randomness; never use `sleep()`.
4. **Prefer E2E.** Exercise the actual CLI from user input to visible result,
   including generated PNG/JSON outputs where applicable. Use lower-level
   tests only when E2E is impractical, and document why. Tier tests, run only
   affected tests locally, and run the full suite on a schedule.
5. **Coverage last.** Target at least 90% branch coverage. Explain uncovered
   branches, especially failure paths. Do not add filler tests to inflate
   coverage numbers.
6. **Enforce with lint and CI.** Ban mock imports, sleep calls, and focused or
   skipped tests (`.only`/`.skip` and Python equivalents). Enforce test naming.
   CI must fail on coverage drops.

The previous non-E2E suites have been removed. Acceptance scenarios and
subprocess E2E tests live in `tests/e2e/`: `RASTER_SCENARIOS.md` with
`test_raster.py`, and `OVERLAY_SCENARIOS.md` with `test_overlay.py`. Run the
affected suite with:

```bash
uv run python -B -m unittest discover -s tests/e2e -p 'test_raster.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_overlay.py' -v
```

`overlay` and `radius` reuse `prepare_raster`, so changes to it must pass
both the raster and overlay suites.

These tests use temporary NetCDF/GeoJSON/TOML files and real PNG/JSON output.
They do not require configured satellite data or network basemaps. Test lint,
coverage gates, and scheduled full-suite CI still need to be configured.

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
  label the daily/hourly comparison and set its time difference to null.
  Keep column and surface units separate. Existing JSON fields remain
  compatible.

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
  TROPOMI statistical smoothing may change values but must restore the
  pre-smoothing valid mask in single-day and window modes; smoothing must
  never create valid cells or change coverage.
- `raster`, `overlay`, `forecast`, and `reconstruct` sidecars add
  `boundary_policy` (under `raster` for `overlay`). Keep statistics valid when
  only exterior-center cells overlap: zero selected cells, null summaries.

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

## Station Radius Maps

- `radius STATION_ID DATE --km KM` uses `commands.raster.prepare_raster`
  and the existing raster/overlay renderers. Keep administrative `raster`
  behavior unchanged when modifying the shared preparation path.
- `geo/radius.py` builds squares in station-centered WGS84 AEQD meters.
  `--km` is the distance from the center to each side; side length is 2 × km.
  Select stations by their projected x/y offsets, including square corners,
  not by radial distance. `RegionInfo.projection_center` keeps the default
  map square and centered. Its axes fit the square exactly, with no exterior
  padding or extra dashed outline; keep edge-station labels inside the frame.
  `geometry_kind=station_radius` identifies the
  non-administrative area; administrative context must not clip the square.
  JSON records `radius.shape=square` and `radius.side_length_km`.
- `--station-var` is optional. Locations-only mode uses
  `read_station_locations` and requires no pollutant field. Coordinates
  and observations in variable mode come from the same station hour.
- Station observations are always one concrete China-time hour, never a
  temporal mean. Daily/window satellite requests with a station variable
  require `--station-datetime YYYYMMDDHH`. GEMS scans reuse nominal nearest
  hour matching (ties forward); explicit overrides remain supported.
- Use the same markers for center and other stations, retaining hollow
  markers for missing values. Do not add a center ring or lower-right legend.
  Keep satellite and station units/colorbars separate. Daily/window versus hourly time
  differences are null; titles identify both time bases.
- Radius JSON retains raster provenance and adds radius, administrative
  context, time matching, and station rows. Empty center-selected grids
  retain zero counts and null summaries even when intersecting cells display.
