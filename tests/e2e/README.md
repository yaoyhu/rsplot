# E2E reviews

Acceptance scenarios are in [RASTER_SCENARIOS.md](RASTER_SCENARIOS.md) and
[OVERLAY_SCENARIOS.md](OVERLAY_SCENARIOS.md).
Each test launches the installed `rsplot` console command in a separate
process. Fixtures are real temporary NetCDF, GeoJSON and TOML files, with
deterministic values and no mocks. Successful plotting scenarios decode the
PNG, check for colored content, and read the persisted JSON. Rejected
requests must not leave output files.

Run only the affected command's E2E tier locally:

```bash
uv run python -B -m unittest discover -s tests/e2e -p 'test_raster.py' -v
uv run python -B -m unittest discover -s tests/e2e -p 'test_overlay.py' -v
```

`overlay` and `radius` reuse the raster preparation path, so a change to
`commands/raster.py` must pass both suites.

No pytest dependency is needed. The existing runtime dependencies supply
the NetCDF reader and PNG decoder. Fixtures and outputs are created under
the system temporary directory and removed after each test. Basemaps are
disabled, so no satellite archive, API key, or tile download is required.
The fixture configuration overrides data/boundary/font paths; it follows
the application's normal config-loading rules, so a malformed user config
can still prevent startup.

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
