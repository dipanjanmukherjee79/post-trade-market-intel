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

    # --- Yahoo S&P 500 ingestion (pending implementation) ---
    logger.info("Yahoo S&P 500 ingestion -- pending implementation")

    # --- Transformation / DQ / Metrics / Signal (pending implementation) ---
    logger.info("Transformation, DQ, metric, signal stages -- pending implementation")

    # Exit non-zero only on permanent failures.
    # Transient and empty are recoverable / informational, not pipeline-fatal.
    if fred_result.outcome == IngestionOutcome.PERMANENT_FAILURE:
        logger.error("Permanent ingestion failure -- failing pipeline run")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
