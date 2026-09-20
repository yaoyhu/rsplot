"""Satellite data readers and product registry."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from rsplot.readers.base import BaseReader
from rsplot.readers.tropomi_hcho import TropomiHCHOReader
from rsplot.readers.tropomi_no2 import TropomiNO2Reader
from rsplot.readers.tropomi_o3 import TropomiO3Reader
from rsplot.readers.tropomi_o3pr import TropomiO3PRReader

HCHO_CMAP = "rsplot_hcho"
NO2_CMAP = "rsplot_no2"
COLORMAP_22 = "rsplot_colormap_22"


@dataclass
class ProductPlotDefaults:
    """Optional per-product plotting defaults by administrative level."""

    res: float | None = None
    smooth_sigma: float | None = None


@dataclass
class ProductInfo:
    """Per-product metadata: reader class, display settings, auto-range config."""

    reader_cls: type[BaseReader]
    colorbar_label: str
    cmap: str
    vmin: float | None  # None = auto from data percentiles
    vmax: float | None
    min_range: (
        float  # minimum vmax-vmin to avoid exaggerating small differences
    )
    level_defaults: dict[str, ProductPlotDefaults] = field(
        default_factory=dict
    )

    sensor: str = "tropomi"
    data_key: str | None = None
    quantity: str | None = None
    processing: str | None = None

    def create_reader(self) -> BaseReader:
        """Construct the configured reader without changing legacy callers."""
        if self.processing is not None:
            return self.reader_cls(processing=self.processing)
        return self.reader_cls()

    def defaults_for_level(self, level: str) -> ProductPlotDefaults:
        """Return product-specific defaults for an administrative level."""
        return self.level_defaults.get(level, ProductPlotDefaults())


PRODUCT_REGISTRY: dict[str, ProductInfo] = {
    "no2": ProductInfo(
        reader_cls=TropomiNO2Reader,
        colorbar_label="NO2 VCD (x10^15 molec/cm2)",
        cmap=NO2_CMAP,
        vmin=0.0,
        vmax=20.0,
        min_range=5.0,
    ),
    "o3": ProductInfo(
        reader_cls=TropomiO3Reader,
        colorbar_label="O3 Total Column (DU)",
        cmap=COLORMAP_22,
        vmin=None,
        vmax=None,
        min_range=30.0,
    ),
    "o3pr": ProductInfo(
        reader_cls=TropomiO3PRReader,
        colorbar_label="O3 Tropospheric Column from Profile (DU)",
        cmap=COLORMAP_22,
        vmin=None,
        vmax=None,
        min_range=5.0,
        level_defaults={
            # O3__PR is a coarse 30x30 km profile product. These defaults
            # keep map pixels close to the native sampling while still using
            # modest smoothing for display.
            "country": ProductPlotDefaults(res=0.25, smooth_sigma=1.0),
            "key_region": ProductPlotDefaults(res=0.15, smooth_sigma=1.2),
            "province": ProductPlotDefaults(res=0.1, smooth_sigma=1.5),
            "city": ProductPlotDefaults(res=0.075, smooth_sigma=1.5),
            "county": ProductPlotDefaults(res=0.05, smooth_sigma=2.0),
        },
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


def get_product_info(
    product: str,
    *,
    sensor: str = "tropomi",
    processing: str | None = None,
) -> ProductInfo:
    """Resolve a product within a sensor, preserving legacy registry keys."""
    if processing is not None:
        processing = processing.lower()
        if processing != "nrti":
            raise ValueError("--processing 仅支持 nrti；省略时保持原有行为。")
        if sensor.lower() != "tropomi":
            raise ValueError("--processing nrti 仅用于 --sensor tropomi。")
    key = product.lower()
    sensor = sensor.lower()
    if sensor not in ("tropomi", "gems"):
        raise ValueError(f"未知卫星来源 '{sensor}'，可用: tropomi / gems")
    if key not in PRODUCT_REGISTRY:
        available = ", ".join(PRODUCT_REGISTRY)
        raise ValueError(
            f"Unsupported product '{product}'. Available: {available}"
        )
    if sensor == "tropomi":
        if processing == "nrti":
            return replace(
                PRODUCT_REGISTRY[key],
                processing=processing,
                data_key=f"tropomi_nrti_{key}",
            )
        return PRODUCT_REGISTRY[key]
    from rsplot.config import LEVEL_DEFAULTS
    from rsplot.readers.gems import (
        GEMS_DEFAULT_RESOLUTION,
        GemsHCHOReader,
        GemsNO2Reader,
        GemsO3PRReader,
        GemsO3Reader,
    )

    readers = {
        "no2": GemsNO2Reader,
        "hcho": GemsHCHOReader,
        "o3": GemsO3Reader,
        "o3pr": GemsO3PRReader,
    }
    quantities = {
        "no2": "tropospheric_no2_column",
        "hcho": "hcho_column",
        "o3": "total_ozone_column",
        "o3pr": "tropospheric_ozone_column",
    }
    return replace(
        PRODUCT_REGISTRY[key],
        reader_cls=readers[key],
        sensor="gems",
        level_defaults={
            level: replace(
                PRODUCT_REGISTRY[key].defaults_for_level(level),
                res=GEMS_DEFAULT_RESOLUTION,
            )
            for level in LEVEL_DEFAULTS
        },
        data_key="gems_o3" if key == "o3pr" else f"gems_{key}",
        quantity=quantities[key],
    )


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
