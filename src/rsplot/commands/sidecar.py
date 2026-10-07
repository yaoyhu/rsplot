"""Run a command that writes a result sidecar only when it succeeds.

Successful runs write the image, data files and sidecar. A failure removes
what the run already wrote, plus any sidecar an earlier run left at the same
path, prints one ``rsplot error <code>[ <option>]: <message>[ <details>]``
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

    ``emit`` appends every file it writes to ``created`` before writing it.
    """
    from rsplot.result_builders.envelope import sidecar_path

    output = kwargs.get("output")
    created: list[Path] = []
    try:
        emit(created)
    except typer.Exit:
        raise
    except Exception as error:
        coded = coded_error(error)
        for path in created:
            path.unlink(missing_ok=True)
        if output is not None:
            Path(sidecar_path(output)).unlink(missing_ok=True)
        print(error_line(coded), file=sys.stderr, flush=True)
        if coded.code == "internal_error":
            raise
        raise typer.Exit(1) from error
