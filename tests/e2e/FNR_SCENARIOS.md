# FNR acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary TROPOMI
NO2 and HCHO NetCDF, GeoJSON and TOML files, with `--basemap none`. Read the
saved PNG, JSON and NetCDF files; do not replace any rsplot function.

Every sidecar, successful or not, must validate against the shipped schema
`rsplot.result/2`. A successful map has `no2`, `hcho` and `fnr` grid layers.
A rejected request exits nonzero, writes no PNG or data file, and writes only
an error sidecar with the stated `error.code`.

Unless a scenario says otherwise, Jan 1–3 have uniform NO2 2 and HCHO 6
(×10¹⁵ molec/cm²) over `FixtureCity` (16 grid cells at 0.25°), and requests
cover the 3 days ending Jan 3 with the default n-min of 3, so FNR is 3.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user maps the FNR regime | Three days of NO2 2 and HCHO 6 | Map FNR | A colored PNG; layers `no2` (mean 2), `hcho` (mean 6) and `fnr` (mean 3, unit 1) over a Jan 1–3 window mean on UTC filename dates; FNR covers 16 of 16 cells |
| user counts cells per regime | Same inputs | Map FNR | `fnr.categories` has 16 `nox_limited`, 0 `transition`, 0 `voc_limited` |
| user changes regime thresholds | Same inputs | Map with --voc-threshold 4 --nox-threshold 5 --display-max 6 | `fnr.categories` has 16 `voc_limited`; render records the thresholds |
| user loads the FNR grids | Same inputs | Map FNR | Three NetCDF files; the FNR file's mean over counted cells is 3 with 3 valid days per cell |
| user reads the masking diagnostics | Same inputs | Map FNR | `fnr.method.mask_counts.final_valid` is 16 and the NO2 floor is 0.5 |
| user finds both products' input files | Same inputs | Map FNR | `no2` and `hcho` each list 3 source files |
| user is warned about missing days | HCHO missing on Jan 2 | Map with --n-min 2 | `hcho` found 2 of 3 days; warning `missing_days` on `hcho`; FNR still mean 3 |
| user masks a low NO2 background | Same inputs | Map with --no2-min 3 | Rejected with `no_valid_data` |
| user rejects an invalid date | Same inputs | Map ending 20260230 | Rejected with `invalid_time` |
| user rejects a zero-day window | Same inputs | Map with --days 0 | Rejected with `invalid_argument` on option --days |
| user rejects an impossible n-min | Same inputs | Map with --n-min 5 | Rejected with `invalid_argument` on option --n-min |
| user rejects crossed thresholds | Same inputs | Map with --voc-threshold 3 --nox-threshold 2 | Rejected with `invalid_argument` |
| user learns the region does not exist | Same inputs | Map region Atlantis | Rejected with `region_not_found` |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
