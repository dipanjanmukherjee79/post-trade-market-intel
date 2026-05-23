"""Tests for src/ingestion/fred.py.

All tests mock requests.get — no live HTTP. The integration smoke test against
real FRED lives in a separate suite (or is run manually) so that CI doesn't
depend on an external service.

Coverage:
- Success path: response parses, "." translates to NaN, provenance columns added
- Transient classification: 5xx, 429, requests.Timeout, requests.ConnectionError
- Permanent classification: 400, 401, 403, 404, non-JSON 200, missing observations key
- Schema validation: missing required columns, malformed date strings
- Empty observations: returns EMPTY outcome (not a failure)
- Constructor guards: empty series_id, missing API key
- Per-instance source_name → unique output paths
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from src.ingestion.base import IngestionOutcome
from src.ingestion.fred import FREDError, FREDIngestor


# --------------------------------------------------------------------- helpers


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Construct a fake requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text or (str(json_body) if json_body else "")
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _ok_response(observations: list[dict]) -> MagicMock:
    return _make_response(200, {"observations": observations})


# --------------------------------------------------------------------- constructor


def test_constructor_rejects_empty_series_id(tmp_path: Path):
    with pytest.raises(ValueError, match="series_id"):
        FREDIngestor(series_id="", output_dir=tmp_path, api_key="fake_key")


def test_constructor_rejects_missing_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        FREDIngestor(series_id="VIXCLS", output_dir=tmp_path)


def test_constructor_reads_api_key_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "env_key_value")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path)
    assert ing.api_key == "env_key_value"


def test_constructor_explicit_api_key_overrides_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "env_key")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="explicit_key")
    assert ing.api_key == "explicit_key"


def test_source_name_is_per_series(tmp_path: Path):
    a = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")
    b = FREDIngestor(series_id="DFF", output_dir=tmp_path, api_key="k")
    assert a.source_name == "fred_vixcls"
    assert b.source_name == "fred_dff"
    # Output paths are distinct
    start, end = datetime(2026, 1, 1), datetime(2026, 1, 31)
    assert a._output_path(start, end) != b._output_path(start, end)


# --------------------------------------------------------------------- success path


@patch("src.ingestion.fred.requests.get")
def test_fetch_success_parses_observations(mock_get, tmp_path: Path):
    mock_get.return_value = _ok_response([
        {"date": "2026-04-01", "value": "16.50", "realtime_start": "2026-04-01", "realtime_end": "2026-04-01"},
        {"date": "2026-04-02", "value": "17.10", "realtime_start": "2026-04-02", "realtime_end": "2026-04-02"},
    ])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 2))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.rows_fetched == 2
    assert result.data is not None
    assert list(result.data.columns) == ["date", "value", "series_id", "source", "fetched_at"]
    assert result.data["value"].tolist() == [16.50, 17.10]
    assert result.data["series_id"].iloc[0] == "VIXCLS"
    assert result.data["source"].iloc[0] == "fred_vixcls"


@patch("src.ingestion.fred.requests.get")
def test_fetch_translates_holiday_placeholder_to_nan(mock_get, tmp_path: Path):
    """FRED returns '.' for market holidays — must become NaN, not crash."""
    mock_get.return_value = _ok_response([
        {"date": "2026-04-02", "value": "17.10"},
        {"date": "2026-04-03", "value": "."},  # Good Friday — markets closed
        {"date": "2026-04-06", "value": "17.55"},
    ])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 2), datetime(2026, 4, 6))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.rows_fetched == 3  # holiday row IS kept (NaN value)
    assert pd.isna(result.data["value"].iloc[1])
    assert result.data["value"].iloc[0] == 17.10
    assert result.data["value"].iloc[2] == 17.55


@patch("src.ingestion.fred.requests.get")
def test_fetch_writes_parquet(mock_get, tmp_path: Path):
    mock_get.return_value = _ok_response([
        {"date": "2026-04-01", "value": "16.50"},
    ])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")
    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.output_path is not None
    assert result.output_path.exists()
    # Round-trip
    reread = pd.read_parquet(result.output_path)
    assert len(reread) == 1


@patch("src.ingestion.fred.requests.get")
def test_fetch_returns_empty_outcome_for_no_observations(mock_get, tmp_path: Path):
    mock_get.return_value = _ok_response([])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 2))

    assert result.outcome == IngestionOutcome.EMPTY
    assert result.rows_fetched == 0
    assert result.output_path is None


@patch("src.ingestion.fred.requests.get")
def test_fetch_redacts_api_key_from_logs(mock_get, tmp_path: Path, caplog):
    mock_get.return_value = _ok_response([{"date": "2026-04-01", "value": "16.50"}])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="secret_key_abc123")

    with caplog.at_level("DEBUG"):
        ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    log_text = " ".join(rec.message for rec in caplog.records)
    assert "secret_key_abc123" not in log_text


# --------------------------------------------------------------------- transient HTTP


@patch("src.ingestion.fred.requests.get")
def test_http_500_is_transient(mock_get, tmp_path: Path):
    mock_get.return_value = _make_response(500, text="upstream broken")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE
    # Base class will have retried max_attempts times
    assert result.attempts == FREDIngestor.max_attempts


@patch("src.ingestion.fred.requests.get")
def test_http_429_is_transient(mock_get, tmp_path: Path):
    mock_get.return_value = _make_response(429, text="too many requests")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE


@patch("src.ingestion.fred.requests.get")
def test_requests_timeout_is_transient(mock_get, tmp_path: Path):
    mock_get.side_effect = requests.exceptions.Timeout("read timed out")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE


@patch("src.ingestion.fred.requests.get")
def test_requests_connection_error_is_transient(mock_get, tmp_path: Path):
    mock_get.side_effect = requests.exceptions.ConnectionError("connection refused")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.TRANSIENT_FAILURE


@patch("src.ingestion.fred.requests.get")
def test_transient_then_success_recovers(mock_get, tmp_path: Path):
    # First two calls fail with 500, third succeeds
    mock_get.side_effect = [
        _make_response(500, text="transient"),
        _make_response(500, text="transient"),
        _ok_response([{"date": "2026-04-01", "value": "16.50"}]),
    ]
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.SUCCESS
    assert result.attempts == 3


# --------------------------------------------------------------------- permanent HTTP


@patch("src.ingestion.fred.requests.get")
def test_http_400_is_permanent(mock_get, tmp_path: Path):
    mock_get.return_value = _make_response(400, text="bad request: unknown series")
    ing = FREDIngestor(series_id="BAD_SERIES", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert result.attempts == 1  # not retried
    assert "HTTP 400" in (result.error_message or "")


@patch("src.ingestion.fred.requests.get")
def test_http_401_is_permanent(mock_get, tmp_path: Path):
    mock_get.return_value = _make_response(401, text="invalid api key")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="bad_key")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert result.attempts == 1


@patch("src.ingestion.fred.requests.get")
def test_http_404_is_permanent(mock_get, tmp_path: Path):
    mock_get.return_value = _make_response(404, text="not found")
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE


@patch("src.ingestion.fred.requests.get")
def test_non_json_200_is_permanent(mock_get, tmp_path: Path):
    bad_response = MagicMock(spec=requests.Response)
    bad_response.status_code = 200
    bad_response.text = "<html>maintenance page</html>"
    bad_response.json.side_effect = ValueError("Expecting value")
    mock_get.return_value = bad_response

    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")
    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert "non-JSON" in (result.error_message or "")


@patch("src.ingestion.fred.requests.get")
def test_missing_observations_key_is_permanent(mock_get, tmp_path: Path):
    """Schema change: FRED returns 200 with JSON but no 'observations' key."""
    mock_get.return_value = _make_response(200, {"unexpected": "shape"})
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert "observations" in (result.error_message or "")


# --------------------------------------------------------------------- schema validation


@patch("src.ingestion.fred.requests.get")
def test_missing_value_column_is_permanent(mock_get, tmp_path: Path):
    """Schema change: observations exist but lack the 'value' field."""
    mock_get.return_value = _ok_response([
        {"date": "2026-04-01"},  # no 'value'
    ])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
    assert "value" in (result.error_message or "")


@patch("src.ingestion.fred.requests.get")
def test_malformed_date_is_permanent(mock_get, tmp_path: Path):
    """Date string not parseable as YYYY-MM-DD."""
    mock_get.return_value = _ok_response([
        {"date": "01/04/2026", "value": "16.50"},  # wrong format
    ])
    ing = FREDIngestor(series_id="VIXCLS", output_dir=tmp_path, api_key="k")

    result = ing.fetch(datetime(2026, 4, 1), datetime(2026, 4, 1))

    assert result.outcome == IngestionOutcome.PERMANENT_FAILURE
