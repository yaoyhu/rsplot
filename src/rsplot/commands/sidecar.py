"""Run a command that writes an ``rsplot.result/2`` sidecar.

Successful runs write the image, data files and sidecar. Any failure removes
what was already written and, when ``--output`` is known, writes an error
sidecar instead, so an agent always finds one JSON describing the outcome.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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


def run_with_sidecar(
    *,
    command: str,
    kwargs: dict[str, Any],
    options: Mapping[str, tuple[str, ...]],
    positionals: Mapping[str, Any],
    emit: Callable[[list[Path]], None],
) -> None:
    """Call ``emit(created)``; on failure clean up and write an error sidecar.

    ``emit`` appends every file it writes to ``created`` before writing it.
    ``options`` maps keyword arguments to their CLI spellings so the error
    sidecar can record which values the caller supplied.
    """
    console = kwargs["console"]
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
        console.print(f"[red]{coded}[/red]")
        if output is not None:
            _write_error_sidecar(
                command, coded, kwargs, options, positionals, output
            )
        if coded.code == "internal_error":
            raise
        raise typer.Exit(1) from error


def _write_error_sidecar(
    command: str,
    error: RsplotError,
    kwargs: dict[str, Any],
    options: Mapping[str, tuple[str, ...]],
    positionals: Mapping[str, Any],
    output: str,
) -> None:
    from rsplot.result_builders.envelope import (
        error_envelope,
        option_given,
        request_block,
        resolved,
        sidecar_path,
        write_sidecar,
    )

    given = {
        key: resolved(kwargs[key], "cli")
        for key, names in options.items()
        if option_given(*names)
    }
    given.update(
        {key: resolved(value, "cli") for key, value in positionals.items()}
    )
    sidecar = str(Path(sidecar_path(output)).resolve())
    write_sidecar(
        error_envelope(
            command=command,
            request=request_block(given),
            error=error,
            sidecar=sidecar,
        ),
        sidecar,
    )
