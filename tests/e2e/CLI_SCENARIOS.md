# CLI-wide acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess with the same isolated
configuration as the command suites. These scenarios cover the command set
itself and the conventions shared by every command.

Data paths come from configuration only (CLI rule 1). The fixture config
lists every data folder under `[paths.data_dirs]`. Typer rejects an unknown
option with exit status 2 before rsplot runs, so no sidecar is written.

Options have long names only (CLI rule 2). Nothing that selects data is
implicit (CLI rule 3): `--output` is required everywhere, `--product` for
the satellite maps, `--var` for station and trend, and `--days` for recent.
Regions are named, never levelled: there is no `--level` option (see
REGION_SCENARIOS.md).

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user sees only enabled commands | CLI is installed | Request top-level help | Help lists raster, radius, overlay, station, trend, meteo, recent and fnr, and does not list forecast or reconstruct |
| user cannot run the disabled forecast command | CLI is installed | Run `forecast` with plausible arguments | Nonzero exit reporting no such command |
| user cannot run the disabled reconstruct command | CLI is installed | Run `reconstruct` with plausible arguments | Nonzero exit reporting no such command |
| user cannot point raster at a data folder | Configured paths | Run `raster ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point overlay at a satellite folder | Configured paths | Run `overlay ... --raster-dir /x` | Exit 2, "No such option", no output |
| user cannot point overlay at a station folder | Configured paths | Run `overlay ... --station-dir /x` | Exit 2, "No such option", no output |
| user cannot point radius at a data folder | Configured paths | Run `radius ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point radius at a station folder | Configured paths | Run `radius ... --station-data-dir /x` | Exit 2, "No such option", no output |
| user cannot point station at a data folder | Configured paths | Run `station ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point trend at a data folder | Configured paths | Run `trend ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point recent at a data folder | Configured paths | Run `recent ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point fnr at an NO2 folder | Configured paths | Run `fnr ... --no2-dir /x` | Exit 2, "No such option", no output |
| user cannot point fnr at an HCHO folder | Configured paths | Run `fnr ... --hcho-dir /x` | Exit 2, "No such option", no output |
| user cannot point meteo at an ERA5 folder | Configured paths | Run `meteo ... --data-dir /x` | Exit 2, "No such option", no output |
| user cannot point meteo at a station folder | Configured paths | Run `meteo ... --station-data-dir /x` | Exit 2, "No such option", no output |
| user learns a data folder is not configured | Config without `no2` | Map NO2 with `raster` | Exit 1; error sidecar `data_not_configured`, naming `[paths.data_dirs].no2` and no CLI option |
| user sees only long options for raster | CLI is installed | Request `raster --help` | No single-letter option such as `-p`, `-o` |
| user sees only long options for overlay | CLI is installed | Request `overlay --help` | No single-letter option |
| user sees only long options for radius | CLI is installed | Request `radius --help` | No single-letter option |
| user sees only long options for station | CLI is installed | Request `station --help` | No single-letter option |
| user sees only long options for trend | CLI is installed | Request `trend --help` | No single-letter option |
| user sees only long options for recent | CLI is installed | Request `recent --help` | No single-letter option |
| user sees only long options for fnr | CLI is installed | Request `fnr --help` | No single-letter option |
| user sees only long options for meteo | CLI is installed | Request `meteo --help` | No single-letter option |
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
| user must give recent an output | CLI is installed | Run `recent` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give recent a day count | CLI is installed | Run `recent` without `--days` | Exit 2, "Missing option" naming `--days`, no output |
| user must give fnr an output | CLI is installed | Run `fnr` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user must give meteo an output | CLI is installed | Run `meteo` without `--output` | Exit 2, "Missing option" naming `--output`, no output |
| user cannot force the raster region level | CLI is installed | Run `raster ... --level city` | Exit 2, "No such option", no output |
| user cannot force the overlay region level | CLI is installed | Run `overlay ... --level city` | Exit 2, "No such option", no output |
| user cannot force the station region level | CLI is installed | Run `station ... --level city` | Exit 2, "No such option", no output |
| user cannot force the trend region level | CLI is installed | Run `trend ... --level city` | Exit 2, "No such option", no output |
| user cannot force the recent region level | CLI is installed | Run `recent ... --level city` | Exit 2, "No such option", no output |
| user cannot force the fnr region level | CLI is installed | Run `fnr ... --level city` | Exit 2, "No such option", no output |
| user cannot force the meteo region level | CLI is installed | Run `meteo ... --level city` | Exit 2, "No such option", no output |
