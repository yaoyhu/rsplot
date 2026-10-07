# Region-naming acceptance scenarios

Tier: E2E. Run the installed CLI (`raster`, as the vehicle for the shared
region resolver) in a subprocess against temporary swath, GeoJSON and TOML
files. Read the saved JSON; do not replace any rsplot function.

Regions are named in Chinese only; there is no `--level` option. A full
name matches its own level; a short name that fits places at two levels is
rejected, never guessed. 北京市, 上海市 and 天津市 are cities; 重庆市 is a
province.

Fixtures add provinces 双名省, 北京市 and 重庆市 and cities 双名市, 北京市
and 重庆市 over the fixture swath box, next to the base FixtureProvince /
FixtureCity boundaries. Every sidecar must validate against the schema; a
rejection exits 1 and writes only an error sidecar.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user maps a city whose short name is also a province | 双名省 and 双名市 | Map 双名市 | Region 双名市, level city |
| user maps the province of that name | 双名省 and 双名市 | Map 双名省 | Region 双名省, level province |
| user is told a short name is ambiguous | 双名省 and 双名市 | Map 双名 | Rejected with `region_ambiguous`; `details.candidates` is 双名省, 双名市 |
| user maps Beijing as a city | 北京市 in both files | Map 北京 | Region 北京市, level city |
| user maps Chongqing as a province | 重庆市 in both files | Map 重庆 | Region 重庆市, level province |
| user cannot use a pinyin name | Chinese boundary names | Map shuangming | Rejected with `region_not_found` |
