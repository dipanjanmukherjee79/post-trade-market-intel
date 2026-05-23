"""End-to-end pipeline entrypoint.

Stages: ingestion -> storage -> transformation -> quality -> metric -> signal.
For now only the ingestion stage is wired up; downstream stages are stubbed
with log markers until they are implemented.

Run locally:
    make run

Or directly:
    python scripts/run_pipeline.py

Environment:
    FRED_API_KEY            required for FRED ingestion
    DEFAULT_LOOKBACK_DAYS   optional, default 90
    LOG_LEVEL               optional, default INFO
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Make src importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env if present — supports local dev. In CI/GitHub Actions the env
# vars are injected directly, so dotenv being absent is fine.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from src.ingestion.base import IngestionOutcome
from src.ingestion.fred import FREDIngestor
from src.ingestion.yahoo import YahooIngestor
from src.transformation.alignment import (
    AlignmentError,
    align_sources,
    summarise_alignment,
)


def _setup_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main() -> int:
    _setup_logging()
    logger = logging.getLogger(__name__)

    raw_dir = Path("data/raw")
    end_date = datetime.now(timezone.utc)
    lookback_days = int(os.environ.get("DEFAULT_LOOKBACK_DAYS", "90"))
    start_date = end_date - timedelta(days=lookback_days)
    logger.info(
        "Pipeline run: date range %s -> %s (%d days)",
        start_date.date(),
        end_date.date(),
        lookback_days,
    )

    # --- FRED VIX ingestion ---
    try:
        fred = FREDIngestor(series_id="VIXCLS", output_dir=raw_dir)
    except ValueError as exc:
        logger.error("FRED ingestor init failed: %s", exc)
        return 2

    fred_result = fred.fetch(start=start_date, end=end_date)
    logger.info(
        "FRED VIXCLS outcome=%s rows=%d attempts=%d duration=%.2fs path=%s",
        fred_result.outcome.value,
        fred_result.rows_fetched,
        fred_result.attempts,
        fred_result.duration_seconds,
        fred_result.output_path,
    )

    # --- Yahoo S&P 500 ingestion ---
    yahoo = YahooIngestor(ticker="^GSPC", output_dir=raw_dir)
    yahoo_result = yahoo.fetch(start=start_date, end=end_date)
    logger.info(
        "Yahoo ^GSPC outcome=%s rows=%d attempts=%d duration=%.2fs path=%s",
        yahoo_result.outcome.value,
        yahoo_result.rows_fetched,
        yahoo_result.attempts,
        yahoo_result.duration_seconds,
        yahoo_result.output_path,
    )

    # --- Transformation: source alignment ---
    # Only run alignment if both ingestors actually wrote raw files. Transient
    # failures from either source mean we don't have fresh raw to align — log
    # and exit informationally rather than crashing the alignment step.
    if (
        fred_result.output_path is not None
        and yahoo_result.output_path is not None
    ):
        try:
            fred_raw = pd.read_parquet(fred_result.output_path)
            yahoo_raw = pd.read_parquet(yahoo_result.output_path)
            aligned = align_sources(fred_raw, yahoo_raw)
            summary = summarise_alignment(aligned)
            logger.info(
                "Alignment summary: total=%d complete=%d vix_only=%d "
                "sp500_only=%d no_data=%d date_range=%s",
                summary.total_rows,
                summary.complete_rows,
                summary.vix_only_rows,
                summary.sp500_only_rows,
                summary.no_data_rows,
                (
                    f"{summary.date_range[0].date()} -> {summary.date_range[1].date()}"
                    if summary.date_range
                    else "n/a"
                ),
            )
            # Write aligned dataset to curated layer (pre-DQ; DQ stage will
            # filter quarantine rows out into the final curated layer)
            aligned_path = Path("data/curated/aligned.parquet")
            aligned_path.parent.mkdir(parents=True, exist_ok=True)
            aligned.to_parquet(aligned_path, index=False)
            logger.info("Wrote aligned dataset to %s", aligned_path)
        except AlignmentError as exc:
            logger.error("Alignment failed: %s", exc)
            return 1
    else:
        logger.warning(
            "Skipping alignment: one or both ingestors did not produce raw output "
            "(fred=%s yahoo=%s)",
            fred_result.outcome.value,
            yahoo_result.outcome.value,
        )

    # --- DQ / Metrics / Signal (pending implementation) ---
    logger.info("DQ, metric, signal stages -- pending implementation")

    # Exit non-zero on permanent failure from any source.
    # Transient and empty are recoverable / informational, not pipeline-fatal —
    # but EMPTY for ^GSPC over a 90-day window is suspect and worth flagging.
    if yahoo_result.outcome == IngestionOutcome.EMPTY:
        logger.warning(
            "Yahoo returned EMPTY for ^GSPC over a multi-day window -- "
            "this is suspect for an actively-traded ticker; investigate"
        )

    permanent_failures = [
        r for r in (fred_result, yahoo_result)
        if r.outcome == IngestionOutcome.PERMANENT_FAILURE
    ]
    if permanent_failures:
        logger.error(
            "Permanent ingestion failure(s) -- failing pipeline run: %s",
            [r.source for r in permanent_failures],
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
