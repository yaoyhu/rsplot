# Station acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary station
NetCDF, GeoJSON and TOML files, with `--basemap none`. Read the saved PNG,
JSON and CSV; do not replace any rsplot function.

Every sidecar must validate against the shipped schema
`src/rsplot/schemas/result.schema.json`. A successful map has one `station`
layer and no relations. A rejected request exits 1, prints one `rsplot error
<code>` line on stderr with the stated code (and option), and leaves no PNG,
JSON or data file.

The station file for Jan 1 13:00 places two stations inside `FixtureCity`
(value 40 and 80 for every variable) and one in the adjacent `EastCity`
(value 999) that must be excluded from statistics.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user maps one station hour | The Jan 1 13:00 station file | Map NO2 at 2026010113 | A colored PNG; station layer NO2 in ug/m3 at hour 2026010113 with no time zone; mean 60 from 2 stations; no relations |
| user reads the station table | Same file | Map NO2 | The CSV lists all three stations read with values 40, 80, 999 and `in_region` 1, 1, 0, without satellite columns |
| user counts exceedances only inside the region | The outside station's 999 exceeds the NO2 hourly limit | Map NO2 | Exceedance threshold 200, count 0 |
| user sees AQI categories | Same file | Map AQI | `categories` counts one station as 优 and one as 良 |
| user is warned about few stations | Two valid stations in the region | Map NO2 | Warning `few_stations`; `quality` has no grade |
| user reproduces a request | Same file | Map NO2 | `request` is the command as one line; the station layer's `source.data_root` is the configured station folder |
| user rejects a date-only hour | Same file | Map 20260101 | Rejected with `invalid_time` |
| user rejects an impossible hour | Same file | Map 2026010125 | Rejected with `invalid_time` |
| user learns the variable is unknown | Same file | Map --var XYZ | Rejected with `invalid_argument` on option --var |
| user never gets another hour | Only the Jan 1 23:00 file exists | Map 2026010113 | Rejected with `data_not_found`, naming 2026010113 |
| user learns a station file is unreadable | The 13:00 file is not NetCDF | Map 2026010113 | Rejected with `read_failed`; `details.path` names that file and the message carries no library boilerplate |
| user learns a region does not exist | Same file | Map region Atlantis | Rejected with `region_not_found` |
| user maps stations across two regions | Same file | Map NO2 for `FixtureCity,EastCity` | `region.members` names both; the station layer counts 3 stations once and has `by_member` FixtureCity n 2 mean 60 and EastCity n 1 mean 999 |
| user sees a region without stations | Only the two FixtureCity stations | Map NO2 for `FixtureCity,EastCity` | `by_member` keeps EastCity with n 0 and a null mean |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
