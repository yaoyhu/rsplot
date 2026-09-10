# rsplot

`rsplot` is an Agent-oriented command-line tool for plotting remote-sensing,
reconstructed, and air-quality data. It provides a small, stable CLI surface for
[tianpu-agent](https://git.lug.ustc.edu.cn/yaoyhu/tianpu-agent).


## Installation

Run directly with `uvx`:

```bash
uvx rsplot --help
```

Or install it in a project environment:

```bash
uv add rsplot
uv run rsplot --help
```

### Development releases

Every push to `main` publishes a PEP 440 development release such as
`0.3.1.dev4`. Stable installs continue to ignore these releases. To follow the
latest development build, opt in once:

```bash
uv tool install rsplot --prerelease allow
uv tool upgrade rsplot
```

The prerelease setting is retained by later `uv tool upgrade` commands.

For local development:

```bash
git clone https://github.com/yaoyhu/rsplot.git
cd rsplot
uv sync
uv run rsplot --help
```

## Configuration

Satellite HCHO, O3, and O3PR use the bundled `colormap_22.txt` by
default; NO2 uses the built-in nine-color gradient. These defaults apply to
both TROPOMI and GEMS. Use `--cmap` to select another registered colormap.

`rsplot` does not ship site-specific data paths. Configure local satellite,
station, boundary, and font paths with a TOML file:

```bash
mkdir -p ~/.config/rsplot
cp config.example.toml ~/.config/rsplot/config.toml
```

Then edit `~/.config/rsplot/config.toml`:

```toml
[paths]
geojson_dir = "/path/to/geojson"
font_dir = "/path/to/fonts"

[paths.data_dirs]
no2 = "/path/to/NO2"
o3 = "/path/to/O3"
o3pr = "/path/to/O3PR"
hcho = "/path/to/HCHO"
guokong = "/path/to/guokong_combine"
era5 = "/path/to/era5"
forecast = "/path/to/forecast"
reconstruct = "/path/to/reconstruct"

# Optional lower-level boundary override for a direct-administered city.
# [subdivision_overrides."中山市"]
# path = "/path/to/中山市镇街界线.shp"
# name_field = "镇街名称"
# level = "township"

# Optional satellite basemap key. Leave commented unless you have a real key.
# [tianditu]
# api_key = "your-real-key"
```

You can also point to a different config file:

```bash
export RSPLOT_CONFIG="/path/to/rsplot.toml"
```

Environment variables override TOML values:

```bash
export TIANDITU_API_KEY="your-key"
export RSPLOT_GEOJSON_DIR="/path/to/geojson"
export RSPLOT_FONT_DIR="/path/to/fonts"
export RSPLOT_DATA_DIR_NO2="/path/to/NO2"
export RSPLOT_DATA_DIR_O3="/path/to/O3"
export RSPLOT_DATA_DIR_O3PR="/path/to/O3PR"
export RSPLOT_DATA_DIR_HCHO="/path/to/HCHO"
export RSPLOT_DATA_DIR_GUOKONG="/path/to/guokong_combine"
export RSPLOT_DATA_DIR_ERA5="/path/to/era5"
export RSPLOT_DATA_DIR_FORECAST="/path/to/forecast"
export RSPLOT_DATA_DIR_RECONSTRUCT="/path/to/reconstruct"
```

Command-line directory options, such as `--data-dir`, take precedence for the
command being run. If no TianDiTu API key is configured, use `--basemap none`
to avoid requesting satellite tiles.

City subdivision overrides replace the county layer only for the configured
city. Their source CRS is converted to the CRS of the standard city boundary.
This lets direct-administered towns or streets appear in maps and spatial
summaries, and makes qualified inputs such as `中山/板芙` resolvable.

## Usage

The examples below assume data paths are configured and readable.

```bash
# Show available commands and options.
rsplot --help

# Plot a single-day TROPOMI raster.
rsplot raster 合肥 20260115 -p no2 -o ./logs/hcho/raster_city_jiujiang_hcho.png

# Plot a 30-day TROPOMI window mean.
rsplot raster 安徽 20260131 -p hcho --days 30 -o hcho_anhui_202601.png

# Plot a TROPOMI ozone-profile tropospheric column raster.
rsplot raster 安徽 20260227 -p o3pr -o o3pr_anhui_20260227.png

# Plot an explicit TROPOMI date range.
rsplot raster 长三角 20260101-20260131 -p no2 -o no2_yrd_202601.png

# Reconstructed-grid input is China standard time; rsplot converts it to the
# matching UTC archive filename. This reads 2026051100.nc.
rsplot reconstruct 安徽 2026051108 --var PM2.5 \
  -o reconstruct_anhui_pm25.png

# Date-only input selects the latest complete hour in that China-time day.
rsplot reconstruct 合肥 20260511 --var O3 --res 0.01 \
  -o reconstruct_hefei_o3.png

# Forecast input is China standard time; rsplot converts it
# to the matching UTC archive initialization hour before reading.
rsplot forecast 安徽 2026063000 --lead 24 --var O3 -o forecast_anhui_o3.png

# Date-only input selects the latest initialization within that China-time day.
rsplot forecast 合肥 20260630 --lead 72 --var PM2.5 -o forecast_hefei_pm25.png

# Overlay station observations on the forecast valid time.
rsplot forecast 合肥 2026041409 --lead 6 --var O3 --station-overlay -o forecast_station_hefei_o3.png

# Plot ERA5 2 m temperature. Input hours are China standard time; rsplot
# converts them to the matching UTC archive day and hour automatically.
rsplot meteo 南京 2026051115 --temp-level 2m -o meteo_nanjing_t2m.png

# Plot black 850 hPa wind arrows; length represents speed and no wind
# colorbar is drawn. The reference arrow gives the speed scale.
rsplot meteo 南京 2026051115 --wind-level 850 -o meteo_nanjing_wind850.png

# Overlay black wind arrows on a temperature background. Only the temperature
# colorbar is drawn.
rsplot meteo 南京 2026051115 --temp-level 850 \
  --wind-level 850 -o meteo_nanjing_t850_wind850.png

# Overlay station observations with black wind arrows.
rsplot meteo 南京 2026051115 --station-var O3 \
  --wind-level 850 -o meteo_nanjing_o3_wind850.png

# Temperature, stations, and wind can be combined. The two colorbars describe
# temperature and station concentration; wind magnitude is encoded by length.
rsplot meteo 南京 2026051115 --temp-level 850 --station-var O3 \
  --wind-level 850 -o meteo_nanjing_t850_o3_wind850.png

# Plot national monitoring station observations.
rsplot station 合肥 2026041415 --var O3 -o station_hefei_o3.png

# Plot one station's hourly observations over the latest seven days.
rsplot trend 3347A 20260520 --days 7 --var O3 -o trend_3347A_o3_7d.png

# A single day and an explicit date range are also supported.
rsplot trend 3347A 20260520 --days 1 --var O3 -o trend_3347A_o3_day.png
rsplot trend 3347A 20260501-20260507 --var PM2.5 -o trend_3347A_pm25.png

# Plot all regional stations as grey lines plus the hourly station mean.
rsplot trend 重庆 20260520 --days 7 --var O3 --region -o trend_chongqing_o3.png

# Plot only the regional mean and highlight one or more explicit stations.
rsplot trend 重庆 20260520 --days 7 --var O3 --region --view mean \
  --focus-station 3347A --threshold 200 -o trend_chongqing_focus.png

# Overlay satellite raster data and station observations.
rsplot overlay 合肥 2026041415 -p no2 --var NO2 -o overlay_hefei_no2.png

# Plot an FNR regime map with the default 7-day window.
rsplot fnr 合肥 20260114 -o fnr_hefei.png

# Plot an FNR regime map with an explicit date range.
rsplot fnr 长三角 20260101-20260130 -o fnr_yrd_202601.png

# Override FNR regime thresholds for agent-driven sensitivity tests.
rsplot fnr 合肥 20260114 --voc-threshold 0.8 --nox-threshold 1.8 --display-max 5 -o fnr_hefei_sensitivity.png
```

When `-o/--output` is provided, `rsplot` writes the image to that path and also
writes a JSON sidecar with the same base name. Reconstructed-grid JSON records
both the China-time input and matched UTC archive hour, source file, native and
output resolution, regional statistics, administrative summaries, and hotspots.

## Select multiple regions without configuration

`raster` and `overlay` accept a quoted, comma-separated region argument.
Use English or Chinese commas; surrounding whitespace and embedded line
breaks are ignored in a list. Province, city, and qualified county/township
names can be mixed. County and township names still require their city,
e.g. `中山市/东区街道`. Other commands retain their single-region input.

```bash
# One map covering three selected townships.
uv run rsplot raster \
  "中山市/东区街道,中山市/南区街道,中山市/石岐街道" 20260907 \
  --sensor gems -p o3pr --cf 1 --res 0.075 --smooth 0 \
  --basemap none -o ./logs/zhongshan/three_streets_raster.png

# The same daily satellite field with observations at 19:00 China time.
uv run rsplot overlay \
  "中山市/东区街道,中山市/南区街道,中山市/石岐街道" 20260907 \
  --sensor gems -p o3pr --station-datetime 2026090719 \
  --cf 1 --res 0.075 --smooth 0 --basemap none \
  -o ./logs/zhongshan/three_streets_overlay.png
```

These examples use your existing product/station data paths. Optional
`--data-dir` for raster or `--raster-dir` for overlay overrides the satellite
root; no named region group needs to be added to configuration.

Every member is resolved before reading data. Repeated aliases are removed
in first-occurrence order; empty items and unknown names fail with an explicit
error instead of silently omitting regions. The map reads and processes the
combined extent once, but colors only the union of the selected geometries,
preserving holes and gaps between disconnected regions. Each member retains
its boundary and label. Defaults use the coarsest selected level; combined
maps use automatic geographic ticks. Explicit plot options still take
precedence. Far-apart selections share one map with intervening whitespace.

Combined maps use `联合区域（N个）` as their default name. The JSON adds
`region.members` with canonical qualified names, administrative levels and
extents. Existing overall statistics operate on the geometric union, without
double-counting parent/child overlaps. `member_stats` summarizes each selected
member using that same statistical grid; for overlay these lists are under
`raster.member_stats` and `station.member_stats`. A member with no valid data
remains in the list with zero valid counts and null numeric summaries.
Members may overlap, so their counts must not be added to recover the union
count. Grid centers exactly on a member boundary are excluded from that
member's statistics, even if they lie inside the combined region. Station
selection retains the existing boundary-tolerance rule. `spatial_summary`
continues to describe subdivisions, independently of selected-member stats.
Single-region inputs retain their existing output contract.

Run the isolated multi-region regressions:

```bash
uv run python -m unittest discover -s tests -p 'test_multi_regions.py' -v
```

## Raster boundaries and regional statistics

`raster`, `overlay`, `forecast` (including station overlays), and
`reconstruct` prepare separate display and statistics grids:

- **Display:** retain valid grid cells that intersect the administrative
  geometry, even when their centers are outside. Clip the colored layer to
  the actual boundary, including holes and disconnected islands. Display
  smoothing uses surrounding values but preserves the input valid-cell mask.
- **Statistics:** select grid centers **strictly inside** the geometry;
  centers exactly on the boundary are excluded. Each valid selected cell has
  equal weight. Coverage is the valid selected-cell count divided by the
  total selected-cell count, not the percentage of colored land area.
  Existing product-specific gap-filling and statistical smoothing behavior
  remains unchanged; GEMS statistics remain unfilled and unsmoothed.

The PNG sidecar adds `boundary_policy` with the selection and weighting
rules, the displayed intersecting-cell count, and the count whose centers
are outside. For `overlay`, this block is nested under `raster`.
A small region can display overlapping cells while having no interior grid
centers: its statistics then report zero valid cells and null summaries.
This change does not increase the satellite's native resolution or fill
missing observations.

Run boundary-selection and actual rendering regressions (including holes
and both PlateCarree and Mercator projections):

```bash
uv run python -m unittest discover -s tests -p 'test_boundary_display.py' -v
```

## GEMS satellite products

Use `--sensor gems` with `raster`, `recent`, and `overlay`. Omitting
`--sensor` retains TROPOMI behavior. GEMS FNR and satellite trend curves are
not included in this release.

Configure the three archive roots in `[paths.data_dirs]`:

```toml
gems_no2 = "/path/to/GEMS/NO2"
gems_hcho = "/path/to/GEMS/HCHO"
gems_o3 = "/path/to/GEMS/O3"
```

Alternatively set `RSPLOT_DATA_DIR_GEMS_NO2`, `RSPLOT_DATA_DIR_GEMS_HCHO`,
and `RSPLOT_DATA_DIR_GEMS_O3`. Each root contains `YYYYMM/DD/*.nc`.
`--data-dir` (`--raster-dir` for overlay) overrides the configured root.

| Product | GEMS variable | Display unit |
| --- | --- | --- |
| `no2` | `Data Fields/ColumnAmountNO2Trop` | 10¹⁵ molecules/cm² |
| `hcho` | `Data Fields/ColumnAmount` | 10¹⁵ molecules/cm² |
| `o3` | `product/total_ozone_column` | DU |
| `o3pr` | `product/troposphere_ozone_column` | DU |

Both ozone quantities use the O3P files in `gems_o3`; `o3pr` reads the
provided tropospheric column without reintegrating the profile. Neither
quantity represents surface ozone concentration.

GEMS dates and scan requests use **Asia/Shanghai**. `YYYYMMDDHHMM` selects
an exact nominal scan; `YYYYMMDD` computes the day's valid-scan mean.
For example, `202609010845` selects the `20260901_0045` UTC archive scan.
The filename is the nominal scan time, not a simultaneous observation time
for every pixel: GEMS scans begin at :45 UTC and take about 30 minutes
([NESC operation schedule](https://nesc.nier.go.kr/en/html/satellite/operation.do)).
Missing scan requests report available local times instead of selecting a
replacement. Duplicate files for one nominal scan are rejected; use a root
containing one archive version.

```bash
# Exact scan, daily mean, and multi-day mean.
rsplot raster 安徽 202609011145 --sensor gems -p no2 \
  --basemap none --output /tmp/gems_no2_scan.png
rsplot raster 安徽 20260901 --sensor gems -p hcho \
  --basemap none --output /tmp/gems_hcho_daily.png
rsplot raster 安徽 20260901-20260902 --sensor gems -p o3pr \
  --basemap none --output /tmp/gems_o3pr_window.png

# Recent daily regional statistics (JSON only).
rsplot recent 安徽 20260902 --days 2 --source raster --sensor gems -p no2 \
  --output /tmp/gems_no2_recent.json

# 11:45 China-time scan with observations at the nearest hour, 12:00.
rsplot overlay 安徽 202609011145 --sensor gems -p no2 \
  --basemap none --output /tmp/gems_no2_overlay.png
# Use --station-datetime YYYYMMDDHH for an intentional time override.
```

Each scan is first remapped by pixel/target overlap area in the equal-area
EPSG:6933 projection, directly onto a **globally aligned target grid selected
by `--res`**. GEMS defaults to 0.05° at every administrative level. This is
numerical grid spacing, not native satellite resolution; finer grids cannot
recover variation within a native pixel. Daily means
weight valid scans equally at each grid cell; multi-day means then weight
valid days equally. A daily cell needs at least one valid scan. Window `--n-min`
continues to count **days**, using the existing product defaults, and is not
available for a single scan. These are means of available daytime scans,
not full 24-hour means. Empty scans and failed files do not contribute zeros.

For GEMS `raster`, `overlay`, and `recent`, **`--res` controls the actual
analysis grid**. No fixed 0.05° intermediate grid is used. Raster and overlay
draw that grid directly, clipped to its valid-cell union and the administrative
boundary. Changing `--res` may change grid-center selection, coverage, and
regional statistics; use the same spacing for comparisons. `--smooth` affects
display only and preserves the target grid's valid mask; statistics remain
unfilled and unsmoothed. DPI and map graticules are independent of grid spacing.
TROPOMI keeps its existing resolution behavior.

For example, compare Zhongshan O3PR at two target spacings without smoothing:

```bash
rsplot raster 中山市 20260907 --sensor gems -p o3pr --cf 1 \
  --res 0.05 --smooth 0 --basemap none --output /tmp/gems_o3pr_res005.png
rsplot raster 中山市 20260907 --sensor gems -p o3pr --cf 1 \
  --res 0.01 --smooth 0 --basemap none --output /tmp/gems_o3pr_res001.png
```

When available, GEMS pixel boundaries use file `CornerLongitude` and
`CornerLatitude` arrays. The checked O3P and NO2 files have centers only;
their quadrilateral boundaries are **estimates from adjacent unfiltered
native centers**, with linear extrapolation at the outer scan edge. Missing
geolocation is not interpolated, and rejected retrievals do not contribute
values. This is not a recovery of official footprints or extra observations.
Analysis cells need positive-area overlap with valid footprints; their
coverage percentage counts valid analysis centers, not precisely observed
land area. Gaps smaller than the selected target cells remain unresolved.

Sidecars record `footprint_source` per scan, `spatial_aggregation`,
`area_crs`, `analysis_resolution_deg`, `display_resolution_deg`, and
`display_support`. The compatibility `swath.resolution_deg` describes the
analysis grid; `analysis_resolution_deg` and `display_resolution_deg` both
record the selected target spacing. `display_support` is `analysis_valid_cells`.
Statistics may change with `--res`, but remain unchanged by smoothing or DPI.

The initial GEMS filter retains final quality flag **0**, finite coordinates
and columns, SZA/VZA below 70°, and a nonnegative cloud measure no greater
than `--cf` (default 0.5). The cloud measures differ: NO2 uses `CloudFraction`,
HCHO uses `CloudRadianceFraction`, and O3P uses `effective_cloud_fraction`.
`--qa` applies only to TROPOMI and is rejected for GEMS. Quality-filtered
negative columns are retained; HCHO gap-filled flag classes are excluded.
This explicit filter is recorded with each file's version and variable in
JSON; quality flag meanings must not be transferred between products.

GEMS JSON statistics, spatial summaries, and hotspots use the **unfilled,
unsmoothed** regional grid. Smoothing affects the map only and cannot create
new valid cells. Sidecars include `sensor`, `quantity`, the requested local
time, nominal UTC/local scan times, actual observation time ranges, filter
settings, file failures, and scan-count summaries. Window metadata retains
per-day diagnostics. Existing TROPOMI fields remain compatible; the boundary
policy block described above is additive.

GEMS `overlay` accepts an exact scan or a daily mean. A daily mean requires
an explicit `--station-datetime YYYYMMDDHH`; its title and JSON distinguish
the daily satellite mean from the hourly station observation, without a
fictitious scan-time offset. Exact scans match the nearest station hour
(at most 30 minutes, ties forward). A missing station hour is an error.
`--station-datetime` records a manual override and its time difference.
NO2 pairs with NO2; O3/O3PR pair with O3; HCHO requires an explicit `--var`.
Satellite columns and station concentrations retain independent colorbars
and units; the map shows spatial juxtaposition, not a column-to-surface
conversion.

Run the self-contained GEMS regressions without adding pytest:

```bash
uv run python -m unittest discover -s tests -p 'test_gems.py' -v
```

## License

This project is distributed under the license in `LICENSE`.

## Publishing

The package version is derived from Git by `hatch-vcs`; do not add a static
`project.version` or make version-bump commits. The latest `vX.Y.Z` tag is the
stable version. Commits after it build as the next patch development series:

```text
v0.3.0           -> 0.3.0
first commit     -> 0.3.1.dev1
second commit    -> 0.3.1.dev2
v0.3.1           -> 0.3.1
```

GitHub Actions publishes every `main` push through the `pypi-dev` environment
and every `v*` tag through `pypi`. Configure two PyPI Trusted Publishers with
the same owner, repository, and workflow, differing only by environment:

```text
Owner: yaoyhu
Repository: rsplot
Workflow: publish.yml
Environment: pypi-dev
Environment: pypi
```

Leave `pypi-dev` automatic for continuous development uploads. Protect the
`pypi` GitHub environment with required reviewers so stable releases need an
explicit approval.

To make a stable release after the desired commit is on GitHub:

```bash
git tag -a v0.3.1 -m v0.3.1
git push github v0.3.1
```
