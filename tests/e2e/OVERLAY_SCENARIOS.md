# Overlay acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary satellite
NetCDF, station NetCDF, GeoJSON and TOML files, with `--basemap none`. Read
the saved PNG and JSON; do not replace any rsplot function. Expected numeric
values below are chosen by the fixtures, independently of rsplot's
implementation.

TROPOMI requests use DATE `20260101` and `--station-datetime 2026010113`
unless a scenario says otherwise. Station fixtures place two stations inside `FixtureCity` (NO2 40 and 80) and
one station in the adjacent `EastCity` (NO2 999) that must be excluded.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user overlays one TROPOMI day with stations | Two NO2 orbits on Jan 1 contain 2 and 4; the Jan 1 13:00 station file has two in-region stations | Overlay Jan 1 with station hour 2026010113 | A colored PNG and JSON report satellite mean 3 from 2 files, and station mean 60 from 2 stations at 2026010113 |
| user keeps observed satellite support while smoothing | One observed NO2 cell in a region too large for gap filling to cover | Overlay with --smooth 0 and --smooth 1.5 | Both PNGs are produced and the satellite valid-cell count, total cells and coverage are identical; smoothing creates no observed cells |
| user gets surface NO2 for NO2 columns | TROPOMI NO2 and a station file | Overlay NO2 without --var | JSON station variable is NO2 |
| user gets MDA8 ozone for total ozone | TROPOMI O3 and a station file | Overlay O3 without --var | JSON station variable is O3_8h_24h |
| user gets MDA8 ozone for profile ozone | TROPOMI O3PR and a station file | Overlay O3PR without --var | JSON station variable is O3_8h_24h |
| user gets MDA8 ozone for TROPOMI HCHO | TROPOMI HCHO and a station file | Overlay HCHO without --var | JSON station variable is O3_8h_24h, not AQI |
| user gets MDA8 ozone for GEMS HCHO | A GEMS HCHO scan and the matched station hour | Overlay the scan without --var | PNG and JSON are produced with station variable O3_8h_24h |
| user selects a station variable explicitly | TROPOMI O3 and a station file | Overlay O3 with --var O3 | JSON station variable is O3 |
| user rejects hourly TROPOMI dates | TROPOMI data and a station file | Supply DATE 2026010113 | Nonzero exit naming YYYYMMDD, no PNG/JSON |
| user names the station hour for a TROPOMI day | TROPOMI data and a station file | Overlay Jan 1 without --station-datetime | Nonzero exit naming --station-datetime, no PNG/JSON |
| user rejects a date-only station hour | TROPOMI data and a station file | Supply --station-datetime 20260101 | Nonzero exit naming YYYYMMDDHH, no PNG/JSON |
| user never gets an automatically chosen station hour | Only the Jan 1 23:00 station file exists | Overlay Jan 1 with station hour 2026010113 | Nonzero exit naming 2026010113, no PNG/JSON |
| user overlays a TROPOMI window mean | Jan 1 orbits contain 2 and 4; Jan 2 contains 9; Jan 2 13:00 stations | Overlay Jan 2 with --days 2 and station hour 2026010213 | Satellite mean 6 from 2 days; JSON date 20260102 and station datetime 2026010213 |
| user rejects competing window selectors | TROPOMI data and a station file | Supply a date range and --days together | Nonzero exit naming --days, no PNG/JSON |
| user matches a GEMS scan to the nearest station hour | A UTC 04:00 NO2 scan and the Jan 1 12:00 station file | Overlay local 202601011200 without --station-datetime | Station datetime 2026010112, time difference 0 minutes, not a manual override |
| user names the station hour for a GEMS day | A GEMS scan and a station file | Overlay GEMS daily mean Jan 1 without --station-datetime | Nonzero exit naming --station-datetime, no PNG/JSON |
| user overlays a GEMS window mean | Jan 1 scans contain 2 and 6; Jan 2 contains 10; Jan 2 12:00 stations | Overlay Jan 2 with --days 2 and station hour 2026010212 | Satellite mean 7 (equal days after equal scans); station datetime 2026010212 |
| user sees how a TROPOMI day meets its station hour | TROPOMI Jan 1 data and the Jan 1 13:00 station file | Overlay Jan 1 | JSON time_matching records the UTC filename-date day, station hour 2026010113 in Asia/Shanghai, null time difference and a manual override |
| user sees how a TROPOMI window meets its station hour | TROPOMI data on Jan 1 and Jan 2; Jan 2 13:00 stations | Overlay Jan 1–Jan 2 with station hour 2026010213 | JSON time_matching records a Jan 1–Jan 2 window mean on UTC filename dates |
| user sees how a GEMS window meets its station hour | GEMS scans on Jan 1 and Jan 2; Jan 2 12:00 stations | Overlay Jan 2 with --days 2 and station hour 2026010212 | JSON time_matching records a Jan 1–Jan 2 window mean on China-time days, with null time difference |
| user keeps the GEMS daily-mean pairing record | A GEMS Jan 1 scan and Jan 1 12:00 stations | Overlay GEMS daily mean Jan 1 with station hour 2026010112 | JSON time_matching keeps the existing daily-mean record unchanged |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
