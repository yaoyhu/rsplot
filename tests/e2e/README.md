# E2E reviews

Acceptance scenarios are in [RASTER_SCENARIOS.md](RASTER_SCENARIOS.md),
[OVERLAY_SCENARIOS.md](OVERLAY_SCENARIOS.md),
[RADIUS_SCENARIOS.md](RADIUS_SCENARIOS.md),
[STATION_SCENARIOS.md](STATION_SCENARIOS.md),
[TREND_SCENARIOS.md](TREND_SCENARIOS.md),
[RECENT_SCENARIOS.md](RECENT_SCENARIOS.md),
[FNR_SCENARIOS.md](FNR_SCENARIOS.md),
[METEO_SCENARIOS.md](METEO_SCENARIOS.md) and
[CLI_SCENARIOS.md](CLI_SCENARIOS.md) (the enabled command set).
Each test launches the installed `rsplot` console command in a separate
process. Fixtures are real temporary NetCDF, GeoJSON and TOML files, with
deterministic values and no mocks. Successful plotting scenarios decode the
PNG, check for colored content, and read the persisted JSON. Rejected
requests must not leave output files.

Run only the affected command's E2E tier locally:

```bash
uv run python -B -m unittest discover -s tests/e2e -p 'test_cli.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_raster.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_overlay.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_radius.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_station.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_trend.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_recent.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_fnr.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_meteo.py' -v
```

`overlay` and `radius` reuse the raster preparation path, so a change to
`commands/raster.py` must pass the raster, overlay and radius suites.

No pytest dependency is needed. The existing runtime dependencies supply
the NetCDF reader and PNG decoder. Fixtures and outputs are created under
the system temporary directory and removed after each test. Basemaps are
disabled, so no satellite archive, API key, or tile download is required.
The fixture configuration lists every data folder plus the boundary and
font paths, and is the only configuration the CLI reads: each process gets a
private `HOME`, so `~/.config/rsplot/config.toml` is never merged in.
Cartopy still reads its shapefile cache from the real
`~/.local/share/cartopy` (or `CARTOPY_DATA_DIR`).

For optional branch measurement, set `RSPLOT_E2E_COVERAGE_DIR` to an
existing temporary directory and run the same command with `coverage`
available, for example `uv run --with coverage python -B -m unittest ...`.
The launcher will instrument the real CLI script and save per-process
coverage data there. Combine the files with `coverage combine` and report the
command module separately from the entire application. This is not a
full-project coverage gate.

Known measurement artifact: after the plotting call returns, coverage stops
recording further lines in the calling command function (`run_raster`,
`run_overlay`), although they execute: every passing plot test reads the
JSON those lines write, and a plain `sys.settrace` probe sees them. Functions
called afterwards, such as result builders, are still recorded. The cause is
in the rendering stack and was not isolated. Figures below correct for it
where stated.

## Raster review results

Before application changes: 24 E2E tests, 21 passed and 3 failed:

- Help omitted explicit TROPOMI date semantics and incorrectly promised an
  interactive window when output was omitted.
- A date range silently overrode a simultaneously supplied `--days`.
- A single-day request with no regional coverage suggested the window-only
  `--n-min` option.

After fixes and seven additional GEMS scenarios: 31 tests passed. The review
also visually inspected a real gradient PNG whose JSON mean was 8, range
2–14 and coverage 16/16 cells. Ruff lint and format checks passed for the
touched Python files.

During the overlay review, one raster scenario was added. A single TROPOMI
day with `--smooth 1.5` reported 16 valid cells and 100% coverage instead of
10 cells and 62.5%, because single-day smoothing did not restore the
pre-smoothing valid mask. After the fix: 32 raster tests pass.

`raster` was then migrated to the `rsplot.result/2` sidecar
([docs/result-schema.md](../../docs/result-schema.md)). Every assertion now
reads the new schema, every sidecar (including error sidecars) is validated
against the shipped JSON Schema via the `jsonschema` dev dependency, and
rejected requests must leave only an error sidecar with a specific
`error.code`. Nine scenarios were added: input files, the statistical-grid
data file, smoothing/coverage/missing-day/unreadable-input quality flags,
request reproduction, unknown regions and missing data. 41 raster tests pass.
These tests were rewritten together with the implementation rather than
before it: the old JSON had none of the new fields, so every rewritten
assertion would fail against the unchanged application by construction.

Measured raster command coverage: 58/74 branches (78.4%), 192/218 statements
(88.1%), not corrected for the artifact above. The 90% branch target is not
met. Remaining cases include default output paths, HCHO-specific window
defaults, additional TROPOMI smoothing combinations, invalid color-range
paths, and guards reachable only through the shared Python preparation API.
Broader gaps include ZIP archives, network basemaps, additional
administrative geometries, GEMS products other than NO2, and rendering/I/O
failures. Do not treat these focused tests as full coverage of satellite
science or of the other CLI commands.

## Overlay review results

Scenarios were written before each change and run against the unchanged
application:

1. Smoothing: the same invented-cell bug as raster (10 → 16 valid cells).
   Overlay now builds its satellite layer with `prepare_raster` instead of a
   separate copy.
2. Default station variables: 4 of 6 scenarios failed (`o3`/`o3pr` paired
   with `O3`, TROPOMI `hcho` with `AQI`, GEMS `hcho` exited with an error).
3. Time semantics: 13 of 17 tests failed. `DATE` now follows `raster`
   (ranges, `--days`, `--n-min`), a TROPOMI `YYYYMMDDHH` is rejected,
   `--station-datetime` is required except for GEMS scans, and the latest
   station hour is never auto-selected.
4. `time_matching`: 3 of 4 scenarios failed (missing for TROPOMI days,
   TROPOMI windows and GEMS windows); the GEMS daily-mean record was
   unchanged.

After fixes: 21 overlay tests and 32 raster tests pass. Real-archive runs
(Hefei NO2, 2026-09-19) produced a PNG and JSON for one day and a 7-day
window; an hourly TROPOMI `DATE` was rejected. Ruff lint and format checks
passed for the touched Python files.

`overlay` was then migrated to `rsplot.result/2`. The 28 rewritten scenarios
(21 updated, 7 new: unknown station variable, GEMS hour override, station
table, colocation, in-region exceedances, comparison flags, few stations)
were written first and all 28 failed against the unchanged application.
After the migration all 28 pass, with 41 raster and 3 CLI tests. A real
Hefei NO2 overlay (2026-09-19, station hour 13:00) validated against the
schema with 6 colocated stations and Spearman 0.886. Not covered: a
non-null Spearman in the fixtures (they have two in-region stations),
multi-region station `by_member`, NRTI overlays, and variables without a
fixed station colour scale.

Measured overlay coverage, corrected for the artifact above:

| Module | Statements | Branches |
| --- | --- | --- |
| `commands/overlay.py` | 79/85 | 24/30 (80%) |
| `result_builders/overlay.py` | 16/23 | 6/10 (60%) |

The 90% branch target is not met. Uncovered behavior:

- A GEMS scan combined with `--days`/`--n-min`, and an unknown station
  variable (both rejections).
- A station variable without an exceedance threshold, such as `AQI`.
- `--processing nrti` overlays, including the JSON `sensor`/`processing`
  fields.
- Comma-separated multi-region overlays and station `member_stats`.
- The default `/tmp` output path and an explicit `--title`.

General error schemas, test-rule CI enforcement, coverage-drop gates and
scheduled full-suite runs remain separate follow-up work.

## Radius review results

`radius` had no suite. Its 12 scenarios were written against the
`rsplot.result/2` contract before the migration; against the unchanged
application 8 failed on the old JSON (no `schema`) and 4 rejections wrote no
error sidecar. After the migration all 12 pass, together with 41 raster, 28
overlay and 3 CLI tests. The old per-command raster block that `prepare_raster`
still built for radius was then removed, along with the old raster and radius
result builders.

The launcher now also drops `FORCE_COLOR` from the inherited environment:
it overrides `NO_COLOR`, colours help output and broke the CLI help scenario
in shells that set it.

Not covered: window and NRTI radius maps, GEMS location-only snapshots,
duplicate-station conflicts, centre stations outside every administrative
unit, and a non-null Spearman correlation (the square holds two stations).
No real-archive radius run was made for this migration.

## Station review results

`station` had no suite. Its 11 scenarios were written against the
`rsplot.result/2` contract first; against the unchanged application 6 failed
on the old JSON and 5 rejections (date-only and impossible hours, unknown
variable, missing hour, unknown region) wrote no error sidecar. After the
migration all 11 pass, with the 84 raster, overlay, radius and CLI tests.
The shared station layer now also reports AQI bands in `categories`, so
overlay and radius AQI layers carry them too.

Not covered: level overrides, multi-region selections (`station` resolves
one region), variables without a fixed colour scale other than AQI, and
stations with missing coordinates. No real-archive station run was made for
this migration.

## Trend review results

`trend` had no suite. Its 14 scenarios (8 single-station, 6 regional) were
written against `rsplot.result/2` first; against the unchanged application 8
failed on the old JSON and 6 rejections wrote no error sidecar. After the
migration all 14 pass, with the 95 other E2E tests. The station series
reader now raises coded errors for an unknown station (`region_not_found`)
and an unreadable variable (`read_failed`).

Not covered: multi-day windows (fixtures cover one day), more than 200 hourly
files (the source manifest path), unreadable hourly files, `--view mean`
rendering, and level overrides. No real-archive trend run was made.

## Recent review results

`recent` had no suite. Its 13 scenarios (5 satellite, 2 station, 1 empty
window, 5 rejections) were written against `rsplot.result/2` first; against
the unchanged application 8 failed on the old JSON and 5 rejections wrote no
error sidecar. After the migration all 13 pass, with the 109 other E2E tests.
Station summaries still take each day's latest available hour; the sidecar
records it, and the conventions step will remove it.

Not covered: GEMS and NRTI recent summaries, windows long enough for the
7/30-day comparisons, and unreadable files. No real-archive run was made.

## FNR review results

`fnr` had no suite. Its 13 scenarios were written against `rsplot.result/2`
first; against the unchanged application 7 failed on the old JSON and 6
rejections wrote no error sidecar. After the migration all 13 pass, with the
122 other E2E tests. `build_satellite_layer` gained `layer_id` and
`coverage_checks` so the NO2 and HCHO inputs reuse it.

Not covered: NRTI FNR, smoothing, mixed regimes within one map, subdivision
`by_admin` rows, and unreadable files. No real-archive run was made.

## Meteo review results

`meteo` had no suite. Its 13 scenarios use tiny ERA5 files in the real
archive layout (UTC day folders, descending latitude) plus a station hour.
Against the unchanged application 6 failed on the old JSON, 6 rejections
wrote no error sidecar, and the date-only request succeeded by choosing the
latest station hour. After the migration all 13 pass, with the 135 other
E2E tests; `meteo` now rejects date-only input in every mode. The ERA5 grid
reader raises a coded `data_not_found` when the requested hour is missing.

Not covered: pressure levels, temperature colour-range options, stride
auto-selection across region levels, `--basemap satellite`, and subdivision
`by_admin` rows.

A real-archive run (Hefei, 2026091913) then failed every meteo map with
`read_failed`: the real ERA5 files name the time coordinate `valid_time`,
while the reader and the fixtures used `time`. The fixtures now write
`valid_time`, and one scenario keeps the older `time` name; against the
unchanged reader 6 of 14 scenarios failed with the real error. The reader
accepts either name. All 14 pass, and the three real meteo maps (temperature,
wind with stations, all layers) succeed with schema-valid sidecars.

## CLI conventions

Rule 1 (data paths from configuration only): 12 scenarios were added to
`test_cli.py`, one per removed data-folder option, plus one for an
unconfigured product. All 13 failed against the unchanged application.
The command launchers stopped passing folder options; the fixture config
now lists every data folder. The unconfigured-product scenario then showed
that the user's `~/.config/rsplot/config.toml` was merged into every test
run (the test read the real NO2 archive); the launcher now gives each
process a private `HOME`.

Rule 2 (long option names only): 9 scenarios (one help check per command,
one rejected former alias) failed against the unchanged application. The 29
aliases were removed from `cli.py` and from each command's option table.
The help check also caught `-p`/`-o` in the usage examples printed by
`raster`, `overlay`, `station` and `recent` help; those now use long names.

Rule 3 (nothing that selects data is implicit): 14 CLI scenarios for a
missing `--output`, `--product`, `--var` or `--days`, plus overlay, trend,
FNR and recent scenarios, were written first. Against the unchanged
application all 14 CLI scenarios failed, every overlay scenario failed (no
`--station-var` option), and the trend, FNR and recent window/selection
rejections failed (a single date silently used a 7-day default; a range
silently ignored `--days`; recent defaulted to `o3`/`AQI`). The five
product-to-station-variable default scenarios were replaced by a required
`--station-var`, the removed `--var`, and an explicit GEMS HCHO pairing.

Rule 4 (`recent --source station` daily values): the station fixtures now
write 13:00 and 14:00 files. Against the unchanged application 4 of the 6
new station scenarios failed (it used each day's latest hour, recorded no
hour count, and counted exceedances against the hourly NO2 limit 200); the
missing-day and no-files scenarios already held and now guard the rewrite.
Each day is now the mean of all available hours; exceedances use the daily
limit.
