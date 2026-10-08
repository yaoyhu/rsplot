# Region-naming acceptance scenarios

Tier: E2E. Run the installed CLI (`raster`, as the vehicle for the shared
region resolver) in a subprocess against temporary swath, GeoJSON and TOML
files. Read the saved JSON; do not replace any rsplot function.

Regions are named in Chinese only; there is no `--level` option. A full
name matches its own level; a short name that fits places at two levels is
rejected, never guessed. 北京市, 上海市 and 天津市 are cities; 重庆市 is a
province.

Short names drop the ethnic groups before 自治区/自治州/自治县/自治旗
(广西壮族自治区 → 广西, 新疆维吾尔自治区 → 新疆).

Fixtures add provinces 双名省, 北京市, 重庆市, 广西壮族自治区,
新疆维吾尔自治区 and 海南省 and cities 双名市, 北京市, 重庆市,
楚雄彝族自治州, 黔东南苗族侗族自治州 and 海南藏族自治州 over the fixture
swath box, next to the base FixtureProvince /
FixtureCity boundaries. Every sidecar must validate against the schema; a
rejection exits 1, prints one `rsplot error <code>` line and writes no
file.

| Scenario | Given | When | Then |
| --- | --- | --- | --- |
| user maps a city whose short name is also a province | 双名省 and 双名市 | Map 双名市 | Region 双名市, level city |
| user maps the province of that name | 双名省 and 双名市 | Map 双名省 | Region 双名省, level province |
| user is told a short name is ambiguous | 双名省 and 双名市 | Map 双名 | Rejected with `region_ambiguous`; `details.candidates` is 双名省, 双名市 |
| user maps Beijing as a city | 北京市 in both files | Map 北京 | Region 北京市, level city |
| user reads a Chinese command line as typed | 北京市 in both files | Map 北京 | `request` starts `rsplot raster 北京 20260101 --product no2`, with no quotes around the name |
| user maps Chongqing as a province | 重庆市 in both files | Map 重庆 | Region 重庆市, level province |
| user maps Guangxi by its short name | 广西壮族自治区 | Map 广西 | Region 广西壮族自治区, level province |
| user maps Xinjiang by its short name | 新疆维吾尔自治区 (no 族) | Map 新疆 | Region 新疆维吾尔自治区, level province |
| user maps an autonomous prefecture by its short name | 楚雄彝族自治州 | Map 楚雄 | Region 楚雄彝族自治州, level city |
| user maps a prefecture named for two groups | 黔东南苗族侗族自治州 | Map 黔东南 | Region 黔东南苗族侗族自治州, level city |
| user is told Hainan is ambiguous | 海南省 and 海南藏族自治州 | Map 海南 | Rejected with `region_ambiguous`; candidates 海南省, 海南藏族自治州 |
| user maps Hainan province by its full name | 海南省 and 海南藏族自治州 | Map 海南省 | Region 海南省, level province |
| user gets a suggestion for a misspelled name | 安徽省 and 安庆市 | Map 安微 | Rejected with `region_not_found`; `details.suggestions` is 安徽省, 安庆市, province first |
| user gets a suggestion for a misspelled county's city | FixtureCity with FixtureCounty | Map FixtureCiti/FixtureCounty | Rejected with `region_not_found`; the first suggestion is FixtureCity |
| user cannot use a pinyin name | Chinese boundary names | Map shuangming | Rejected with `region_not_found` |
