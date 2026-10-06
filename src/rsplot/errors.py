"""Expected failures with machine-readable codes for result sidecars."""

from __future__ import annotations

from typing import Any

# Codes accepted by the rsplot.result/2 schema's ``error.code``.
ERROR_CODES = (
    "invalid_argument",
    "invalid_time",
    "region_not_found",
    "data_not_configured",
    "data_not_found",
    "no_valid_data",
    "read_failed",
    "internal_error",
)


class RsplotError(ValueError):
    """An expected input or data error.

    Subclasses ``ValueError`` so commands that still catch ``ValueError``
    keep printing the same message and exiting with status 1.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        option: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown rsplot error code: {code}")
        super().__init__(message)
        self.code = code
        self.option = option
        self.details = details or {}
