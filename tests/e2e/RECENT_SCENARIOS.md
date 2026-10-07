# Recent acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary satellite
and station NetCDF, GeoJSON and TOML files. `recent` draws no image: read the
JSON written at `--output` and its daily CSV; do not replace any rsplot
function.

Every sidecar must validate against the shipped schema
`src/rsplot/schemas/result.schema.json`. A successful run has one daily
`series` layer, no image and no render block. A rejected request exits 1,
prints one `rsplot error <code>` line on stderr with the stated code (and
option), and leaves no PNG, JSON or data file.

Requests cover the 3 days ending Jan 3 in `FixtureCity`. Satellite fixtures
are uniform NO2 swaths valued 2, 4 and 6 on Jan 1–3. Station fixtures have
13:00 and 14:00 files per day; the in-region stations read 40 + d and 80 + d
at 13:00 and 20 more at 14:00, for day offsets d = 0, 10, 20, and an outside
station reads 999. A station's day is the mean of its available hours, so
the station daily means are 50 + d and 90 + d and the regional daily values
70, 80 and 90.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user summarizes recent satellite days | Three daily swaths | Summarize raster NO2 | Layer `satellite`, kind `series`, daily series Jan 1–3 on UTC filename dates, 3 of 3 days, mean 4; no image, no render |
| user loads the daily table | Three daily swaths | Summarize raster NO2 | The daily CSV has three rows with values 2, 4 and 6, all `ok` |
| user sees the recent trend | Three daily swaths | Summarize raster NO2 | `temporal_summary.trend` has slope 2 per day, direction up |
| user is warned about missing days | Swaths on Jan 1 and Jan 3 only | Summarize raster NO2 | Coverage 2 of 3 days, warning `missing_days`, grade `limited`; the Jan 2 CSV row is not `ok` and has an error |
| user finds every input file | Three daily swaths | Summarize raster NO2 | `source.files` lists the three swath files |
| user summarizes recent station days | Two hourly files per day | Summarize station NO2 | Layer `station`, quantity NO2 in ug/m3, mean 80; method `station_daily_value` is `mean_of_available_hours` |
| user reads each station day | Two hourly files per day | Summarize station NO2 | The daily CSV values are 70, 80, 90, each from 2 hours |
| user summarizes a day with missing hours | Jan 3 has only its 13:00 file | Summarize station NO2 | Jan 3 is 80 from 1 hour; Jan 1 and 2 are 70 and 80 from 2 hours |
| user is warned about a day without station files | No Jan 2 files | Summarize station NO2 | Coverage 2 of 3 days, warning `missing_days`; the Jan 2 CSV row is not `ok` |
| user counts daily exceedances against the daily limit | Two hourly files per day | Summarize station NO2 | `method.daily_limit` is 80 (NO2 daily limit, not the hourly 200); one station exceeds it each day |
| user is told no station files exist | No station files | Summarize station NO2 | Status ok, 0 of 3 days, flag `no_valid_data` |
| user is told nothing was found | No swaths | Summarize raster NO2 | Status ok, 0 of 3 days, flag `no_valid_data`, grade `unreliable` |
| user rejects an invalid end date | Three daily swaths | Summarize ending 20260230 | Rejected with `invalid_time` |
| user rejects an unknown source | Three daily swaths | Summarize with --source radar | Rejected with `invalid_argument` on option --source |
| user rejects GEMS for station summaries | Three daily station files | Station summary with --sensor gems | Rejected with `invalid_argument` on option --sensor |
| user learns the station variable is unknown | Three daily station files | Station summary with --var XYZ | Rejected with `invalid_argument` on option --var |
| user learns the region does not exist | Three daily swaths | Summarize region Atlantis | Rejected with `region_not_found` |
| user summarizes one region at a time | Three daily swaths | Summarize `FixtureCity,EastCity` | Rejected with `invalid_argument`; the message says to run once per region and `details.regions` lists FixtureCity and EastCity |
| user names the product for satellite summaries | Three daily swaths | Summarize with --source raster and no --product | Rejected with `invalid_argument` on option --product |
| user names the variable for station summaries | Three daily station files | Summarize with --source station and no --var | Rejected with `invalid_argument` on option --var |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
