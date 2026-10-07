# rsplot result sidecar — `rsplot.result/2`

Status: **implemented for every enabled command.** The disabled `forecast`
and `reconstruct` commands are out of scope.

Every rsplot command writes one JSON sidecar with the same envelope, whether
it succeeds or fails. The sidecar is written for agents that will analyse the
result further: it says what was computed, how far it can be trusted, how to
reproduce it, and where the full data is. Humans read the PNG and stdout.

- Machine schema: [`src/rsplot/schemas/result-2.schema.json`](../src/rsplot/schemas/result-2.schema.json)
  (JSON Schema 2020-12, shipped inside the package).
- Examples, all valid against the schema:
  - [`overlay-tropomi-day.json`](result-examples/overlay-tropomi-day.json):
    two layers, time matching, colocation, informational flags.
  - [`raster-window-unreliable.json`](result-examples/raster-window-unreliable.json):
    the real Hefei 7-day window with 2.9 % coverage, graded `unreliable`.
  - [`overlay-error.json`](result-examples/overlay-error.json): a failed run.

  Examples abbreviate long lists (`files`, `by_admin`, `extremes`).

This is a clean break from the old sidecars: no legacy keys are kept. The
`schema` field identifies the version; a consumer must check it.

## Design rules

1. **One envelope, one layer shape.** Every command emits the same top-level
   keys. What differs between commands is only how many `layers` there are
   and what `kind` they are. An agent needs one parser.
2. **Numbers are numbers.** Units are machine-readable (`unit` + `scale`), never
   parsed from display labels. Missing values are `null`, never `NaN`.
3. **Say how much to trust it.** `quality` grades every result and explains
   why with coded flags. A mean over 35 cells must not look like a mean over
   800.
4. **Point to the full data.** Summaries stay in JSON; complete grids, station
   tables and series go into data files next to the image.
5. **Reproducible.** `request` records the exact arguments and every effective
   parameter with where it came from; `source` records every input file.
6. **Science and display are separate.** Everything that changes values lives
   in `layers[].method`; everything that only changes the picture lives in
   `render`.
7. **Failures use the same envelope** with `status: "error"`.

## Top-level keys

| Key | Meaning |
| --- | --- |
| `schema` | Always `"rsplot.result/2"`. |
| `status` | `"ok"` or `"error"`. |
| `command` | `raster`, `radius`, `overlay`, `station`, `trend`, `meteo`, `recent`, `fnr`. |
| `rsplot_version`, `generated_at` | Package version and ISO 8601 time with offset. |
| `request` | `argv` exactly as received, and `resolved`: every effective parameter as `{value, source, detail?}` where `source` is `cli`, `config`, `level_default`, `product_default` or `built_in`. |
| `region` | `name`, `level`, `kind` (`administrative` or `station_radius`), `extent`, `members` (comma-selected regions), and for radius maps `radius` (`center_station`, `center_lon`, `center_lat`, `km`, `side_length_km`, `shape`, `projection`, `administrative_context`). `null` only for single-station trends or failures before region resolution. |
| `layers` | One entry per data layer (below). Empty only on failure. |
| `relations` | How layers relate: `time_matching` and `colocation`. `{}` for single-layer results. |
| `quality` | `grade` and `flags` (below). |
| `render` | Image settings actually used, per layer id. `null` for `recent` and failures. |
| `artifacts` | `image`, `sidecar`, and every `data` file with format, content, shape/rows and size in bytes. All paths are absolute. |
| `error` | `null` on success; `{code, message, option?, details?}` on failure. |

## Layers

Every layer has the same keys:

| Key | Meaning |
| --- | --- |
| `id` | Unique name within the sidecar (`satellite`, `station`, `temperature`, `wind`, `no2`, `hcho`, `fnr`, `regional_mean`, ...). |
| `kind` | `grid`, `points`, `vector_grid` or `series`. |
| `quantity` | `name`, `unit`, `scale` (stored × scale = value in `unit`), optional display `label`. |
| `time` | `aggregation` (`scan`, `hourly`, `daily`, `daily_scan_mean`, `window_mean`, `hourly_series`), `at` or `start`/`end`, `timezone`, `basis`, optional `archive_time_utc`, and `days` for windows (`requested`, `found`, `failed`, `n_min`, `valid_days_per_cell`). |
| `source` | `sensor`, `processing` (`offl` or `nrti` for TROPOMI, `null` otherwise), `data_root`, `files` (relative to `data_root`, sorted, at most 200), `files_total`, `files_manifest` (absolute path of a CSV of all files when there are more than 200), `failed_files`, `versions`. |
| `method` | Choices that change values: QA/cloud filters, grid spacing, gap filling, day weighting, smoothing, cell selection/weighting, pixels used. |
| `coverage` | `valid`, `total`, `fraction` (0–1), `unit` (`cells`, `stations`, `hours`, `vectors`). |
| `stats` | `n`, `mean`, `std`, `min`, `p10`, `p25`, `median`, `p75`, `p90`, `max` over the statistical support. |
| `exceedance` | Station layers with a standard: `threshold`, `operator` (`>`), `standard`, `count`, `fraction`. |
| `vector_summary` | Vector layers: resultant `mean_u`, `mean_v`, `direction_to_deg`, `wind_from_deg`, component statistics and the maximum-speed location. |
| `categories` | Counts per band where the variable has bands, e.g. AQI levels (优, 良, 轻度, 中度, 重度, 严重, 爆表). |
| `temporal_summary` | Comparisons across a series (`recent`): `windows` (last/previous 7 and 30 days, last 365), `changes` between them, and the linear `trend`. |
| `by_admin` | Statistics for every subdivision of the region, never truncated; may carry a `category` such as the dominant FNR regime. |
| `by_member` | Comma-selected regions only, from the same statistical data. |
| `extremes` | Highest cells or stations as a capped list: `items`, `total`, `truncated`, `order`. |
| `data` | Absolute path of this layer's data file, or `null`. |

Commands map onto layers like this:

| Command | Layers |
| --- | --- |
| `raster` | `satellite` (grid) |
| `overlay` | `satellite` (grid), `station` (points) |
| `radius` | `satellite` (grid), `station` (points; quantity `location` with no values and no relations without `--station-var`) |
| `station` | `station` (points) |
| `trend` | `station` (series, station ID in `subject`, region `null`); region mode: `regional_mean` and `station` (series), all hours in the data file |
| `meteo` | any of `temperature` (grid, degC), `wind` (vector_grid, speed statistics plus `vector_summary`), `station` (points, paired with `wind` by `same_hour`) |
| `recent` | one daily `series` layer, `satellite` or `station`, with `temporal_summary`; no image, `render` null |
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

`grade` is the worst flag severity: no flags or only `info` → `good`; any
`warning` → `limited`; any `critical` → `unreliable`; failed runs → `failed`.
Agents should not report `unreliable` statistics as regional values without
saying so.

| Code | Severity | Raised when |
| --- | --- | --- |
| `no_valid_data` | critical | A layer has zero valid cells/stations/hours. |
| `very_low_coverage` | critical | Grid coverage fraction < 0.10. |
| `low_coverage` | warning | Grid coverage fraction < 0.30. |
| `few_valid_days` | warning | Window median valid days per cell < `n_min`. |
| `missing_days` | warning | A window has failed or missing days. |
| `failed_files` | warning | Any input file could not be read. |
| `few_stations` | warning | Fewer than 3 valid stations in a station layer. |
| `missing_station_values` | info | Some stations in the region have no value. |
| `missing_hours` | warning | A series misses more than 10 % of its hours. |
| `daily_vs_hourly` | info | A daily/window field is paired with one hour. |
| `column_vs_surface` | info | Satellite columns are compared with surface concentrations. |
| `manual_time_override` | info | `--station-datetime` overrode automatic matching. |
| `values_smoothed` | info | Statistical smoothing changed values (coverage never changes). |

Each flag carries `code`, `severity`, optional `layer`, a short `message`
suggesting a remedy when there is one, and `evidence` with the numbers that
triggered it.

## Data files

Data files are written next to the image and share its base name:
`<base>.<layer>.nc`, `<base>.<layer>.csv`, and `<base>.sources.csv` when a
source list is too long for JSON.

| Content | Format | Contents |
| --- | --- | --- |
| `statistical_grid` | NetCDF4 | `lat`, `lon` cell centres cropped to the region extent at the analysis spacing; `value` (float32, NaN = invalid, in stored units); `counted` (uint8, 1 = cell counts toward statistics); `valid_days` (int16, windows only); attributes for quantity, unit, scale, time and schema. |
| `vector_grid` | NetCDF4 | Same layout as `statistical_grid` with `value` = speed plus `u` and `v`. |
| `station_table` | CSV | Overlay: every station read around the region with `id`, `lon`, `lat`, `admin`, `admin_level`, `value`, `valid`, `exceeds`, `in_region`, `satellite_value`, `colocated`. Radius: the stations in the square with the same columns plus `is_center`, `distance_km`, `dx_km`, `dy_km`; without `--station-var` only `id`, `lon`, `lat`, `admin`, `in_region` and the radius columns. |
| `hourly_series` | NetCDF4 | `station_id`, `lon`, `lat` per station; `time` (CF hours since 1970-01-01 UTC) and `time_cst` (`YYYYMMDDHH` China time); `value(station, time)` with NaN gaps; region trends add `regional_mean(time)` and `n_stations(time)`. |
| `daily_table` | CSV | `recent`: one row per requested day with `date`, `ok`, `value`, and `error`; satellite adds `n_valid`, `coverage_fraction`, `pixels`; station adds `hours` (hourly files read that day), `n_valid`, `n_stations`, `n_exceed` (stations above `method.daily_limit`). |
| `source_manifest` | CSV | Every input file with status and failure reason. |

**Size.** The JSON itself stays small (typically under 64 KB) because it never
holds arrays of values: grid values, all stations and series go to data
files, `extremes` is capped at 10 items, and `files` at 200 names. Data files
are compressed (NetCDF zlib level 4 with shuffle) and cropped to the region
extent, not the buffered read extent. Rough worst cases: a national GEMS grid
at 0.05° (about 1.3 million cells) is 1–3 MB; a national station table (about
2,000 stations) is about 150 KB; a 30-day national region trend (2,000
stations × 720 hours) is about 2 MB. There is no hard cap; `artifacts.data`
reports each file's `bytes` so an agent can decide whether to load it.

## Errors

On any expected input or data error the command exits 1, writes no PNG and
no data files, and writes the envelope with `status: "error"`, `quality.grade:
"failed"`, empty `layers`, `render: null`, and `error`:

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
| `internal_error` | Unexpected failure; `details` carries the exception type. |

`option` names the offending option when there is one. `message` keeps the
existing Chinese CLI wording. Usage errors caught by the CLI parser (an
unknown option, a missing required option or argument) exit 2 before rsplot
runs and write no sidecar; the exit code is the only signal.

## Versioning

Additive changes (new optional keys, new flag codes, new layer ids) keep
`rsplot.result/2`. Removing or renaming a key, or changing a meaning, bumps
the version. Tests validate every sidecar against the shipped schema.
