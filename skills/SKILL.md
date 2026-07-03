---
name: rsplot
description: Use this skill whenever the user wants to plot, visualize, summarize, or compare TROPOMI satellite remote-sensing data, gridded air-quality forecast data, Chinese national air-quality monitoring station (国控站) data, ERA5 wind overlays on station maps, FNR (HCHO/NO2) regimes, or satellite-plus-station overlays for a Chinese region (country/province/city/county/key-region).
---

# rsplot — satellite, forecast, station, wind, FNR, and recent summaries

`rsplot` is a Typer CLI for Chinese-region air-quality visualization and JSON summaries. It supports TROPOMI raster products, gridded air-quality forecast maps, 国控 station data, optional ERA5 wind vectors on station maps, satellite/station overlays, HCHO/NO2 FNR regime maps, and recent-day JSON summaries for comparing weekly/monthly/yearly changes.

Subcommands:

- `rsplot raster REGION DATE_ARG` — TROPOMI raster map for `no2` / `o3` / `o3pr` / `hcho`; supports single-day and window means.
- `rsplot forecast REGION DATETIME` — gridded air-quality forecast map for `PM2.5` / `PM10` / `SO2` / `NO2` / `CO` / `O3` at forecast leads `6/12/24/48/72`.
- `rsplot station REGION DATETIME` — 国控站点 scatter map for AQI and pollutant variables; can optionally overlay ERA5 horizontal wind vectors with `--wind-level`.
- `rsplot overlay REGION DATETIME` — satellite raster plus station scatter on one map.
- `rsplot fnr REGION DATE_ARG` — FNR = HCHO / NO2 regime map from window-mean fields.
- `rsplot recent REGION END_DATE` — JSON-only recent N-day summary for `raster` or `station` data; no PNG.

When the user asks for a map, choose `raster`, `forecast`, `station`, `overlay`, or `fnr`. When they ask about "recent N days", "this week/month/year", "trend", "变化", or "compare last week/month", use `recent`.

## How to invoke the CLI

`rsplot` is installed as a command-line program on the target environment. Invoke it directly:

```bash
rsplot <subcommand> ...
```

Do **not** wrap normal usage in `uv run` and do **not** `source .venv/bin/activate`.

If an agent is unsure about syntax, flags, products, variables, or expected arguments, or if a command errors, call the built-in help before guessing. Disable Typer/Rich formatting for stable plain-text output:

```bash
TYPER_USE_RICH=0 rsplot --help
TYPER_USE_RICH=0 rsplot raster --help
TYPER_USE_RICH=0 rsplot forecast --help
TYPER_USE_RICH=0 rsplot station --help
TYPER_USE_RICH=0 rsplot overlay --help
TYPER_USE_RICH=0 rsplot fnr --help
TYPER_USE_RICH=0 rsplot recent --help
```

Use help output as the source of truth for command and subcommand syntax.

## Pick the right subcommand

| User asks for... | Use |
|---|---|
| Satellite column / remote sensing / TROPOMI / 卫星 / 遥感 | `raster` |
| HCHO spatial distribution / formaldehyde column | `raster -p hcho`, usually with `--days 30` |
| Forecast / 预报 / 未来6小时 / 未来24小时 / 72小时预报 / model forecast | `forecast` |
| 站点 / 国控站 / AQI / 小时浓度 / PM2.5 hourly | `station` |
| Station map plus wind / 风场 / 风向 / 风速 / ERA5 | `station --wind-level ...` |
| Satellite + station together / 叠加 / ground validation | `overlay` |
| HCHO/NO2 ratio / FNR / VOC-limited / NOx-limited / 臭氧敏感性 | `fnr` |
| 最近 N 天 / 周变化 / 月变化 / 年变化 / trend / only need JSON | `recent` |
| Just "a pollution map" without specifying | Ask, or default by wording: forecast/future -> `forecast`; current AQI/PM/SO2/CO -> `station`; satellite/column -> `raster`. |

`overlay` is meaningful for satellite `no2`, `o3`, or `o3pr` paired with station variables. HCHO is supported for raster maps and FNR, but not as an overlay default.

Forecast maps are not TROPOMI products: they are model-grid surface pollutant concentrations, not satellite columns.

## Region argument

A single string. rsplot resolves it to one of five administrative levels and matches fuzzily: `安徽省`, `安徽`, and `安徽 ` are equivalent.

| Level | What to pass | Notes |
|---|---|---|
| `country` | `中国` | Mainland-focused extent. |
| `key_region` | `YRD` `BTH` `PRD` `SCB`, or 中文: `长三角` `京津冀` `珠三角` `成渝` | Only these presets are configured. |
| `province` | Province/自治区/直辖市 name, e.g. `安徽`, `四川`, `北京`, `内蒙古` | 直辖市 resolve as province unless `--level city` is used. |
| `city` | Prefecture-city name, e.g. `合肥`, `杭州`, `苏州` | |
| `county` | `城市/区县`, e.g. `合肥/蜀山`, `杭州/拱墅` | Bare county names are ambiguous; use nested form. |

Use `--level / -l` only to override auto-detection.

## Date and time arguments

- `raster DATE_ARG`
  - `YYYYMMDD` without `--days` means single-day swaths.
  - `YYYYMMDD --days N` means the N-day window ending on that date.
  - `YYYYMMDD-YYYYMMDD` means an inclusive date range.
- `forecast DATETIME`
  - `YYYYMMDDHH` means a specific model initialization hour.
  - `YYYYMMDD` auto-picks the latest available non-empty initialization hour for that date and lead.
  - `valid_datetime = init_datetime + --lead hours`.
- `station DATETIME`
  - `YYYYMMDDHH` means a specific hour.
  - `YYYYMMDD` auto-picks the latest available hour of that day.
  - With `--wind-level`, the station datetime defaults to `Asia/Shanghai` and is converted to ERA5 UTC for wind matching. Use `--station-timezone` when the station archive uses a different timezone convention.
- `overlay DATETIME`
  - First 8 digits are used for the satellite date.
  - Full `YYYYMMDDHH` or auto-latest `YYYYMMDD` is used for stations.
- `fnr DATE_ARG`
  - Same date-window forms as `raster`.
  - Single date defaults to a 7-day window unless `--days` is given.
- `recent END_DATE`
  - `YYYYMMDD` only; use `--days N` to choose how many recent days to summarize.

Calendar dates are validated. For example, `20260231` is invalid.

## Products and variables

- Raster products: `o3` (default), `no2`, `o3pr`, `hcho`.
- `o3` is TROPOMI ozone total column (`ozone_total_vertical_column`, DU).
- `o3pr` is TROPOMI `O3__PR` ozone-profile product, using the provided `ozone_tropospheric_column` variable directly and converting from `mol m-2` to DU. It is a tropospheric ozone column, not total ozone.
- HCHO is sparse day-to-day; prefer `raster ... -p hcho --days 30` for readable maps.
- Forecast variables use `--var/-v`: `PM2.5`, `PM10`, `SO2`, `NO2`, `CO`, `O3`. Internally these map to NetCDF variables `pm25`, `pm10`, `so2`, `no2`, `co`, `o3`. CO is `mg/m3`; all other forecast pollutants are `ug/m3`.
- Forecast lead uses `--lead`: `6`, `12`, `24`, `48`, or `72` hours.
- FNR always combines NO2 and HCHO window means. Defaults are `<1` VOC-limited, `1-2` transition, `>2` NOx-limited, but `rsplot fnr` can override these with `--voc-threshold` and `--nox-threshold`. `--display-max` controls the FNR colorbar upper bound and must be greater than `--nox-threshold`. `--no2-min` controls the minimum mean NO2 column for valid FNR interpretation.
- Station variables are case-sensitive: `AQI`, `PM2.5`, `PM10`, `NO2`, `O3`, `SO2`, `CO`, `O3_8h`, plus `_24h` variants (`PM2.5_24h`, `NO2_24h`, `SO2_24h`, `CO_24h`, `PM10_24h`, `O3_24h`, `O3_8h_24h`).
- Station wind levels use `--wind-level`: `10m`, `100m`, `1000`, `925`, `850`, `700`, `500`. Pressure levels are hPa.
- `overlay -v` defaults from product: `-p no2 -> -v NO2`, `-p o3 -> -v O3`, `-p o3pr -> -v O3`. Override when needed, e.g. `-p o3pr -v O3_8h`.
- `recent --source raster` uses `--product/-p`; `recent --source station` uses `--var/-v`. Recent v1 does **not** compute FNR or forecast summaries.

### O3PR display defaults

`o3pr` is a coarse ozone profile product with roughly 30 km native sampling. It has product-specific defaults so agents should not force the normal fine `o3` grid unless the user asks.

| Level | `o3pr` default `--res` | `o3pr` default `--smooth` |
|---|---:|---:|
| `country` | `0.25` | `1.0` |
| `key_region` | `0.15` | `1.2` |
| `province` | `0.1` | `1.5` |
| `city` | `0.075` | `1.5` |
| `county` | `0.05` | `2.0` |

Explicit CLI flags still win: `--res` / `--smooth` override product defaults. For robust O3PR maps, prefer multi-day windows over aggressive smoothing:

```bash
rsplot raster 安徽 20260228 -p o3pr --days 7 --n-min 1 \
  -o <LOG_ROOT>/by-date/20260228/rsplot/raster_anhui_o3pr_days7_nmin1/raster_anhui_o3pr_20260228_days7.png
```

### Forecast resolution

Forecast files are native `0.1°` regular latitude/longitude grids, roughly 9-11 km in eastern China. This is appropriate for city, province, key-region, and country maps. County-level forecast maps can be scientifically valid but visually coarse because only a few grid centers may fall inside a small district.

Do not treat forecast smoothing as added information. `--smooth` only makes the display less blocky; it does not increase model resolution.

## Output files

Use the public artifact root from the system prompt as `LOG_ROOT`. `LOG_ROOT` is shared across conversations. For dated outputs, write under `<LOG_ROOT>/by-date/<date-key>/rsplot/<stable-key>/...`, where `date-key` is `YYYYMMDD` for one day or `YYYYMMDD_YYYYMMDD` for an inclusive date range.

Before running `rsplot`, inspect the expected date directory with `find` or `rg --files`. If a matching JSON sidecar already exists, read it and reuse its paired PNG instead of re-running. Treat an artifact as reusable only after the JSON matches the requested command, region, product/variable, date window, `--days`, `--n-min`, forecast lead, wind level, thresholds, and other relevant flags.

For map commands, always pass `-o` so the PNG and JSON sidecar are written. For `recent`, `-o` is the JSON output path directly.

Prefer stable output locations:

```text
<LOG_ROOT>/by-date/<date-key>/rsplot/<stable-key>/<command>_<region>_<name>_<date>.png
<LOG_ROOT>/by-date/<init-date>_<valid-date>/rsplot/forecast_<region>_<var>_init<YYYYMMDDHH>_f<lead>/forecast_<region>_<var>_<YYYYMMDDHH>_f<lead>.png
<LOG_ROOT>/by-date/<date-key>/rsplot/<stable-key>/recent_<region>_<source>_<name>_<start>_<end>.json
```

Create parent directories before invoking if needed. If no `-o` is given, rsplot writes to `/tmp`.

## JSON output contract

For `raster`, `forecast`, `station`, `overlay`, and `fnr`, `-o foo.png` also writes `foo.json`. Read the JSON sidecar after running; do not parse rich stdout.

For `recent`, the command writes only JSON to the path passed with `-o`.

Important coverage semantics: `stats.coverage_pct` for gridded outputs is the fraction of valid grid centers **inside the administrative geometry**, not the fraction of the full rectangular plotting extent. For example, county forecast output may show `100% (7/7)` even though only seven coarse forecast grid centers fall inside that county.

JSON contents:

- Common map fields: `command`, `image`, `sidecar`, `region`, `stats`, `unit` where applicable.
- `raster`: `product`, `date`, `vrange`, `swath`, `stats.grid_shape`, `stats.coverage_pct`, `stats.valid_region_pixels`, `stats.total_region_pixels`, optional `window`, `spatial_summary`, `hotspots`.
- `forecast`: `variable`, `label`, `unit`, `forecast.init_datetime`, `forecast.lead_hour`, `forecast.valid_datetime`, `forecast.source_file`, `vrange`, `stats.coverage_pct`, `stats.n_region_cells`, `stats.n_valid`, `stats.n_read_cells`, `stats.n_read_valid`, optional `spatial_summary`, `hotspots`.
- `station`: `datetime`, `variable`, `n_stations`, `n_valid`, `threshold`, `exceedance`, `aqi_distribution`, `city_ranking`. If ERA5 wind is requested, includes `wind` with `level`, `datetime_utc`, `source_files`, `grid_shape`, `stride`, `n_vectors_valid`, `n_arrows_plotted`, component/speed stats, resultant wind direction, and max-speed location.
- `overlay`: top-level shared fields plus nested `.raster` and `.station` blocks matching the standalone JSON structures.
- `fnr`: `window`, `params` (including `n_min`, `no2_min_column`, `voc_threshold`, `nox_threshold`, `display_max`, `resolution_deg`), `stats.coverage_pct`, `stats.coverage_days`, `stats.mask_diagnostics`, `regime_pct`, `mean_fields`, and optional `city_ranking`.
- `recent`: `source`, `period`, `availability`, `daily`, `windows`, `changes`, `trend`, `warnings`.

Use `jq` to inspect:

```bash
jq '.stats, .spatial_summary, .hotspots' output.json
jq '.forecast, .stats, .hotspots' forecast.json
jq '.wind, .stats, .city_ranking' station_wind.json
jq '.availability, .windows, .changes, .trend' recent.json
```

If the user asks "which cities are highest", "where is the hotspot", "what changed this week", "what is the forecast valid time", "what wind field was matched", or "is the trend up or down", answer from JSON fields rather than recomputing from pixels or parsing stdout.

## Canonical invocations

```bash
# Single-day satellite raster:
rsplot raster 合肥 20260115 -p no2 -o <LOG_ROOT>/by-date/20260115/rsplot/raster_hefei_no2/raster_hefei_no2_20260115.png
rsplot raster 中国 20260208 -p o3 -o <LOG_ROOT>/by-date/20260208/rsplot/raster_china_o3/raster_china_o3_20260208.png
rsplot raster 安徽 20260227 -p o3pr -o <LOG_ROOT>/by-date/20260227/rsplot/raster_anhui_o3pr/raster_anhui_o3pr_20260227.png

# HCHO window mean:
rsplot raster 安徽 20260131 -p hcho --days 30 -o <LOG_ROOT>/by-date/20260102_20260131/rsplot/raster_anhui_hcho_days30/raster_anhui_hcho_20260131_days30.png
rsplot raster 长三角 20260101-20260131 -p no2 -o <LOG_ROOT>/by-date/20260101_20260131/rsplot/raster_yrd_no2/raster_yrd_no2_20260101_20260131.png

# Forecast maps:
rsplot forecast 安徽 2026063000 --lead 24 --var O3 -o <LOG_ROOT>/by-date/20260630_20260701/rsplot/forecast_anhui_o3_init2026063000_f24/forecast_anhui_o3_2026063000_f24.png
rsplot forecast 合肥 20260630 --lead 72 --var PM2.5 -o <LOG_ROOT>/by-date/20260630_20260703/rsplot/forecast_hefei_pm25_latest_f72/forecast_hefei_pm25_20260630_f72.png

# Station map:
rsplot station 安徽 2026041415 --var PM2.5 -o <LOG_ROOT>/by-date/20260414/rsplot/station_anhui_pm25_15/station_anhui_pm25_2026041415.png
rsplot station 中国 20260414 --var AQI -o <LOG_ROOT>/by-date/20260414/rsplot/station_china_aqi/station_china_aqi_20260414.png

# Station map with ERA5 wind:
rsplot station 合肥 2026041415 --var O3 --wind-level 10m -o <LOG_ROOT>/by-date/20260414/rsplot/station_hefei_o3_wind10m_15/station_hefei_o3_wind10m_2026041415.png
rsplot station 安徽 2026041415 --var PM2.5 --wind-level 850 -o <LOG_ROOT>/by-date/20260414/rsplot/station_anhui_pm25_wind850_15/station_anhui_pm25_wind850_2026041415.png

# Overlay:
rsplot overlay YRD 2026041415 -p no2 -o <LOG_ROOT>/by-date/20260414/rsplot/overlay_yrd_no2_15/overlay_yrd_no2_2026041415.png
rsplot overlay 安徽 2026041415 -p o3 -v O3_8h -o <LOG_ROOT>/by-date/20260414/rsplot/overlay_anhui_o3_o3_8h_15/overlay_anhui_o3_o3_8h_2026041415.png
rsplot overlay 安徽 2026022715 -p o3pr -v O3_8h -o <LOG_ROOT>/by-date/20260227/rsplot/overlay_anhui_o3pr_o3_8h_15/overlay_anhui_o3pr_o3_8h_2026022715.png

# FNR regime:
rsplot fnr 合肥 20260131 --days 30 --n-min 7 -o <LOG_ROOT>/by-date/20260102_20260131/rsplot/fnr_hefei_days30_nmin7/fnr_hefei_20260131_days30_nmin7.png
rsplot fnr 长三角 20260101-20260130 -o <LOG_ROOT>/by-date/20260101_20260130/rsplot/fnr_yrd/fnr_yrd_20260101_20260130.png
rsplot fnr 合肥 20260131 --days 30 --n-min 3 --voc-threshold 1.94 --nox-threshold 2.43 --display-max 6 -o <LOG_ROOT>/by-date/20260102_20260131/rsplot/fnr_hefei_days30_nmin3_lit/fnr_hefei_20260131_days30_lit.png

# Recent JSON summaries, no PNG:
rsplot recent 合肥 20260228 --days 30 -p hcho -o <LOG_ROOT>/by-date/20260130_20260228/rsplot/recent_hefei_hcho_days30/recent_hefei_raster_hcho_20260130_20260228.json
rsplot recent 安徽 20260228 --source raster -p o3pr --days 7 -o <LOG_ROOT>/by-date/20260222_20260228/rsplot/recent_anhui_o3pr_days7/recent_anhui_raster_o3pr_20260222_20260228.json
rsplot recent 合肥 20260428 --days 7 --source station --var O3 -o <LOG_ROOT>/by-date/20260422_20260428/rsplot/recent_hefei_station_o3_days7/recent_hefei_station_o3_20260422_20260428.json
```

## Flags — when to use them

Most map runs need only `REGION DATE [-p|--var] -o`. Reach for other flags only when useful:

| Flag | Reason to use |
|---|---|
| `--days` | Window means for raster/FNR/recent; especially important for HCHO. |
| `--lead` | Forecast only. Forecast lead time in hours: `6`, `12`, `24`, `48`, or `72`. |
| `--var / -v` | Station or forecast variable. Station names are case-sensitive; forecast accepts pollutant names such as `PM2.5` and `O3`. |
| `--n-min` | Minimum valid days per pixel for raster window/FNR. Lower it when coverage is too sparse; increase it for stricter diagnostics. |
| `--voc-threshold` | FNR only. Override the VOC-limited cutoff; pixels with FNR below this are VOC-limited. Must be `>=0` and less than `--nox-threshold`. |
| `--nox-threshold` | FNR only. Override the NOx-limited cutoff; pixels with FNR above this are NOx-limited. Must be greater than `--voc-threshold` and less than `--display-max`. |
| `--display-max` | FNR only. Colorbar/display upper bound. Increase it when using high regional thresholds such as 4-5 so the NOx-limited band remains visible. |
| `--wind-level` | Station only. Overlay ERA5 wind vectors at `10m`, `100m`, or pressure levels `1000/925/850/700/500`. |
| `--wind-data-dir` | Station wind only. Override the configured ERA5 directory. |
| `--station-timezone` | Station wind only. IANA timezone for station file timestamps; default `Asia/Shanghai`. |
| `--wind-stride` | Station wind only. Force quiver thinning. Let rsplot choose automatically unless the plot is too dense or too sparse. |
| `--wind-scale`, `--wind-width` | Station wind only. Tune Matplotlib quiver geometry. |
| `--wind-cmap`, `--wind-vmin`, `--wind-vmax` | Station wind only. Tune wind-speed color scale. |
| `--level / -l` | User wants a different administrative level than auto-detect. |
| `--basemap / -b satellite\|none` | User wants satellite tile background or no basemap. |
| `--vmin` / `--vmax` / `--cmap` | User wants a specific color scale for comparable plots. Pass vmin/vmax together. |
| `--smooth` | User explicitly wants smoothing or wants to override product defaults. For O3PR, defaults are product-aware by level. Note that FNR restores the original valid mask after smoothing. For forecast, smoothing is visual only and does not add resolution. |
| `--qa` | Stricter/looser TROPOMI QA filtering; default is 0.5. For sparse O3PR days, try `--qa 0.3` only as a diagnostic. |
| `--res` | Specific grid resolution in degrees. For O3PR, avoid forcing very fine grids unless the user wants visual interpolation. Forecast uses its native grid and does not expose `--res`. |
| `--dpi` | Override image DPI; default is usually fine. |
| `--data-dir / -d` | Override a single data source for `raster`, `forecast`, or `station`. `overlay` uses `--raster-dir` and `--station-dir`; `fnr` uses `--no2-dir` and `--hcho-dir`. |
| `--title` | Custom title. |

## Data paths and reader behavior

Configured data directories are loaded by rsplot from `$HOME/.config/rsplot/config.toml` first, then overwritten by environment variables when they are set. In the TianPu container `$HOME` is `/data/home`, and docker compose bind-mounts the host rsplot config there.

These environment variables may override the config file:

- `RSPLOT_DATA_DIR_NO2`
- `RSPLOT_DATA_DIR_O3`
- `RSPLOT_DATA_DIR_O3PR`
- `RSPLOT_DATA_DIR_HCHO`
- `RSPLOT_DATA_DIR_GUOKONG`
- `RSPLOT_DATA_DIR_ERA5`
- `RSPLOT_DATA_DIR_FORECAST`
- `RSPLOT_GEOJSON_DIR`
- `RSPLOT_FONT_DIR`
- `RSPLOT_HCHO_CMAP_FILE`
- `TIANDITU_API_KEY`

Expected local config or environment values under `TIANPU_DATA_ROOT`:

- NO2: `$TIANPU_DATA_ROOT/no2/OFFL`
- O3: `$TIANPU_DATA_ROOT/o3/OFFL`
- O3PR: `$TIANPU_DATA_ROOT/o3pr/OFFL`
- HCHO: `$TIANPU_DATA_ROOT/hcho/OFFL`
- SO2: `$TIANPU_DATA_ROOT/so2/OFFL`
- AOD: `$TIANPU_DATA_ROOT/aod`
- 国控: `$TIANPU_DATA_ROOT/stations`
- ERA5: `$TIANPU_DATA_ROOT/era5`
- Forecast: `$TIANPU_DATA_ROOT/forecast`
- GeoJSON: `$TIANPU_DATA_ROOT/auxiliaries/geojson`
- Fonts: `$TIANPU_DATA_ROOT/auxiliaries/fonts`

The TROPOMI readers glob only the configured directory itself; they do not recursively search product subdirectories such as `OFFL/` or `NRT/`.

The TROPOMI readers accept both flattened variables (`PRODUCT_longitude`) and official `/PRODUCT` group variables (`longitude`), and support `.nc` and `.nc.zip` patterns. Broken/unreadable orbit files are counted and skipped rather than failing the whole day.

Forecast reader behavior:

- Forecast files are grouped as `forecast{lead}/{YYYYMMDDHH}_forecast{lead}.nc`.
- The filename timestamp is the model initialization time.
- `valid_datetime = init_datetime + lead_hour`.
- `YYYYMMDD` input chooses the latest non-empty file for that date and lead.
- Forecast files are regular `lat, lon` grids with variables `pm25`, `pm10`, `so2`, `no2`, `co`, and `o3`.

ERA5 wind reader behavior:

- ERA5 files are indexed in UTC.
- Station filenames default to `Asia/Shanghai`; rsplot converts the resolved station time to UTC before selecting the ERA5 hour.
- Early local hours can map to the previous UTC date. For example, `2026010104 Asia/Shanghai` matches `2025123120 UTC`.
- Single-level winds use `10m` or `100m`; pressure-level winds use `1000/925/850/700/500 hPa`.

## Error handling notes

- Unknown region: check spelling; county-level needs `市/县` nesting.
- Unknown product: raster supports `o3`, `no2`, `o3pr`, `hcho`; overlay supports `o3`, `o3pr`, and `no2`.
- Unknown forecast variable: use `PM2.5`, `PM10`, `SO2`, `NO2`, `CO`, or `O3`.
- Invalid forecast lead: use only `6`, `12`, `24`, `48`, or `72`.
- Unknown station variable: match case exactly.
- Invalid date: use real calendar dates (`20260228`, not `20260231`).
- Raster/FNR all-NaN or no valid pixels: coverage is too sparse, `--n-min` may be too strict, or the time window is too short. Try a multi-day window, lower `--n-min`, or use an earlier/later date. For O3PR, try `--days 7 --n-min 1` before increasing smoothing.
- HCHO/FNR coverage can be sparse even when files exist; the key is per-pixel NO2/HCHO overlap after QA and masking.
- Forecast date-only input can fail if no non-empty file exists for that date and lead.
- Forecast county maps may look blocky because the native grid is `0.1°`; this is a data-resolution limitation, not a plotting failure.
- Station wind can fail if the matched ERA5 UTC hour or U/V component file is missing. Check `wind.datetime_utc` and `wind.source_files` in JSON when diagnosing.
- Station commands first bbox-filter then geometry-filter stations; region-edge stations outside the administrative boundary are omitted silently.

## What not to do

- Don't call rsplot internals from custom Python when the CLI can do the job.
- Don't mix up satellite columns, forecast surface concentrations, and station pollutants: TROPOMI supplies columns, forecast supplies gridded surface concentrations, and stations supply point observations.
- Don't invent region names, products, forecast variables, leads, wind levels, or station variables not listed above.
- Don't compare `o3` and `o3pr` as the same physical quantity: `o3` is total column, `o3pr` is tropospheric column from the profile product.
- Don't compare forecast `O3` directly with TROPOMI `o3`: forecast `O3` is surface concentration, while TROPOMI `o3` is total column.
- Don't use county-level forecast maps to infer street-scale gradients; forecast native resolution is about 0.1°.
- Don't override tuned defaults just to make maps look nicer unless the user asks.
- Don't parse rich stdout for results; use the JSON sidecar or recent JSON.
- Don't interpret `coverage_pct` as rectangular plot coverage. It is administrative-geometry grid coverage for gridded outputs.
- Don't expect `recent` to produce a PNG; it is JSON-only.
- Don't use `overlay` for HCHO unless a future version explicitly adds station pairing semantics.
