"""Shared numeric summaries used by machine-readable result builders."""

from __future__ import annotations

from typing import Any

import numpy as np


def round_finite(value: float, ndigits: int = 2) -> float | None:
    """Round a finite value and represent non-finite values as ``None``."""
    if not np.isfinite(value):
        return None
    return round(float(value), ndigits)


def basic_stats(values: np.ndarray, ndigits: int = 2) -> dict[str, Any]:
    """Return the stable rsplot summary over finite array values."""
    finite = np.asarray(values)[np.isfinite(values)]
    if len(finite) == 0:
        return {}
    p10, p25, median, p75, p90 = np.percentile(
        finite,
        [10, 25, 50, 75, 90],
    )
    return {
        "n": len(finite),
        "min": round_finite(np.min(finite), ndigits),
        "max": round_finite(np.max(finite), ndigits),
        "mean": round_finite(np.mean(finite), ndigits),
        "median": round_finite(median, ndigits),
        "p10": round_finite(p10, ndigits),
        "p25": round_finite(p25, ndigits),
        "p75": round_finite(p75, ndigits),
        "p90": round_finite(p90, ndigits),
    }
