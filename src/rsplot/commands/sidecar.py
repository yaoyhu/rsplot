"""Run a command that writes a result sidecar only when it succeeds.

Successful runs write the data files, image and, last, the sidecar; each
file appears whole, through a temporary name. A run first removes any
sidecar an earlier run left at the same path, so a sidecar on disk always
describes the image beside it. A failure removes what the run already wrote,
prints one ``rsplot error <code>[ <option>]: <message>[ <details>]``
line on stderr and exits 1.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from rsplot.errors import RsplotError


def coded_error(error: Exception) -> RsplotError:
    """Map an exception to an rsplot error code."""
    if isinstance(error, RsplotError):
        return error
    if isinstance(error, FileNotFoundError):
        return RsplotError("data_not_found", str(error))
    if isinstance(error, OSError):
        return RsplotError("read_failed", str(error))
    if isinstance(error, ValueError):
        return RsplotError("invalid_argument", str(error))
    return RsplotError(
        "internal_error",
        str(error) or type(error).__name__,
        details={"exception": type(error).__name__},
    )


def error_line(error: RsplotError) -> str:
    """Format the single stderr line that reports a failure."""
    option = f" {error.option}" if error.option else ""
    message = " ".join(str(error).split())
    details = (
        " " + json.dumps(error.details, ensure_ascii=False, default=str)
        if error.details
        else ""
    )
    return f"rsplot error {error.code}{option}: {message}{details}"


def run_with_sidecar(
    *,
    kwargs: dict[str, Any],
    emit: Callable[[list[Path]], None],
) -> None:
    """Call ``emit(created)``; on failure clean up and report one error line.

    ``emit`` appends every file it writes to ``created`` before writing it,
    writes each through ``atomic.atomic_write`` and writes the sidecar last.
    """
    from rsplot.result_builders.envelope import sidecar_path

    output = kwargs.get("output")
    created: list[Path] = []
    cleanup_sidecar: Path | None = None
    try:
        if output is None or Path(output).suffix.lower() != ".png":
            raise RsplotError(
                "invalid_argument",
                "输出文件必须使用 .png 后缀。",
                option="--output",
            )
        image = Path(output).resolve()
        if image.is_dir() or image.suffix.lower() != ".png":
            raise RsplotError(
                "invalid_argument",
                "输出路径必须指向 .png 文件，不能是目录。",
                option="--output",
            )
        # Only a validated image path can own a sidecar to clean up. Remove
        # an earlier run's sidecar first: if this run is killed, no sidecar
        # is left to vouch for a new image.
        cleanup_sidecar = Path(sidecar_path(str(image)))
        cleanup_sidecar.unlink(missing_ok=True)
        emit(created)
    except typer.Exit:
        raise
    except Exception as error:
        coded = coded_error(error)
        for path in created:
            path.unlink(missing_ok=True)
        if cleanup_sidecar is not None:
            cleanup_sidecar.unlink(missing_ok=True)
        print(error_line(coded), file=sys.stderr, flush=True)
        if coded.code == "internal_error":
            raise
        raise typer.Exit(1) from error
