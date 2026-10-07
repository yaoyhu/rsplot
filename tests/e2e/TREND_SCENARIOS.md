# Trend acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary hourly
station NetCDF, GeoJSON and TOML files. Read the saved PNG, JSON and NetCDF;
do not replace any rsplot function.

Every sidecar must validate against the shipped schema
`src/rsplot/schemas/result.schema.json`. A rejected request exits 1, prints
one `rsplot error <code>` line on stderr with the stated code (and option),
and leaves no PNG, JSON or data file.

Unless a scenario says otherwise, Jan 1 has 24 hourly files. Inside
`FixtureCity`, station S001A reads 10 + h and S002A reads 20 + h at hour h;
S003A in `EastCity` reads 999. Requests use `--days 1 --var NO2`.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user plots one station's hours | 24 hourly files | Trend S001A for Jan 1 | A PNG; no region; one `series` layer for station S001A, 24 of 24 hours valid, mean 21.5, hourly series on Jan 1 in Asia/Shanghai |
| user loads the hourly series | 24 hourly files | Trend S001A | The series NetCDF holds 1 station × 24 hours, first hour 2026010100 with value 10 |
| user is warned about missing hours | Only hours 00–11 exist | Trend S001A | Coverage 12 of 24 hours; warning `missing_hours`; grade `limited` |
| user overrides the exceedance threshold | 24 hourly files | Trend S001A with --threshold 30 | Exceedance threshold 30 counts 3 hours, standard says it came from --threshold |
| user plots a regional trend | 24 hourly files | Trend FixtureCity with --region | Region FixtureCity; `regional_mean` layer with mean 26.5 over 24 hours; `station` layer with 2 stations |
| user loads every station's hours | 24 hourly files | Trend FixtureCity with --region | The series NetCDF holds 2 stations × 24 hours plus the regional mean, first mean 15 |
| user highlights a focus station | 24 hourly files | Regional trend with --focus-station S002A | `render.layers.station.focus_station_ids` is ["S002A"] |
| user is warned about few stations | 24 hourly files | Regional trend | Warning `few_stations`; grade `limited` |
| user learns a focus station is outside the region | 24 hourly files | Regional trend with --focus-station S003A | Rejected with `invalid_argument` on option --focus-station |
| user learns the station does not exist | 24 hourly files | Trend ZZZ9A | Rejected with `region_not_found`, naming ZZZ9A |
| user learns the region does not exist | 24 hourly files | Trend Atlantis with --region | Rejected with `region_not_found` |
| user trends one region at a time | 24 hourly files | Trend `FixtureCity，EastCity` (Chinese comma) with --region | Rejected with `invalid_argument`; the message says to run once per region and `details.regions` lists FixtureCity and EastCity |
| user learns no files exist | No hourly files | Trend S001A | Rejected with `data_not_found` |
| user rejects an invalid date | 24 hourly files | Trend S001A for 20260230 | Rejected with `invalid_time` |
| user rejects a regional view for one station | 24 hourly files | Trend S001A with --view mean | Rejected with `invalid_argument` on option --view |
| user names the window for a single date | 24 hourly files | Trend S001A 20260101 without --days | Rejected with `invalid_argument` on option --days |
| user plots an explicit date range | 24 hourly files | Trend S001A 20260101-20260101 without --days | A PNG; the series runs from 20260101 to 20260101 |
| user cannot combine a date range with days | 24 hourly files | Trend S001A 20260101-20260101 with --days 1 | Rejected with `invalid_argument` on option --days |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
