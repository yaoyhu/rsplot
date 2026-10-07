# Meteo acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary ERA5 and
station NetCDF, GeoJSON and TOML files, with `--basemap none`. Read the saved
PNG, JSON and data files; do not replace any rsplot function.

Every sidecar must validate against the shipped schema
`src/rsplot/schemas/result.schema.json`. A rejected request exits 1, prints
one `rsplot error <code>` line on stderr with the stated code (and option),
and leaves no PNG, JSON or data file.

Unless a scenario says otherwise, the request hour is 2026010113 China time,
which is the ERA5 UTC hour 2026010105. ERA5 fixtures are uniform 293.15 K
2 m temperature and 10 m wind u = 3, v = 4 m/s on a 0.25° grid. Like the
real archive, they name the time coordinate `valid_time`. The station
file for 2026010113 has two in-region stations (NO2 40 and 80) and one
outside.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user maps temperature | 2 m temperature | Map with --temp-level 2m | A colored PNG; one `temperature` grid layer, mean 20 °C, hourly at 2026010113 Asia/Shanghai on the ERA5 hour basis with archive time 2026010105 UTC; no relations |
| user maps temperature from older files | 2 m temperature whose time coordinate is named `time` | Map with --temp-level 2m | A PNG; `temperature` mean 20 °C |
| user maps wind | 10 m wind | Map with --wind-level 10m | One `wind` vector_grid layer, mean speed 5 m/s; `vector_summary` gives wind from 216.9° |
| user loads the wind grid | 10 m wind | Map with --wind-level 10m | The wind NetCDF holds `u` 3, `v` 4 and `value` (speed) 5 |
| user maps all three layers | Temperature, wind and the station file | Map with --temp-level 2m --wind-level 10m --station-var NO2 | Layers `temperature`, `wind`, `station`; station mean 60; time matching pairs wind and station at the same hour, 0 minutes |
| user records the wind drawing | 10 m wind | Map with --wind-level 10m --wind-stride 2 | `render.layers.wind` records stride 2 and no colorbar |
| user rejects a date-only hour | Wind and the station file | Map 20260101 with --wind-level 10m --station-var NO2 | Rejected with `invalid_time`; no latest station hour is chosen |
| user needs wind for a station layer | The station file | Map with --temp-level 2m --station-var NO2 | Rejected with `invalid_argument` on option --station-var |
| user names at least one layer | ERA5 files | Map with no level | Rejected with `invalid_argument` |
| user learns a level is unsupported | ERA5 files | Map with --temp-level 333 | Rejected with `invalid_argument` on option --temp-level |
| user styles temperature only when drawn | Wind | Map with --wind-level 10m --cmap viridis | Rejected with `invalid_argument` on option --cmap |
| user learns the ERA5 hour is missing | ERA5 for another hour | Map with --temp-level 2m | Rejected with `data_not_found` |
| user learns the station hour is missing | Wind only | Map with --wind-level 10m --station-var NO2 | Rejected with `data_not_found`, naming 2026010113 |
| user learns the region does not exist | 2 m temperature | Map region Atlantis | Rejected with `region_not_found` |
| user maps weather across two regions | Temperature and wind | Map `FixtureCity,EastCity` with --temp-level 2m --wind-level 10m | `region.members` names both; `temperature` `by_member` FixtureCity n 25 and EastCity n 15 (cells on the shared border count for both), mean 20; `wind` `by_member` the same counts, mean 5 |
| user maps stations with weather across two regions | Wind and the station file | Map `FixtureCity,EastCity` with --wind-level 10m --station-var NO2 | `station` `by_member` FixtureCity n 2 mean 60 and EastCity n 1 mean 999 |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
