# Raster acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary NetCDF,
GeoJSON and TOML files, with `--basemap none`. Read the saved PNG, JSON and
data files; do not replace any rsplot function. Expected numeric values below
are chosen by the fixtures, independently of rsplot's implementation.

Every sidecar must validate against the shipped schema
`src/rsplot/schemas/result.schema.json`. "Mean" and other values refer to
the `satellite` layer. A rejected request exits 1, prints one `rsplot error
<code>` line on stderr with the stated code (and option), and leaves no PNG,
JSON or data file.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user understands raster dates | CLI is installed | Request raster help | Explain TROPOMI single-day orbit aggregation, trailing/inclusive windows, GEMS scans, and file output |
| user plots one TROPOMI day | Two NO2 orbits on Jan 1 contain 2 and 4; Jan 2 contains 9 | Select Jan 1 | A colored PNG; time is a daily UTC filename date Jan 1; 2 source files; mean 3 |
| user counts the input files | Two NO2 orbits on Jan 1 | Select Jan 1 | `source` has the configured data root, sensor `tropomi`, processing `offl` and `files_total` 2, with no file list or manifest; the output folder holds only the PNG, JSON and satellite NetCDF |
| user loads the statistical grid | Two NO2 orbits on Jan 1 contain 2 and 4 | Select Jan 1 | The NetCDF named by the layer's `data` exists, has nonzero size, and its mean over `counted` cells is 3 with as many counted cells as `coverage.total` |
| user reads grouped products | Official PRODUCT-group NO2 input contains 4 | Plot that day | Mean 4 |
| user plots HCHO | HCHO input contains 6 in display units | Plot HCHO | Mean 6; quantity `tropospheric_hcho_column` in molec/cm2 with scale 1e15 |
| user plots total ozone | O3 input contains 300 DU | Plot O3 | Mean 300; unit DU, scale 1 |
| user plots profile ozone | O3PR input contains 30 DU | Plot O3PR | Mean 30; unit DU |
| user averages days equally | Jan 1 has two orbits valued 2 and 4; Jan 2 has one valued 9 | Select Jan 2 with --days 2 | Window Jan 1–Jan 2, equal-day weighting, mean 6, not the pooled-pixel mean 5 |
| user includes both range endpoints | Same two-day archive | Select Jan 1–Jan 2 | Two days found and mean 6 |
| user requests a one-day window | Jan 1 has two orbits valued 2 and 4 | Select Jan 1 with --days 1 | One requested day, mean 3 |
| user distinguishes gap filling | Only one grid cell has observations in a larger region | Compare single day with --days 1 | Single day fills nearby holes; window retains observed-cell support (1 valid cell) |
| user keeps observed support while smoothing | One observed NO2 cell in a region too large for gap filling to cover | Plot one TROPOMI day with --smooth 0 and --smooth 1.5 | Valid cells, total cells and coverage fraction are identical; smoothing creates no observed cells |
| user reads smoothing from the method | Uniform NO2 input | Plot with --smooth 1 | `method.smoothing_sigma` is 1 and there is no flag |
| user is warned when coverage is too low | One observed cell of 16 region cells | Plot a one-day window | `quality` is exactly one flag: `very_low_coverage`, critical, layer satellite, evidence valid 1, total 16, fraction 0.062, threshold 0.1; no grade and no message |
| user sees missing-day diagnostics | Jan 1 is missing, Jan 2 has value 9 | Request two days | Mean 9, one found day, Jan 1 listed under the window's failed days |
| user is warned about missing days | Same incomplete archive | Request two days | The only flag is `missing_days` (warning, satellite) with evidence requested 2, found 1 and Jan 1 under failed; no message |
| user keeps cells with one valid day | Jan 1 is valued 2 in all 16 cells; Jan 2 is valued 18 in one cell only | Request two days | All 16 cells valid; the twice-observed cell averages 10 and the others keep 2, so the mean is 2.5, not 1.5625 as with missing days counted as zero; valid days per cell range 1–2 and the minimum valid days recorded is 1 |
| user keeps unobserved cells empty | Jan 1 and Jan 2 are each valued in the same one cell (4 and 8) | Request two days | 1 of 16 cells valid with mean 6; the 15 unobserved cells are NaN in the layer's NetCDF, not 0 |
| user filters QA and clouds | Valid observations are 2; large outliers have QA at threshold or excessive cloud | Plot with --qa 0.5 --cf 0.5 | Mean 2 from 16 pixels; QA equality rejected and cloud equality retained; method records both thresholds |
| user sees partial unreadable inputs | One valid orbit and one corrupt file | Plot the day | Mean 4; the corrupt file is the only entry in `failed_files` |
| user is warned about unreadable inputs | Same inputs | Plot the day | The only flag is `failed_files`; `quality` has no grade |
| user reproduces a request | Uniform NO2 input; QA threshold only in config | Plot with --res 0.25 | `request` is the command as one line, `rsplot raster FixtureCity 20260101 ... --output <path>`; `method` records grid 0.25 and the config QA 0.5 |
| user reads a quoted title in the command line | Uniform NO2 input | Plot with --title "NO2 map" | `request` ends with `--title 'NO2 map'`; other arguments stay unquoted |
| user reads the region bounding box | Uniform NO2 input | Plot FixtureCity | `region.bbox` is [117, 118, 31, 32]; there is no `extent` |
| user selects multiple regions | Two adjacent fixture regions and uniform observations | Select comma-separated regions | Region has both members; the layer has two `by_member` rows |
| user selects NRTI processing | Two versions of identical NRTI observations contain 2 and 4 | Plot with --processing nrti | Mean 4; processing `nrti`; 16 duplicates removed; UTC filename-date basis |
| user rejects competing window selectors | A valid archive | Supply a date range and --days together | Rejected with `invalid_argument` on option --days |
| user rejects hourly TROPOMI input | A valid archive | Supply YYYYMMDDHH | Rejected with `invalid_time`, naming accepted date formats |
| user rejects invalid calendar dates | A valid archive | Supply Feb 30 | Rejected with `invalid_time` |
| user rejects reversed ranges | A valid archive | Supply Jan 2–Jan 1 | Rejected with `invalid_time` |
| user rejects zero-day windows | A valid archive | Supply --days 0 | Rejected with `invalid_argument` |
| user receives useful single-day coverage guidance | Observations exist only outside the selected region | Plot one day | Rejected with `no_valid_data`; the message names the day and does not suggest a window |
| user receives useful window coverage guidance | Observations exist only outside the selected region | Plot a one-day window | Rejected with `no_valid_data`; the message names the window and does not suggest a valid-day threshold |
| user learns a region does not exist | A valid archive | Plot region "Atlantis" | Rejected with `region_not_found` |
| user learns data is missing | Only Jan 2 data exists | Plot Jan 1 | Rejected with `data_not_found` |
| user selects a GEMS scan in China time | UTC Jan 1 04:00 and 05:00 scans contain 2 and 6 | Select local Jan 1 12:00 | Mean 2; time is scan 202601011200 in Asia/Shanghai, nominal scan basis, archive time 202601010400 UTC; one scan found |
| user averages GEMS scans equally | Those two scans belong to the same China-time day | Select Jan 1 | Mean 4 from two valid scans; daily scan-mean aggregation |
| user averages GEMS days equally | Jan 1 has scan values 2 and 6; Jan 2 has value 10 | Select Jan 2 with --days 2 | Mean 7, equal scans then equal days, China-time day basis |
| user preserves GEMS statistics while styling | A GEMS scan contains value 6 | Change smoothing and DPI | Both PNGs are produced and statistics are identical |
| user rejects TROPOMI QA for GEMS | GEMS is selected | Supply --qa | Rejected with `invalid_argument` |
| user rejects a scan window | A GEMS exact scan is selected | Supply --days | Rejected with `invalid_argument` |

Window means are per-cell means over valid days: missing or invalid days
are skipped, never counted as zero; each valid day has equal weight; a cell
with at least one valid day keeps its mean and a cell with none is nodata.
There is no minimum-valid-days option.

Argument errors detected by the CLI parser itself (unknown options, values
outside a declared range) exit 2 before `--output` is known and therefore
write no sidecar.

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix. General exception
formatting, shared error schemas and other subcommands are outside this review.

Network basemaps, all GEMS products and footprint geometries, every
administrative level, and rendering failure paths need additional E2E
scenarios; no 90% branch coverage claim is made.
