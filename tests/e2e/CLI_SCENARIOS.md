# CLI-wide acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess with the same isolated
configuration as the command suites. These scenarios cover the command set
itself and the conventions shared by every command.

Data paths come from configuration only (CLI rule 1). The fixture config
lists every data folder under `[paths.data_dirs]`. Typer rejects an unknown
option with exit status 2 before rsplot runs, so no sidecar is written.

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
