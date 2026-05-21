"""Tests for src/ingestion/base.py.

Covers:
- retry_with_backoff: retry, give-up, no-retry-on-permanent
- Ingestor: success / transient-recovery / permanent-failure / empty / idempotent paths
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.base import (
    Ingestor,
    IngestionOutcome,
    retry_with_backoff,
)


# --------------------------------------------------------------------- fixtures


class _FakeIngestor(Ingestor):
    """Test double for the abstract Ingestor.

    Configurable to raise N times before succeeding, raise a specific exception,
    return empty, or return a specific DataFrame. Tracks how many times _fetch_raw
    was invoked.
    """

    source_name = "fake"

    def __init__(
        self,
        output_dir: Path,
        raise_count: int = 0,
        exception_class: type[BaseException] = TimeoutError,
        empty: bool = False,
        invalid_schema: bool = False,
    ):
        super().__init__(output_dir)
        self._raise_count_remaining = raise_count
        self._exception_class = exception_class
        self._empty = empty
        self._invalid_schema = invalid_schema
        self.fetch_call_count = 0

    def _fetch_raw(self, start: datetime, end: datetime) -> pd.DataFrame:
        self.fetch_call_count += 1
        if self._raise_count_remaining > 0:
            self._raise_count_remaining -= 1
            raise self._exception_class("simulated failure")
        if self._empty:
            return pd.DataFrame()
        return pd.DataFrame({"date": [start], "value": [1.0]})

    def _validate_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        if self._invalid_schema:
            raise ValueError("schema violation: missing required column")
        return df


# ============================================================ retry_with_backoff


def test_retry_succeeds_on_first_attempt():
    calls: list[int] = []

    def fn():
        calls.append(1)
        return "ok"

    assert retry_with_backoff(fn) == "ok"
    assert len(calls) == 1


def test_retry_recovers_from_transient_failures():
    calls: list[int] = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("transient")
        return "ok"

    result = retry_with_backoff(fn, base_delay_seconds=0.01)
    assert result == "ok"
    assert len(calls) == 3


def test_retry_gives_up_after_max_attempts():
    calls: list[int] = []

    def fn():
        calls.append(1)
        raise TimeoutError("persistent transient")

    with pytest.raises(TimeoutError):
        retry_with_backoff(fn, max_attempts=2, base_delay_seconds=0.01)
    assert len(calls) == 2


def test_retry_does_not_retry_permanent_exceptions():
    calls: list[int] = []

    def fn():
        calls.append(1)
        raise ValueError("permanent — schema change")

    with pytest.raises(ValueError):
        retry_with_backoff(fn, base_delay_seconds=0.01)
    assert len(calls) == 1


def test_retry_rejects_invalid_max_attempts():
    with pytest.raises(ValueError):
        retry_with_backoff(lambda: None, max_attempts=0)


# ============================================================ Ingestor.fetch


def test_ingestor_success_writes_parquet(tmp_path: Path):
    ing = _FakeIngestor(tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.rows_fetched == 1
    assert result.attempts == 1
    assert result.error_message is None
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.data is not None
    # Parquet round-trip
    reread = pd.read_parquet(result.output_path)
    assert len(reread) == 1


def test_ingestor_recovers_from_transient_failures(tmp_path: Path):
    ing = _FakeIngestor(tmp_path, raise_count=2, exception_class=TimeoutError)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.attempts == 3
    assert ing.fetch_call_count == 3


def test_ingestor_classifies_exhausted_transient_failures(tmp_path: Path):
    ing = _FakeIngestor(tmp_path, raise_count=10, exception_class=TimeoutError)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE
    assert result.attempts == _FakeIngestor.max_attempts
    assert result.error_message is not None
    assert "simulated failure" in result.error_message


def test_ingestor_classifies_permanent_failure_from_fetch(tmp_path: Path):
    ing = _FakeIngestor(tmp_path, raise_count=1, exception_class=ValueError)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert result.attempts == 1  # not retried
    assert result.error_message is not None


def test_ingestor_classifies_permanent_failure_from_validation(tmp_path: Path):
    ing = _FakeIngestor(tmp_path, invalid_schema=True)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert "schema violation" in (result.error_message or "")


def test_ingestor_returns_empty_outcome_for_empty_data(tmp_path: Path):
    ing = _FakeIngestor(tmp_path, empty=True)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.EMPTY
    assert result.rows_fetched == 0
    assert result.output_path is None  # nothing written


def test_ingestor_idempotent_output_path(tmp_path: Path):
    ing = _FakeIngestor(tmp_path)
    p1 = ing._output_path(datetime(2026, 5, 1), datetime(2026, 5, 5))
    p2 = ing._output_path(datetime(2026, 5, 1), datetime(2026, 5, 5))
    assert p1 == p2


def test_ingestor_rejects_missing_source_name(tmp_path: Path):
    class _Unnamed(Ingestor):
        source_name = ""

        def _fetch_raw(self, start, end):
            return pd.DataFrame()

        def _validate_schema(self, df):
            return df

    with pytest.raises(ValueError, match="source_name"):
        _Unnamed(tmp_path)
