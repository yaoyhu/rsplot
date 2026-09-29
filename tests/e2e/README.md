# Raster E2E review

Acceptance scenarios are in [RASTER_SCENARIOS.md](RASTER_SCENARIOS.md).
Each test launches the installed `rsplot` console command in a separate
process. Fixtures are real temporary NetCDF, GeoJSON and TOML files, with
deterministic values and no mocks. Successful plotting scenarios decode the
PNG, check for colored content, and read the persisted JSON. Rejected
requests must not leave output files.

Run only this command's E2E tier locally:

```bash
uv run python -B -m unittest discover -s tests/e2e -p 'test_raster.py' -v
```

No pytest dependency is needed. The existing runtime dependencies supply
the NetCDF reader and PNG decoder. Fixtures and outputs are created under
the system temporary directory and removed after each test. Basemaps are
disabled, so no satellite archive, API key, or tile download is required.
The fixture configuration overrides data/boundary/font paths; it follows
the application's normal config-loading rules, so a malformed user config
can still prevent startup.

For optional branch measurement, install `coverage` in the test interpreter
and set `RSPLOT_E2E_COVERAGE_DIR` to an existing temporary directory before
running the same command. The launcher will instrument the real CLI script
and save per-process coverage data there. Combine the files with
`coverage combine` and report `src/rsplot/commands/raster.py` separately from
the entire application. This is not a full-project coverage gate.

## Review results

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

Measured raster command coverage: 58/74 branches (78.4%), 192/218 statements
(88.1%). The 90% branch target is not met. Remaining cases include default
output paths, HCHO-specific window defaults, additional TROPOMI smoothing
combinations, invalid color-range paths, and guards reachable only through
the shared Python preparation API. Broader gaps include ZIP archives,
network basemaps, additional administrative geometries, GEMS products other
than NO2, and rendering/I/O failures. Do not treat these focused tests as
full coverage of satellite science or of the other CLI commands.

General error schemas, test-rule CI enforcement, coverage-drop gates and
scheduled full-suite runs remain separate follow-up work.
