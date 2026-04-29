"""Satellite data readers and product registry."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from rsplot.readers.base import BaseReader
from rsplot.readers.tropomi_hcho import TropomiHCHOReader
from rsplot.readers.tropomi_no2 import TropomiNO2Reader
from rsplot.readers.tropomi_o3 import TropomiO3Reader

HCHO_CMAP = "rsplot_hcho"


@dataclass
class ProductInfo:
    """Per-product metadata: reader class, display settings, auto-range config."""

    reader_cls: type[BaseReader]
    colorbar_label: str
    cmap: str
    vmin: float | None  # None = auto from data percentiles
    vmax: float | None
    min_range: float  # minimum vmax-vmin to avoid exaggerating small differences


PRODUCT_REGISTRY: dict[str, ProductInfo] = {
    "no2": ProductInfo(
        reader_cls=TropomiNO2Reader,
        colorbar_label="NO2 VCD (x10^15 molec/cm2)",
        cmap="YlOrRd",
        vmin=0.0,
        vmax=20.0,
        min_range=5.0,
    ),
    "o3": ProductInfo(
        reader_cls=TropomiO3Reader,
        colorbar_label="O3 Total Column (DU)",
        cmap="YlOrRd",
        vmin=None,
        vmax=None,
        min_range=30.0,
    ),
    "hcho": ProductInfo(
        reader_cls=TropomiHCHOReader,
        colorbar_label="HCHO VCD (x10^15 molec/cm2)",
        cmap=HCHO_CMAP,
        vmin=None,  # unit not yet confirmed — let auto-range pick
        vmax=None,
        min_range=5.0,
    ),
}


def get_product_info(product: str) -> ProductInfo:
    """Return ProductInfo for a product name."""
    key = product.lower()
    if key not in PRODUCT_REGISTRY:
        available = ", ".join(PRODUCT_REGISTRY)
        raise ValueError(
            f"Unsupported product '{product}'. Available: {available}"
        )
    return PRODUCT_REGISTRY[key]


def auto_vrange(
    grid: np.ndarray, prod_info: ProductInfo
) -> tuple[float, float]:
    """Compute vmin/vmax from data, respecting min_range and rounding nicely."""
    p2 = float(np.nanpercentile(grid, 2))
    p98 = float(np.nanpercentile(grid, 98))
    span = p98 - p2

    # Enforce minimum range: expand symmetrically around the center
    if span < prod_info.min_range:
        center = (p2 + p98) / 2
        p2 = center - prod_info.min_range / 2
        p98 = center + prod_info.min_range / 2
        span = prod_info.min_range

    # Round to nice numbers: pick step from span magnitude
    if span < 10:
        step = 1.0
    elif span < 50:
        step = 5.0
    elif span < 100:
        step = 10.0
    else:
        step = 20.0

    vmin = math.floor(p2 / step) * step
    vmax = math.ceil(p98 / step) * step
    return vmin, vmax
