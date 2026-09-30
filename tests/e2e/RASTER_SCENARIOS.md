# Raster acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary NetCDF,
GeoJSON and TOML files, with `--basemap none`. Read the saved PNG and JSON;
do not replace any rsplot function. Expected numeric values below are chosen
by the fixtures, independently of rsplot's implementation.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user understands raster dates | CLI is installed | Request raster help | Explain TROPOMI single-day orbit aggregation, trailing/inclusive windows, GEMS scans, and file output |
| user plots one TROPOMI day | Two NO2 orbits on Jan 1 contain 2 and 4 at identical locations; Jan 2 contains 9 | Select Jan 1 | A colored PNG and JSON report Jan 1, 2 files, and mean 3 |
| user reads grouped products | Official PRODUCT-group NO2 input contains 4 | Plot that day | PNG and JSON mean 4 |
| user plots HCHO | HCHO input contains 6 in display units | Plot HCHO | PNG and JSON mean 6 with HCHO column units |
| user plots total ozone | O3 input contains 300 DU | Plot O3 | PNG and JSON mean 300 DU |
| user plots profile ozone | O3PR input contains 30 DU | Plot O3PR | PNG and JSON mean 30 DU |
| user averages days equally | Jan 1 has two orbits valued 2 and 4; Jan 2 has one valued 9 | Select Jan 2 with --days 2 | Window includes both days, default n-min is 2, mean is 6, not the pooled-pixel mean 5 |
| user includes both range endpoints | Same two-day archive | Select Jan 1–Jan 2 | Same window and mean 6 |
| user requests a one-day window | Jan 1 has two orbits valued 2 and 4 | Select Jan 1 with --days 1 | Window has one day, n-min 1, mean 3 |
| user distinguishes gap filling | Only one grid cell has observations in a larger region | Compare single day with --days 1 | Single day fills nearby holes; window retains observed-cell support |
| user keeps observed support while smoothing | One observed NO2 cell in a region too large for gap filling to cover | Plot one TROPOMI day with --smooth 0 and --smooth 1.5 | Both PNGs are produced and valid-cell count, total cells and coverage are identical; smoothing creates no observed cells |
| user sees missing-day diagnostics | Jan 1 is missing, Jan 2 has value 9 | Request two days with --n-min 1 | PNG and JSON mean 9, one found day, Jan 1 listed as failed |
| user enforces minimum valid days | Same incomplete archive | Request two days with default n-min | Nonzero exit and no PNG/JSON |
| user filters QA and clouds | Valid observations are 2; large outliers have QA at threshold or excessive cloud | Plot with --qa 0.5 --cf 0.5 | Mean 2; QA equality rejected and cloud equality retained |
| user sees partial unreadable inputs | One valid orbit and one corrupt file | Plot the day | PNG and JSON retain the valid values and report one broken file |
| user selects multiple regions | Two adjacent fixture regions and uniform observations | Select comma-separated regions | PNG and JSON contain both members and their statistics |
| user selects NRTI processing | Two versions of identical NRTI observations contain 2 and 4 | Plot with --processing nrti | Mean 4; JSON reports deduplication and UTC filename-date basis |
| user rejects competing window selectors | A valid archive | Supply a date range and --days together | Nonzero exit explaining the conflict, no PNG/JSON |
| user rejects hourly TROPOMI input | A valid archive | Supply YYYYMMDDHH | Nonzero exit explaining accepted date formats, no PNG/JSON |
| user rejects invalid calendar dates | A valid archive | Supply Feb 30 | Nonzero exit and no PNG/JSON |
| user rejects reversed ranges | A valid archive | Supply Jan 2–Jan 1 | Nonzero exit and no PNG/JSON |
| user rejects zero-day windows | A valid archive | Supply --days 0 | Nonzero exit and no PNG/JSON |
| user rejects n-min outside a window | A valid archive | Supply a single date and --n-min | Nonzero exit and no PNG/JSON |
| user rejects impossible n-min | A two-day archive | Supply --days 2 --n-min 3 | Nonzero exit and no PNG/JSON |
| user receives useful single-day coverage guidance | Observations exist only outside the selected region | Plot one day | Error identifies the requested day/region; does not suggest the unavailable single-day --n-min option |
| user selects a GEMS scan in China time | UTC Jan 1 04:00 and 05:00 scans contain 2 and 6 | Select local Jan 1 12:00 | PNG and JSON mean 2 with exact scan provenance |
| user averages GEMS scans equally | Those two scans belong to the same China-time day | Select Jan 1 | PNG and JSON mean 4 with two valid scans |
| user averages GEMS days equally | Jan 1 has scan values 2 and 6; Jan 2 has value 10 | Select Jan 2 with --days 2 | PNG and JSON mean 7, using equal days after equal scans |
| user preserves GEMS statistics while styling | A GEMS scan contains value 6 | Change smoothing and DPI | Both real PNGs are produced and JSON statistics are identical |
| user rejects TROPOMI QA for GEMS | GEMS is selected | Supply --qa | Nonzero exit and no PNG/JSON |
| user rejects a scan window | A GEMS exact scan is selected | Supply --days | Nonzero exit and no PNG/JSON |
| user rejects a scan valid-day threshold | A GEMS exact scan is selected | Supply --n-min | Nonzero exit and no PNG/JSON |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix. General exception
formatting, shared error schemas and other subcommands are outside this review.

Network basemaps, all GEMS products and footprint geometries, every
administrative level, and rendering failure paths need additional E2E
scenarios; no 90% branch coverage claim is made.
