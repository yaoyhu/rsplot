# Overlay acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary satellite
NetCDF, station NetCDF, GeoJSON and TOML files, with `--basemap none`. Read
the saved PNG, JSON and data files; do not replace any rsplot function.
Expected numeric values below are chosen by the fixtures, independently of
rsplot's implementation.

Every sidecar, successful or not, must validate against the shipped schema
`rsplot.result/2`. A successful overlay has two layers, `satellite` and
`station`. A rejected request exits nonzero, writes no PNG or data file, and
writes only an error sidecar with the stated `error.code`.

TROPOMI requests use DATE `20260101` and `--station-datetime 2026010113`
unless a scenario says otherwise. Station fixtures place two stations inside
`FixtureCity` (NO2 40 and 80) and one station in the adjacent `EastCity`
(NO2 999) that must be excluded from statistics.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user overlays one TROPOMI day with stations | Two NO2 orbits on Jan 1 contain 2 and 4; the Jan 1 13:00 station file has two in-region stations | Overlay Jan 1 with station hour 2026010113 | A colored PNG; satellite daily Jan 1 mean 3 from 2 files; station hour 2026010113 with mean 60 from 2 stations |
| user keeps observed satellite support while smoothing | One observed NO2 cell in a region too large for gap filling to cover | Overlay with --smooth 0 and --smooth 1.5 | Satellite valid cells, total cells and coverage fraction are identical |
| user gets surface NO2 for NO2 columns | TROPOMI NO2 and a station file | Overlay NO2 without --var | Station quantity is NO2 |
| user gets MDA8 ozone for total ozone | TROPOMI O3 and a station file | Overlay O3 without --var | Station quantity is O3_8h_24h |
| user gets MDA8 ozone for profile ozone | TROPOMI O3PR and a station file | Overlay O3PR without --var | Station quantity is O3_8h_24h |
| user gets MDA8 ozone for TROPOMI HCHO | TROPOMI HCHO and a station file | Overlay HCHO without --var | Station quantity is O3_8h_24h, not AQI |
| user gets MDA8 ozone for GEMS HCHO | A GEMS HCHO scan and the matched station hour | Overlay the scan without --var | Station quantity is O3_8h_24h |
| user selects a station variable explicitly | TROPOMI O3 and a station file | Overlay O3 with --var O3 | Station quantity is O3 |
| user learns the station variable is unknown | TROPOMI data and a station file | Overlay with --var XYZ | Rejected with `invalid_argument` on option --var |
| user rejects hourly TROPOMI dates | TROPOMI data and a station file | Supply DATE 2026010113 | Rejected with `invalid_time`, naming YYYYMMDD |
| user names the station hour for a TROPOMI day | TROPOMI data and a station file | Overlay Jan 1 without --station-datetime | Rejected with `invalid_argument` on option --station-datetime |
| user rejects a date-only station hour | TROPOMI data and a station file | Supply --station-datetime 20260101 | Rejected with `invalid_time` on option --station-datetime, naming YYYYMMDDHH |
| user never gets an automatically chosen station hour | Only the Jan 1 23:00 station file exists | Overlay Jan 1 with station hour 2026010113 | Rejected with `data_not_found`, naming 2026010113 |
| user overlays a TROPOMI window mean | Jan 1 orbits contain 2 and 4; Jan 2 contains 9; Jan 2 13:00 stations | Overlay Jan 2 with --days 2 and station hour 2026010213 | Satellite mean 6 from 2 found days, window ending Jan 2; station hour 2026010213 |
| user rejects competing window selectors | TROPOMI data and a station file | Supply a date range and --days together | Rejected with `invalid_argument` on option --days |
| user matches a GEMS scan to the nearest station hour | A UTC 04:00 NO2 scan and the Jan 1 12:00 station file | Overlay local 202601011200 without --station-datetime | Station hour 2026010112; time matching by nominal scan time, 0 minutes, not a manual override |
| user learns a GEMS scan hour was overridden | A UTC 04:00 NO2 scan and the Jan 1 13:00 station file | Overlay the scan with --station-datetime 2026010113 | Time difference 60 minutes, manual override, and a `manual_time_override` flag |
| user names the station hour for a GEMS day | A GEMS scan and a station file | Overlay GEMS daily mean Jan 1 without --station-datetime | Rejected with `invalid_argument` on option --station-datetime |
| user overlays a GEMS window mean | Jan 1 scans contain 2 and 6; Jan 2 contains 10; Jan 2 12:00 stations | Overlay Jan 2 with --days 2 and station hour 2026010212 | Satellite mean 7; station hour 2026010212 |
| user sees how a TROPOMI day meets its station hour | TROPOMI Jan 1 data and the Jan 1 13:00 station file | Overlay Jan 1 | Time matching pairs satellite and station by `period_mean_with_explicit_station_hour`, null difference, manual override |
| user sees how a TROPOMI window meets its station hour | TROPOMI data on Jan 1 and Jan 2; Jan 2 13:00 stations | Overlay Jan 1–Jan 2 with station hour 2026010213 | Satellite time is a Jan 1–Jan 2 window mean on UTC filename dates |
| user sees how a GEMS window meets its station hour | GEMS scans on Jan 1 and Jan 2; Jan 2 12:00 stations | Overlay Jan 2 with --days 2 and station hour 2026010212 | Satellite time is a window mean on China-time days; null time difference |
| user sees how a GEMS daily mean meets its station hour | A GEMS Jan 1 scan and Jan 1 12:00 stations | Overlay GEMS daily mean Jan 1 with station hour 2026010112 | Time matching by `daily_mean_with_explicit_station_hour`, null difference, manual override |
| user reads the station table | TROPOMI Jan 1 data and the station file | Overlay Jan 1 | The station CSV lists all three stations read, with values 40, 80 and 999 and `in_region` 1, 1, 0 |
| user sees satellite values at stations | Uniform satellite value 4 and the station file | Overlay Jan 1 | Colocation has 2 pairs, no Spearman correlation (fewer than 3 pairs), incomparable units; the CSV gives satellite value 4 and `colocated` 1 for both in-region stations and `colocated` 0 for the outside one |
| user counts exceedances only inside the region | The outside station's 999 exceeds the NO2 hourly limit | Overlay Jan 1 | Station exceedance count is 0 with threshold 200 |
| user is told what the comparison means | TROPOMI Jan 1 data and the station file | Overlay Jan 1 | Info flags `column_vs_surface` and `daily_vs_hourly` |
| user is warned about few stations | Two valid stations in the region | Overlay Jan 1 | Warning `few_stations`; grade `limited` |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
