# CLI-wide acceptance scenarios

Tier: E2E. Run the installed CLI in a subprocess with the same isolated
configuration as the command suites. These scenarios cover the command set
itself rather than any one command.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user sees only enabled commands | CLI is installed | Request top-level help | Help lists raster, radius, overlay, station, trend, meteo, recent and fnr, and does not list forecast or reconstruct |
| user cannot run the disabled forecast command | CLI is installed | Run `forecast` with plausible arguments | Nonzero exit reporting no such command |
| user cannot run the disabled reconstruct command | CLI is installed | Run `reconstruct` with plausible arguments | Nonzero exit reporting no such command |
