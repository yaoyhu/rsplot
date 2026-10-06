# Trend acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary hourly
station NetCDF, GeoJSON and TOML files. Read the saved PNG, JSON and NetCDF;
do not replace any rsplot function.

Every sidecar, successful or not, must validate against the shipped schema
`rsplot.result/2`. A rejected request exits nonzero, writes no PNG or data
file, and writes only an error sidecar with the stated `error.code`.

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
| user learns no files exist | No hourly files | Trend S001A | Rejected with `data_not_found` |
| user rejects an invalid date | 24 hourly files | Trend S001A for 20260230 | Rejected with `invalid_time` |
| user rejects a regional view for one station | 24 hourly files | Trend S001A with --view mean | Rejected with `invalid_argument` on option --view |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
