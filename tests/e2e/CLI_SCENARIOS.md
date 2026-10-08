# CLI-wide acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess with the same isolated
configuration as the command suites. These scenarios cover the command set
itself and the conventions shared by every command.

Data paths come from configuration only (CLI rule 1). The fixture config
lists every data folder under `[paths.data_dirs]`. Typer rejects an unknown
option with exit status 2 before rsplot runs. Any other rejection exits 1,
prints exactly one `rsplot error <code>[ <option>]: <message>[ <details>]`
line on stderr, and leaves no PNG, JSON or data file; sidecars exist only
for successful runs.

Options have long names only (CLI rule 2). Nothing that selects data is
implicit (CLI rule 3): `--output` is required everywhere, `--product` for
the satellite maps, and `--var` for station and trend.
Regions are named, never levelled: there is no `--level` option (see
REGION_SCENARIOS.md).

Every time is China time, so no output names a time zone (北京时间, 中国时间,
中国标准时间, CST, UTC, `Asia/Shanghai`, a `timezone` key or a `_utc` key):
not help text, console output, the error line, figure titles or sidecars.
Every suite's success helper checks stdout and the sidecar, and the shared
`assert_failed` checks the error output, so each scenario covers this rule.
The one exception is meteo's missing ERA5 hour error, which still names
the UTC archive hour it looked for.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user sees only enabled commands | CLI is installed | Request top-level help | Help lists raster, radius, overlay, station, trend, meteo and fnr, and does not list recent, forecast or reconstruct |
| user cannot run the disabled forecast command | CLI is installed | Run `forecast` with plausible arguments | Nonzero exit reporting no such command |
| user cannot run the disabled reconstruct command | CLI is installed | Run `reconstruct` with plausible arguments | Nonzero exit reporting no such command |
| user cannot run the removed recent command | CLI is installed | Run `recent` with arguments it used to accept | Nonzero exit reporting no such command, no output |
| user cannot point raster at a data folder | Configured paths | Run `raster ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point overlay at a satellite folder | Configured paths | Run `overlay ... --raster-dir /x` | Exit 2, "No such option", no output |
| user cannot point overlay at a station folder | Configured paths | Run `overlay ... --station-dir /x` | Exit 2, "No such option", no output |
| user cannot point radius at a data folder | Configured paths | Run `radius ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point radius at a station folder | Configured paths | Run `radius ... --station-data-dir /x` | Exit 2, "No such option", no output |
| user cannot point station at a data folder | Configured paths | Run `station ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point trend at a data folder | Configured paths | Run `trend ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point fnr at an NO2 folder | Configured paths | Run `fnr ... --no2-dir /x` | Exit 2, "No such option", no output |
| user cannot point fnr at an HCHO folder | Configured paths | Run `fnr ... --hcho-dir /x` | Exit 2, "No such option", no output |
| user cannot point meteo at an ERA5 folder | Configured paths | Run `meteo ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point meteo at a station folder | Configured paths | Run `meteo ... --station-data-dir /x` | Exit 2, "No such option", no output |
| user cannot set a raster valid-day threshold | Configured paths | Run `raster ... --days 2 --n-min 1` | Exit 2, "No such option", no output |
| user cannot set an overlay valid-day threshold | Configured paths | Run `overlay ... --days 2 --n-min 1` | Exit 2, "No such option", no output |
| user cannot set a radius valid-day threshold | Configured paths | Run `radius ... --days 2 --n-min 1` | Exit 2, "No such option", no output |
| user learns a data folder is not configured | Config without `no2` | Map NO2 with `raster` | Exit 1; error line `data_not_configured` naming `[paths.data_dirs].no2` and no CLI option, details `{"config_key": "no2"}` |
| user sees only long options for raster | CLI is installed | Request `raster --help` | No single-letter option such as `-p`, `-o` |
| user sees only long options for overlay | CLI is installed | Request `overlay --help` | No single-letter option |
| user sees only long options for radius | CLI is installed | Request `radius --help` | No single-letter option |
| user sees only long options for station | CLI is installed | Request `station --help` | No single-letter option |
| user sees only long options for trend | CLI is installed | Request `trend --help` | No single-letter option |
| user sees only long options for fnr | CLI is installed | Request `fnr --help` | No single-letter option |
| user sees only long options for meteo | CLI is installed | Request `meteo --help` | No single-letter option |
| user reads raster help without time zones | CLI is installed | Request `raster --help` | The help names no time zone |
| user reads overlay help without time zones | CLI is installed | Request `overlay --help` | The help names no time zone |
| user reads radius help without time zones | CLI is installed | Request `radius --help` | The help names no time zone |
| user reads station help without time zones | CLI is installed | Request `station --help` | The help names no time zone |
| user reads trend help without time zones | CLI is installed | Request `trend --help` | The help names no time zone |
| user reads fnr help without time zones | CLI is installed | Request `fnr --help` | The help names no time zone |
| user reads meteo help without time zones | CLI is installed | Request `meteo --help` | The help names no time zone |
| user cannot use a former alias | CLI is installed | Run `raster ... -o map.png` | Exit 2, "No such option", no output |
| user must give raster an output | CLI is installed | Run `raster` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give raster a product | CLI is installed | Run `raster` without `--product` | Exit 2, "Missing option" naming `--product`, no output |
| user must give overlay an output | CLI is installed | Run `overlay` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give overlay a product | CLI is installed | Run `overlay` without `--product` | Exit 2, "Missing option" naming `--product`, no output |
| user must give radius an output | CLI is installed | Run `radius` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give radius a product | CLI is installed | Run `radius` without `--product` | Exit 2, "Missing option" naming `--product`, no output |
| user must give station an output | CLI is installed | Run `station` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give station a variable | CLI is installed | Run `station` without `--var` | Exit 2, "Missing option" naming `--var`, no output |
| user must give trend an output | CLI is installed | Run `trend` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give trend a variable | CLI is installed | Run `trend` without `--var` | Exit 2, "Missing option" naming `--var`, no output |
| user must give fnr an output | CLI is installed | Run `fnr` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give meteo an output | CLI is installed | Run `meteo` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user cannot force the raster region level | CLI is installed | Run `raster ... --level city` | Exit 2, "No such option", no output |
| user cannot force the overlay region level | CLI is installed | Run `overlay ... --level city` | Exit 2, "No such option", no output |
| user cannot force the station region level | CLI is installed | Run `station ... --level city` | Exit 2, "No such option", no output |
| user cannot force the trend region level | CLI is installed | Run `trend ... --level city` | Exit 2, "No such option", no output |
| user cannot force the fnr region level | CLI is installed | Run `fnr ... --level city` | Exit 2, "No such option", no output |
| user cannot force the meteo region level | CLI is installed | Run `meteo ... --level city` | Exit 2, "No such option", no output |
| user reads a failure from one error line | One swath | Map with --days 0 | Exit 1; stderr has exactly one `rsplot error invalid_argument --days: --days 必须 >= 1。` line; no files are left |
| user keeps no stale sidecar after a failure | An earlier successful map at the same output | Map again with --days 0 | Exit 1; the earlier sidecar is gone |
| user finds no format number in a sidecar | One swath | Map it | The sidecar has no `schema`, `status` or `error` key; it has `rsplot_version` |
| user reads the generation time in Beijing time | One swath; the computer's time zone is America/New_York | Map it | The sidecar's `generated_at` ends in `+08:00` |
