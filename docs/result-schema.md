# rsplot result sidecar

Status: **implemented for every enabled command.** The disabled `forecast`
and `reconstruct` commands are out of scope.

Every rsplot command writes one JSON sidecar with the same envelope when it
succeeds. A failed run writes no sidecar (see Errors). The sidecar is written for agents that will analyse the
result further: it says what was computed, how far it can be trusted, how to
reproduce it, and where the full data is. Humans read the PNG and stdout.

- Machine schema: [`src/rsplot/schemas/result.schema.json`](../src/rsplot/schemas/result.schema.json)
  (JSON Schema 2020-12, shipped inside the package).
- Examples, all valid against the schema:
  - [`overlay-tropomi-day.json`](result-examples/overlay-tropomi-day.json):
    two layers, time matching and colocation.
  - [`raster-window-unreliable.json`](result-examples/raster-window-unreliable.json):
    a sparse Hefei 7-day window with 2.9 % coverage and a critical
    `very_low_coverage` flag.

  Examples abbreviate long lists (`by_admin`, `extremes`).

This is a clean break from the old sidecars: no legacy keys are kept. There
is no format number; `rsplot_version` identifies the release that wrote the
file, and that release's shipped schema describes it.

## Design rules

1. **One envelope, one layer shape.** Every command emits the same top-level
   keys. What differs between commands is only how many `layers` there are
   and what `kind` they are. An agent needs one parser.
2. **Numbers are numbers.** Units are machine-readable (`unit` + `scale`), never
   parsed from display labels. Missing values are `null`, never `NaN`.
3. **Evidence, not verdicts.** The sidecar holds numbers measured from the
   data. `quality.flags` name documented conditions with the counts and
   threshold that raised them; there is no prose message and no overall
   grade, so the agent draws its own conclusion. A mean over 35 cells must
   not look like a mean over 800.
4. **Point to the full data.** Summaries stay in JSON; complete grids, station
   tables and series go into data files next to the image.
5. **Reproducible.** `request` is the command line; every effective value
   that changes the numbers is in `layers[].method`, and `source` records the
   data root and how many files were read (no file lists).
6. **Science and display are separate.** Everything that changes values lives
   in `layers[].method`; everything that only changes the picture lives in
   `render`.
7. **A sidecar means success.** Failures write no sidecar; they exit 1 with
   one `rsplot error` line on stderr.

## Top-level keys

| Key | Meaning |
| --- | --- |
| `command` | `raster`, `radius`, `overlay`, `station`, `trend`, `meteo`, `fnr`. |
| `rsplot_version`, `generated_at` | Package version and ISO 8601 time with offset. |
| `request` | The command as received, shell-quoted on one line, e.g. `rsplot raster 合肥市 20260919 --product no2 --output /abs/map.png`. |
| `region` | `name`, `level`, `kind` (`administrative` or `station_radius`), `bbox` (`[lon_min, lon_max, lat_min, lat_max]`), `members` (comma-selected regions), and for radius maps `radius` (`center_station`, `center_lon`, `center_lat`, `km`, `side_length_km`, `shape`, `projection`, `administrative_context`). `null` only for single-station trends. |
| `layers` | One entry per data layer (below); never empty. |
| `relations` | How layers relate: `time_matching` and `colocation`. `{}` for single-layer results. |
| `quality` | `flags` (below); `[]` when no condition was met. |
| `render` | Image settings actually used, per layer id. |
| `artifacts` | `image`, `sidecar`, and every `data` file with format, content, shape/rows and size in bytes. All paths are absolute. |

## Layers

Every layer has the same keys:

| Key | Meaning |
| --- | --- |
| `id` | Unique name within the sidecar (`satellite`, `station`, `temperature`, `wind`, `no2`, `hcho`, `fnr`, `regional_mean`, ...). |
| `kind` | `grid`, `points`, `vector_grid` or `series`. |
| `quantity` | `name`, `unit`, `scale` (stored × scale = value in `unit`), optional display `label`. |
| `time` | `aggregation` (`scan`, `hourly`, `daily`, `daily_scan_mean`, `window_mean`, `hourly_series`), `at` or `start`/`end`, `timezone`, `basis`, optional `archive_time_utc`, and `days` for windows (`requested`, `found`, `failed`, `n_min`, `valid_days_per_cell`). `n_min` is the minimum valid days that keep a cell: always 1 for `raster`, `overlay` and `radius`, whose window means average each cell's valid days and leave cells without any as nodata; `fnr` records its `--n-min`. |
| `source` | `sensor`, `processing` (`offl` or `nrti` for TROPOMI, `null` otherwise), `data_root`, `files_total` (files read; names are not listed), `failed_files` (relative name → reason), `versions`. |
| `method` | Choices that change values: QA/cloud filters, grid spacing, gap filling, day weighting, smoothing, cell selection/weighting, pixels used. |
| `coverage` | `valid`, `total`, `fraction` (0–1), `unit` (`cells`, `stations`, `hours`, `vectors`). |
| `stats` | `n`, `mean`, `std`, `min`, `p10`, `p25`, `median`, `p75`, `p90`, `max` over the statistical support. |
| `exceedance` | Station layers with a standard: `threshold`, `operator` (`>`), `standard`, `count`, `fraction`. |
| `vector_summary` | Vector layers: resultant `mean_u`, `mean_v`, `direction_to_deg`, `wind_from_deg`, component statistics and the maximum-speed location. |
| `daily` | Series layers: one row per China-time day with `date`, `hours` (valid hours), `mean`, `min`, `max`. |
| `diurnal` | Series layers: 24 rows, one per China-time hour of day, with `days` (valid days at that hour) and `mean`. |
| `categories` | Counts per band where the variable has bands, e.g. AQI levels (优, 良, 轻度, 中度, 重度, 严重, 爆表). |
| `by_admin` | Statistics for every subdivision of the region, never truncated; may carry a `category` such as the dominant FNR regime. |
| `by_member` | Comma-selected regions only (`raster`, `overlay`, `station`, `meteo`, `fnr`), from the same statistical data. A member without valid data keeps `n: 0` with null summaries (and a null FNR `category`). |
| `extremes` | Highest cells, stations or hours as a capped list: `items`, `total`, `truncated`, `order`. Station items in `overlay` and `radius` with a station variable add `satellite_value` (the colocated cell, `null` outside valid cells). |
| `data` | Absolute path of this layer's data file, or `null`. |

Commands map onto layers like this:

| Command | Layers |
| --- | --- |
| `raster` | `satellite` (grid) |
| `overlay` | `satellite` (grid), `station` (points) |
| `radius` | `satellite` (grid), `station` (points; quantity `location` with no values and no relations without `--station-var`) |
| `station` | `station` (points) |
| `trend` | `station` (series, station ID in `subject`, region `null`); region mode: `regional_mean` and `station` (series), all hours in the data file. The single station and `regional_mean` carry `daily` and `diurnal`; the region-mode `station` layer lists each station's mean, max and valid hours in `extremes` |
| `meteo` | any of `temperature` (grid, degC), `wind` (vector_grid, speed statistics plus `vector_summary`), `station` (points, paired with `wind` by `same_hour`) |
| `fnr` | `no2` and `hcho` window means (grid), `fnr` (grid, unit 1) with regime counts in `categories`, masking rules and `mask_counts` in `method`, and dominant regimes per unit in `by_admin[].category` |

## Relations

`time_matching` describes how two layers taken at different times were
paired. It replaces the per-command blocks: `layers` names the pair,
`reference` says how the time was chosen (`nominal_scan_time`,
`daily_mean_with_explicit_station_hour`,
`period_mean_with_explicit_station_hour`, `explicit_station_hour`,
`same_hour`), `difference_minutes` is `null` when one side is a daily or window
mean, and `manual_override` says whether `--station-datetime` set it.

`colocation` answers one question: **at the monitoring stations, does the
satellite field rise and fall with the station values?** For every station
inside a valid statistics cell, rsplot pairs the station value with the
satellite value of that cell. `pairs` counts them and `spearman` is their rank
correlation (`null` with fewer than 3 pairs). The full pair list is in the
station CSV (`satellite_value` column). `comparable_units` is `false` for
columns versus surface concentrations: a high correlation means the spatial
patterns agree, never that one quantity can be converted into the other.
Only `overlay` and `radius` with a station variable produce colocation.

## Quality

`quality.flags` lists documented conditions the run met. Each flag has
`code`, `severity`, `layer` when it concerns one layer, and `evidence`: the
measured numbers and, for threshold rules, the threshold. There is no prose
message and no overall grade. Severity follows only from the code below.
Facts that are already fields (smoothing in `method`, time matching and unit
comparability in `relations`) are not repeated as flags.

| Code | Severity | Raised when | Evidence |
| --- | --- | --- | --- |
| `no_valid_data` | critical | A grid or station layer has zero valid cells or stations. | `valid`, `total`, `fraction` (grids) |
| `very_low_coverage` | critical | Grid coverage fraction < 0.10. | `valid`, `total`, `fraction`, `threshold` |
| `low_coverage` | warning | Grid coverage fraction < 0.30. | `valid`, `total`, `fraction`, `threshold` |
| `few_valid_days` | warning | Median valid days per observed cell < `n_min` (`fnr` only; never raised when `n_min` is 1). | `median_valid_days`, `n_min` |
| `missing_days` | warning | A window has days without valid data. | `requested`, `found`, `failed` (date → reason) |
| `failed_files` | warning | Any input file could not be read. | `count` (names and reasons in `source.failed_files`) |
| `few_stations` | warning | Fewer than 3 valid stations in a station layer. | `valid`, `total`, `threshold` |
| `missing_station_values` | info | Some stations in the region have no value. | `valid`, `total` |
| `missing_hours` | warning | A series misses more than 10 % of its hours. | `valid`, `total`, `fraction`, `unit`, `threshold` |

## Data files

Data files are written next to the image and share its base name:
`<base>.<layer>.nc` or `<base>.<layer>.csv`. Input file names are not listed
anywhere; `source.data_root` and the archive layout locate them.

| Content | Format | Contents |
| --- | --- | --- |
| `statistical_grid` | NetCDF4 | `lat`, `lon` cell centres cropped to the region extent at the analysis spacing; `value` (float32, NaN = invalid, in stored units); `counted` (uint8, 1 = cell counts toward statistics); `valid_days` (int16, windows only); attributes for quantity, unit, scale, time and schema. |
| `vector_grid` | NetCDF4 | Same layout as `statistical_grid` with `value` = speed plus `u` and `v`. |
| `station_table` | CSV | Overlay: every station read around the region with `id`, `lon`, `lat`, `admin`, `admin_level`, `value`, `valid`, `exceeds`, `in_region`, `satellite_value`, `colocated`. Radius: the stations in the square with the same columns plus `is_center`, `distance_km`, `dx_km`, `dy_km`; without `--station-var` only `id`, `lon`, `lat`, `admin`, `in_region` and the radius columns. |
| `hourly_series` | NetCDF4 | `station_id`, `lon`, `lat` per station; `time` (CF hours since 1970-01-01 UTC) and `time_cst` (`YYYYMMDDHH` China time); `value(station, time)` with NaN gaps; region trends add `regional_mean(time)` and `n_stations(time)`. |

**Size.** The JSON itself stays small (typically under 64 KB) because it never
holds arrays of values: grid values, all stations and series go to data
files, `extremes` is capped at 10 items, and input files are only counted.
`daily` has one row per window day and `diurnal` 24 rows. Data files
are compressed (NetCDF zlib level 4 with shuffle) and cropped to the region
extent, not the buffered read extent. Rough worst cases: a national GEMS grid
at 0.05° (about 1.3 million cells) is 1–3 MB; a national station table (about
2,000 stations) is about 150 KB; a 30-day national region trend (2,000
stations × 720 hours) is about 2 MB. There is no hard cap; `artifacts.data`
reports each file's `bytes` so an agent can decide whether to load it.

## Errors

On any expected input or data error the command exits 1 and prints exactly
one line on stderr:

```
rsplot error <code>[ <option>]: <message>[ <details as one-line JSON>]
rsplot error region_ambiguous: 区域名 '吉林' 同时匹配 吉林省（省级）和 吉林市（市级），请写全称。 {"region": "吉林", "candidates": ["吉林省", "吉林市"]}
```

It writes no sidecar, removes the PNG and data files it had written, and
removes a sidecar an earlier run left at the same path, so a sidecar on disk
always describes a successful run. Codes:

| Code | Meaning |
| --- | --- |
| `invalid_argument` | Bad or conflicting option values. |
| `invalid_time` | Malformed or impossible date/hour, or a time form the command does not accept. |
| `region_not_found` | Region name or station ID does not resolve. |
| `region_ambiguous` | A short region name fits different places at two levels (e.g. 吉林: 吉林省 and 吉林市); `details.candidates` lists the full names to use. |
| `data_not_configured` | No configured data root for the requested product. |
| `data_not_found` | The requested file, day, scan or hour does not exist. |
| `no_valid_data` | Data was read but nothing valid falls in the region. |
| `read_failed` | Input files exist but could not be read. |
| `internal_error` | Unexpected failure; `details` carries the exception type, and the traceback follows the line. |

`option` names the offending option when there is one. The message keeps the
existing Chinese CLI wording on a single line. Usage errors caught by the CLI
parser (an unknown option, a missing required option or argument) exit 2
before rsplot runs, with the parser's own message instead of the error line.

## Versioning

There is no format number. Each release ships the schema that describes the
sidecars it writes, and `rsplot_version` in every sidecar names that release.
Tests validate every sidecar against the shipped schema.
