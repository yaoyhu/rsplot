"""Write output files so a reader never sees a partial file."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from rsplot.errors import RsplotError


@contextmanager
def atomic_write(path: str | Path) -> Iterator[Path]:
    """Yield a temporary path beside ``path`` and rename it into place.

    The temporary name keeps the suffix, so writers that infer a format
    from it (Matplotlib, netCDF4) behave as for the final name. A failed
    write removes the temporary file and leaves ``path`` untouched; an
    operating-system failure is reported as ``write_failed``.
    """
    target = Path(path)
    temp = target.with_name(f".{target.stem}.{os.getpid()}.tmp{target.suffix}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        yield temp
        os.replace(temp, target)
    except OSError as error:
        raise RsplotError(
            "write_failed",
            f"无法写入 {target}: {error.strerror or error}",
            option="--output",
            details={"path": str(target)},
        ) from error
    finally:
        temp.unlink(missing_ok=True)
