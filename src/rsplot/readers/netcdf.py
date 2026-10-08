"""Open single NetCDF inputs with coded, one-line failures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import xarray as xr

from rsplot.errors import RsplotError


def open_netcdf(path: str | Path, **kwargs: Any) -> xr.Dataset:
    """Open ``path``; a missing or unreadable file names itself.

    xarray reports a corrupt file as a ValueError with a paragraph about IO
    backends; agents get ``read_failed`` and the path instead.
    """
    try:
        return xr.open_dataset(path, **kwargs)
    except FileNotFoundError as error:
        raise RsplotError(
            "data_not_found",
            f"未找到文件: {path}",
            details={"path": str(path)},
        ) from error
    except (OSError, ValueError) as error:
        raise RsplotError(
            "read_failed",
            f"无法读取 NetCDF 文件 {path}：文件损坏或不是 NetCDF 格式。",
            details={"path": str(path), "reason": type(error).__name__},
        ) from error
