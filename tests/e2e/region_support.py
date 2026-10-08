"""Boundary files with same-name places for region-naming scenarios."""

from __future__ import annotations

import json
from pathlib import Path

from raster_support import RasterWorkspace

# Extra places over the fixture swath box (117-118°E, 31-32°N). They are
# kept out of the base fixtures so administrative lookups elsewhere still
# find FixtureCity.
EXTRA = {
    "中国_省.geojson": (
        "双名省",
        "北京市",
        "重庆市",
        "广西壮族自治区",
        "新疆维吾尔自治区",
        "海南省",
        "安徽省",
    ),
    "中国_市.geojson": (
        "双名市",
        "北京市",
        "重庆市",
        "楚雄彝族自治州",
        "黔东南苗族侗族自治州",
        "海南藏族自治州",
        "安庆市",
    ),
}


class RegionWorkspace(RasterWorkspace):
    """The raster fixtures plus provinces and cities sharing names."""

    def __init__(self, root: Path):
        super().__init__(root)
        for filename, names in EXTRA.items():
            path = self.boundaries / filename
            collection = json.loads(path.read_text(encoding="utf-8"))
            collection["features"] += [
                self.feature(name, 117, 118) for name in names
            ]
            path.write_text(json.dumps(collection), encoding="utf-8")
