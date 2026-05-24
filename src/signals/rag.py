"""RAG signal computation.

Implements the Red/Amber/Green signal defined in ADR-0003 and METRICS.md.
Fixed-threshold bands on the raw VIX value:

    VIX < 20       -> GREEN  (low volatility regime)
    20 <= VIX <=30 -> AMBER  (elevated, monitor)
    VIX > 30       -> RED    (stressed market)
    VIX is NaN     -> UNAVAILABLE

Thresholds match ADR-0003's defence: widely cited historical regime boundaries
(2008/2020/2022 crises all crossed 30; majority of post-2000 days sit below 20).

The signal is computed for *every* row in the serving dataset, not only the
latest. This lets the dashboard render the signal history across the visible
window — green/amber/red bands following the market over time — which is the
case study's strongest narrative on real data. The "current" signal is just
the last row of the resulting Series.

Pure functions only — no I/O. Orchestrator calls these on the serving DataFrame
between metric computation and writing the gold-layer parquet.
"""

from __future__ import annotations

import logging
from enum import Enum

import pandas as pd

logger = logging.getLogger(__name__)


class RagBand(str, Enum):
    """Typed RAG signal value. String-valued for clean JSON / Parquet serialization."""

    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    UNAVAILABLE = "unavailable"


# Threshold constants from ADR-0003. Centralised here so a change to the
# RAG policy is a one-line edit, reviewable as a single PR. A future
# Macquarie-specific calibration (see ADR-0003 open questions) would adjust
# these constants and add a regression test row.
GREEN_UPPER_EXCLUSIVE = 20.0  # vix < 20 -> green
RED_LOWER_EXCLUSIVE = 30.0  # vix > 30 -> red


def compute_rag_signal(vix_value: float | None) -> RagBand:
    """Classify a single VIX value into a RAG band.

    Args:
        vix_value: A VIX closing value, or None / NaN if unavailable.

    Returns:
        RagBand enum value.

    Boundary semantics per ADR-0003:
        VIX = 19.99... -> GREEN
        VIX = 20.00    -> AMBER  (lower bound inclusive)
        VIX = 30.00    -> AMBER  (upper bound inclusive)
        VIX = 30.01... -> RED
    """
    if vix_value is None or pd.isna(vix_value):
        return RagBand.UNAVAILABLE
    if vix_value < GREEN_UPPER_EXCLUSIVE:
        return RagBand.GREEN
    if vix_value > RED_LOWER_EXCLUSIVE:
        return RagBand.RED
    return RagBand.AMBER


def enrich_with_signal(serving_df: pd.DataFrame) -> pd.DataFrame:
    """Add a `rag_signal` column to the serving DataFrame.

    Each row's signal is computed from that row's `vix` column. Rows where
    VIX is NaN get RagBand.UNAVAILABLE.

    Args:
        serving_df: Serving DataFrame, must contain a `vix` column.

    Returns:
        New DataFrame with a `rag_signal` column appended. Input is not mutated.

    Raises:
        ValueError: if `vix` column is missing.
    """
    if "vix" not in serving_df.columns:
        raise ValueError(
            f"serving DataFrame missing 'vix' column. "
            f"Got: {sorted(serving_df.columns)}"
        )

    result = serving_df.copy()
    result["rag_signal"] = result["vix"].apply(
        lambda v: compute_rag_signal(v).value
    )

    if len(result) > 0:
        distribution = result["rag_signal"].value_counts().to_dict()
        logger.info("RAG signal distribution: %s", distribution)

    return result
