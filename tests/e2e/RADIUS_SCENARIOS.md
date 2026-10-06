# Radius acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary satellite
NetCDF, station NetCDF, GeoJSON and TOML files, with `--basemap none`. Read
the saved PNG, JSON and data files; do not replace any rsplot function.

Every sidecar, successful or not, must validate against the shipped schema
`rsplot.result/2`. A successful radius map has a `satellite` and a `station`
layer and a `station_radius` region. A rejected request exits nonzero,
writes no PNG or data file, and writes only an error sidecar with the stated
`error.code`.

Unless a scenario says otherwise, requests use centre station `C001A`
(117.5°E, 31.5°N, NO2 40), `--km 20`, TROPOMI NO2 on Jan 1 and the Jan 1
13:00 station file. Station `N002A` (NO2 80) lies about 7 km away inside the
square; `F003A` (NO2 999) lies about 60 km away outside it. Satellite orbits
on Jan 1 contain 2 and 4.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user maps a square around a station with values | Two orbits and the station file | Map with --station-var NO2 --station-datetime 2026010113 | A colored PNG; region kind `station_radius` centred on C001A with km 20 and side 40 km; satellite mean 3; station mean 60 from 2 stations at 2026010113 |
| user maps station locations only | One orbit and the station file | Map with --station-datetime 2026010113 and no --station-var | Station layer quantity `location` with 2 stations and no values; no time matching, no colocation, no station flags |
| user reads the radius station table | Same as the first scenario | Map with NO2 | The station CSV lists C001A and N002A only, with `is_center` 1 and 0, `distance_km` 0 for the centre and about 7 for the neighbour, and east/north offsets `dx_km`, `dy_km` |
| user sees satellite values at stations | Same as the first scenario | Map with NO2 | Colocation has 2 pairs, no Spearman correlation, incomparable units |
| user sees how the day meets the station hour | Same as the first scenario | Map with NO2 | Time matching by `period_mean_with_explicit_station_hour`, null difference, manual override |
| user is told what the comparison means | Same as the first scenario | Map with NO2 | Info flags `column_vs_surface` and `daily_vs_hourly` |
| user records the administrative context | Same as the first scenario | Map with NO2 | `region.radius.administrative_context.center_cities` is `["FixtureCity"]` |
| user matches a GEMS scan to the nearest station hour | A UTC 04:00 NO2 scan and the Jan 1 12:00 station file | Map local 202601011200 with --station-var NO2 | Station hour 2026010112; time matching by nominal scan time, 0 minutes |
| user names the station hour for a daily mean with values | The station file | Map with --station-var NO2 and no --station-datetime | Rejected with `invalid_argument` on option --station-datetime |
| user learns the centre station is unknown | The station file | Map station `ZZZ9A` | Rejected with `region_not_found`, naming ZZZ9A |
| user rejects a non-positive square | The station file | Map with --km 0 | Rejected with `invalid_argument` on option --km |
| user learns the station variable is unknown | The station file | Map with --station-var XYZ | Rejected with `invalid_argument` on option --station-var |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
