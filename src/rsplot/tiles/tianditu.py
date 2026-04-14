"""TianDiTu (天地图) tile provider for cartopy.

Supports satellite imagery (img), vector (vec), and terrain (ter) layers.
Requires an API key from https://www.tianditu.gov.cn.
"""

from __future__ import annotations

import cartopy.io.img_tiles as cimgt


class TianDiTuTiles(cimgt.GoogleTiles):
    """天地图卫星影像瓦片（球面墨卡托投影）。

    Parameters
    ----------
    tk : TianDiTu API key.
    layer : "img" (satellite), "vec" (vector), "ter" (terrain).
    """

    def __init__(self, tk: str, layer: str = "img"):
        self.tk = tk
        self.layer = layer
        super().__init__()

    def _image_url(self, tile):
        x, y, z = tile
        server = (x + y) % 8
        return (
            f"http://t{server}.tianditu.gov.cn/DataServer"
            f"?T={self.layer}_w&x={x}&y={y}&l={z}&tk={self.tk}"
        )
