# Recent acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess against temporary satellite
and station NetCDF, GeoJSON and TOML files. `recent` draws no image: read the
JSON written at `--output` and its daily CSV; do not replace any rsplot
function.

Every sidecar, successful or not, must validate against the shipped schema
`rsplot.result/2`. A successful run has one daily `series` layer, no image
and no render block. A rejected request exits nonzero and writes only an
error sidecar with the stated `error.code`.

Requests cover the 3 days ending Jan 3 in `FixtureCity`. Satellite fixtures
are uniform NO2 swaths valued 2, 4 and 6 on Jan 1–3. Station fixtures have
one 13:00 file per day with in-region stations at 40 + d and 80 + d for day
offsets d = 0, 10, 20 and an outside station at 999.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user summarizes recent satellite days | Three daily swaths | Summarize raster NO2 | Layer `satellite`, kind `series`, daily series Jan 1–3 on UTC filename dates, 3 of 3 days, mean 4; no image, no render |
| user loads the daily table | Three daily swaths | Summarize raster NO2 | The daily CSV has three rows with values 2, 4 and 6, all `ok` |
| user sees the recent trend | Three daily swaths | Summarize raster NO2 | `temporal_summary.trend` has slope 2 per day, direction up |
| user is warned about missing days | Swaths on Jan 1 and Jan 3 only | Summarize raster NO2 | Coverage 2 of 3 days, warning `missing_days`, grade `limited`; the Jan 2 CSV row is not `ok` and has an error |
| user finds every input file | Three daily swaths | Summarize raster NO2 | `source.files` lists the three swath files |
| user summarizes recent station days | Three daily station files | Summarize station NO2 | Layer `station`, quantity NO2 in ug/m3, daily means 60, 70, 80 with mean 70; method records the latest available hour per day |
| user sees which hour each station day used | Three daily station files | Summarize station NO2 | The daily CSV `hour` column is 2026010113, 2026010213, 2026010313 |
| user is told nothing was found | No swaths | Summarize raster NO2 | Status ok, 0 of 3 days, flag `no_valid_data`, grade `unreliable` |
| user rejects an invalid end date | Three daily swaths | Summarize ending 20260230 | Rejected with `invalid_time` |
| user rejects an unknown source | Three daily swaths | Summarize with --source radar | Rejected with `invalid_argument` on option --source |
| user rejects GEMS for station summaries | Three daily station files | Station summary with --sensor gems | Rejected with `invalid_argument` on option --sensor |
| user learns the station variable is unknown | Three daily station files | Station summary with --var XYZ | Rejected with `invalid_argument` on option --var |
| user learns the region does not exist | Three daily swaths | Summarize region Atlantis | Rejected with `region_not_found` |

For suspected bugs, run the corresponding scenario against the unchanged
application and record the failure before applying a fix.
