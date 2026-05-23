"""Tests for src/ingestion/yahoo.py.

All tests mock yfinance.Ticker so no live network is required. The integration
smoke test against real Yahoo is run manually via `make run`.

Coverage targets:
- Constructor: empty ticker rejected; source_name normalisation (^, ., =)
- Success path: parses OHLCV, applies lowercase rename, adds provenance
- All-NaN Close -> PERMANENT (canonical scraper-broken signal)
- >50% NaN Close -> PERMANENT (heuristic threshold)
- Just-at-threshold NaN -> SUCCESS (50% exactly, since condition is strict >)
- Missing columns -> PERMANENT (schema change)
- Empty DataFrame -> EMPTY (legitimate no-data case)
- Transient: requests.Timeout, requests.ConnectionError
- YFRateLimitError -> TRANSIENT (when typed exception available)
- Transient then success recovers
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from src.ingestion.base import IngestionOutcome
from src.ingestion.yahoo import YahooDataError, YahooIngestor, YFRateLimitError


# --------------------------------------------------------------------- helpers


def _make_history_df(
    dates: list[str],
    closes: list[float | None] | None = None,
    drop_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Build a DataFrame that mimics yfinance.Ticker().history() output.

    yfinance returns a DatetimeIndex named 'Date' with columns Open/High/Low/Close/Volume.
    """
    n = len(dates)
    if closes is None:
        closes = [4000.0 + i for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": [c - 5 if c is not None else None for c in closes],
            "High": [c + 10 if c is not None else None for c in closes],
            "Low": [c - 10 if c is not None else None for c in closes],
            "Close": closes,
            "Volume": [1_000_000_000] * n,
        },
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates], name="Date"),
    )
    if drop_columns:
        df = df.drop(columns=drop_columns)
    return df


# --------------------------------------------------------------------- constructor


def test_constructor_rejects_empty_ticker(tmp_path: Path):
    with pytest.raises(ValueError, match="ticker"):
        YahooIngestor(ticker="", output_dir=tmp_path)


def test_source_name_normalises_caret(tmp_path: Path):
    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    assert ing.source_name == "yahoo_gspc"


def test_source_name_normalises_dot(tmp_path: Path):
    ing = YahooIngestor(ticker="BRK.B", output_dir=tmp_path)
    assert ing.source_name == "yahoo_brk_b"


def test_source_name_normalises_equals(tmp_path: Path):
    ing = YahooIngestor(ticker="EURUSD=X", output_dir=tmp_path)
    assert ing.source_name == "yahoo_eurusd_x"


def test_distinct_tickers_get_distinct_output_paths(tmp_path: Path):
    a = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    b = YahooIngestor(ticker="AAPL", output_dir=tmp_path)
    start, end = datetime(2026, 5, 1), datetime(2026, 5, 5)
    assert a._output_path(start, end) != b._output_path(start, end)


# --------------------------------------------------------------------- success path


@patch("src.ingestion.yahoo.yf.Ticker")
def test_fetch_success_parses_ohlcv(mock_ticker_class, tmp_path: Path):
    mock_inst = MagicMock()
    mock_inst.history.return_value = _make_history_df(
        ["2026-05-01", "2026-05-04", "2026-05-05"],
        closes=[5000.0, 5010.0, 4990.0],
    )
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.rows_fetched == 3
    assert result.data is not None

    expected_cols = {"date", "open", "high", "low", "close", "volume", "ticker", "source", "fetched_at"}
    assert set(result.data.columns) == expected_cols
    assert result.data["close"].tolist() == [5000.0, 5010.0, 4990.0]
    assert result.data["ticker"].iloc[0] == "^GSPC"
    assert result.data["source"].iloc[0] == "yahoo_gspc"


@patch("src.ingestion.yahoo.yf.Ticker")
def test_fetch_writes_parquet(mock_ticker_class, tmp_path: Path):
    mock_inst = MagicMock()
    mock_inst.history.return_value = _make_history_df(["2026-05-01"])
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.output_path is not None
    assert result.output_path.exists()
    reread = pd.read_parquet(result.output_path)
    assert len(reread) == 1


@patch("src.ingestion.yahoo.yf.Ticker")
def test_fetch_returns_empty_outcome_for_empty_dataframe(mock_ticker_class, tmp_path: Path):
    """Legitimate empty case — base classifies as EMPTY, not failure."""
    mock_inst = MagicMock()
    mock_inst.history.return_value = pd.DataFrame()
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.EMPTY
    assert result.rows_fetched == 0
    assert result.output_path is None


# --------------------------------------------------------------------- scraper-broken signals


@patch("src.ingestion.yahoo.yf.Ticker")
def test_all_nan_close_is_permanent_failure(mock_ticker_class, tmp_path: Path):
    """The canonical scraper-broken pattern: rows exist but every Close is NaN."""
    mock_inst = MagicMock()
    mock_inst.history.return_value = _make_history_df(
        ["2026-05-01", "2026-05-04", "2026-05-05"],
        closes=[None, None, None],
    )
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 5))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert result.attempts == 1  # not retried
    assert "ALL Close values are NaN" in (result.error_message or "")
    assert "scraper" in (result.error_message or "").lower()


@patch("src.ingestion.yahoo.yf.Ticker")
def test_majority_nan_close_is_permanent_failure(mock_ticker_class, tmp_path: Path):
    """Partial scraper failure: >50% NaN Close trips the heuristic."""
    mock_inst = MagicMock()
    # 3 of 4 rows have NaN close = 75%, above the 50% threshold
    mock_inst.history.return_value = _make_history_df(
        ["2026-05-01", "2026-05-04", "2026-05-05", "2026-05-06"],
        closes=[5000.0, None, None, None],
    )
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 6))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert "75%" in (result.error_message or "")


@patch("src.ingestion.yahoo.yf.Ticker")
def test_exactly_half_nan_close_is_accepted(mock_ticker_class, tmp_path: Path):
    """Boundary test: at exactly 50% NaN, threshold is NOT tripped (strict >)."""
    mock_inst = MagicMock()
    # 1 of 2 rows is NaN = 50%, threshold is strict >, so this should pass
    mock_inst.history.return_value = _make_history_df(
        ["2026-05-01", "2026-05-04"],
        closes=[5000.0, None],
    )
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 4))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.rows_fetched == 2


# --------------------------------------------------------------------- schema validation


@patch("src.ingestion.yahoo.yf.Ticker")
def test_missing_close_column_is_permanent(mock_ticker_class, tmp_path: Path):
    mock_inst = MagicMock()
    mock_inst.history.return_value = _make_history_df(
        ["2026-05-01"],
        drop_columns=["Close"],
    )
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert "Close" in (result.error_message or "")


@patch("src.ingestion.yahoo.yf.Ticker")
def test_missing_volume_column_is_permanent(mock_ticker_class, tmp_path: Path):
    mock_inst = MagicMock()
    mock_inst.history.return_value = _make_history_df(
        ["2026-05-01"],
        drop_columns=["Volume"],
    )
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE


# --------------------------------------------------------------------- transient handling


@patch("src.ingestion.yahoo.yf.Ticker")
def test_requests_timeout_is_transient(mock_ticker_class, tmp_path: Path):
    mock_inst = MagicMock()
    mock_inst.history.side_effect = requests.exceptions.Timeout("read timed out")
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE
    assert result.attempts == YahooIngestor.max_attempts


@patch("src.ingestion.yahoo.yf.Ticker")
def test_requests_connection_error_is_transient(mock_ticker_class, tmp_path: Path):
    mock_inst = MagicMock()
    mock_inst.history.side_effect = requests.exceptions.ConnectionError("refused")
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE


@patch("src.ingestion.yahoo.yf.Ticker")
def test_yfinance_rate_limit_is_transient(mock_ticker_class, tmp_path: Path):
    """YFRateLimitError (real or placeholder) should be classified as transient.

    Note: the real yfinance.exceptions.YFRateLimitError takes no constructor
    arguments — the message is baked into the class. Calling it with no args
    is portable across the real exception and our placeholder fallback.
    """
    mock_inst = MagicMock()
    mock_inst.history.side_effect = YFRateLimitError()
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE


@patch("src.ingestion.yahoo.yf.Ticker")
def test_transient_then_success_recovers(mock_ticker_class, tmp_path: Path):
    """Two transient failures, then a successful response — base should recover."""
    mock_inst = MagicMock()
    success_df = _make_history_df(["2026-05-01"], closes=[5000.0])
    mock_inst.history.side_effect = [
        requests.exceptions.Timeout("transient"),
        requests.exceptions.Timeout("transient"),
        success_df,
    ]
    mock_ticker_class.return_value = mock_inst

    ing = YahooIngestor(ticker="^GSPC", output_dir=tmp_path)
    result = ing.fetch(datetime(2026, 5, 1), datetime(2026, 5, 1))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.attempts == 3
