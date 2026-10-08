"""Write output files so a reader never sees a partial file."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_write(path: str | Path) -> Iterator[Path]:
    """Yield a temporary path beside ``path`` and rename it into place.

    The temporary name keeps the suffix, so writers that infer a format
    from it (Matplotlib, netCDF4) behave as for the final name. A failed
    write removes the temporary file and leaves ``path`` untouched.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.stem}.{os.getpid()}.tmp{target.suffix}")
    try:
        yield temp
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
