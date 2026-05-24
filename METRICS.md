# METRICS.md

## Purpose

This document defines the metric requirements for the Market Intelligence dashboard **before any transformation code is written**. It captures what the metrics measure, why they matter, and how edge cases are handled. Any change to a metric definition must update this document first, then propagate to code.

| Field | Value |
|---|---|
| Written | [DATE — fill in when committed] |
| Version | 1.0 |
| Owner | Dipanjan Ghosh |
| Status | Pre-implementation requirements |

## Scope

This document defines:
- The three calculated metrics displayed on the dashboard
- The RAG signal logic and thresholds
- The calendar, timezone, and missing-data handling policies that apply to all metrics

Out of scope: source selection rationale (see `docs/adrs/0001-storage-choice.md` and README), pipeline architecture, and dashboard layout.

## Audience and dashboard question

The dashboard is intended for a **financially literate but non-technical** management audience. It answers a single question:

> *"How has market activity trended over the past 90 days, and is there anything we should be watching?"*

Metric choices prioritise interpretability for this audience over analytical sophistication. Where a more sophisticated alternative was considered and rejected, the rationale is recorded inline.

## Data sources (summary)

| Role | Provider | Series | Granularity | Calendar |
|---|---|---|---|---|
| Market index | Yahoo Finance | S&P 500 (`^GSPC`) — daily OHLCV | Daily | NYSE trading calendar |
| Macro indicator | FRED | VIX (`VIXCLS`) | Daily | US business days |

Both sources are US-based and align cleanly on a single trading calendar. This was a deliberate choice to keep timezone and calendar handling tractable for v1.

---

## Cross-cutting policies

### Calendar and timezone alignment

- **Reference timezone:** `America/New_York`. All timestamps are converted at ingestion.
- **Trading day definition:** A date appears in the curated dataset if **either** source published data for it. The curated layer is the union of FRED's and Yahoo's calendars, not the intersection.
- **Alignment between sources:** **Outer join on trading day.** Rows where one source is missing data are retained and flagged. Whether they enter the metric layer is decided by the data quality stage (see Missing data policy below).
- **Non-trading days:** US weekends and dates that neither source returns data for are absent from the curated layer entirely.
- **Data freshness:** The pipeline accepts data up to T-1 (yesterday's close). The dashboard displays the most recent successful run timestamp and the date of the latest closing value used, so users can see if the data is stale.

### Why outer join, not inner join

The live ingestion run on 2026-05-23 exposed two distinct calendar mismatches between FRED and Yahoo:

1. **Holiday semantics differ.** FRED publishes a row for every US business day including market holidays, with `value = "."` (translated to NaN). Yahoo omits closed days entirely. For Good Friday (April 3, 2026), FRED has a NaN row; Yahoo has no row.

2. **Publication lag.** FRED publishes VIX after Cboe's official close (16:15 ET), which is later than Yahoo's S&P 500 close (16:00 ET). A pipeline run scheduled close to the US market close can pick up Yahoo's data but not FRED's for the same date. The next run resolves the gap.

An inner-join alignment policy would silently drop both cases — including the publication-lag case, which is a genuine valid Yahoo row lost to a scheduler timing artifact. **Inner join optimises for simplicity at the expense of information.** A senior data analytics pipeline preserves every valid observation and handles incompleteness explicitly.

### Missing data policy

- **Definition of "missing":** A trading day where either source returns null, absent, or invalid data after schema validation.
- **Curated layer construction:** Outer-join across FRED and Yahoo by trading day. Rows where any source-required column (VIX value, S&P close) is NaN are routed to the **quarantine log** and not promoted to the curated layer. Rows where all required columns are present are promoted to curated.
- **Quarantine log:** Every excluded row is written to `logs/dq_quarantine.log` with: date, reason, which source(s) were missing, run timestamp, and the partial data we did receive. This satisfies the explicit case study requirement *"Log data quality outcomes — do not silently drop bad records."*
- **No silent imputation.** Carry-forward, interpolation, and last-observation-carried-forward are not applied to filling missing values. Missing means missing.
- **Late-arriving records.** Idempotent ingestion (raw layer rewrites by date range) plus deterministic alignment (curated layer rebuilt from raw each run) means: a record missing on Monday's run that becomes available on Tuesday's run will automatically promote from quarantine to curated on Tuesday's run. No state machine is needed; the medallion architecture's "rebuild downstream from upstream" pattern handles it.
- **No backfill state.** The pipeline does not track "rows previously quarantined." Each run produces a fresh curated layer from the current raw layer. This is deliberately stateless — see ADR-0006 for the architectural rationale.

---

## Metric 1 — Rolling Simple Moving Averages of S&P 500 close (10-day and 20-day)

**What it measures (plain language):**
The average closing price of the S&P 500 over the most recent N trading days, for two values of N — a fast 10-day window and a slow 20-day window. Each trading day, the oldest value in each window drops out and the newest is added.

**Why it matters for the dashboard question:**
Daily closing prices are noisy. A rolling average smooths short-term noise and makes the underlying trend visible to a non-technical audience. Two timescales together tell a richer story than one: the 10-day captures fast regime changes (the moment when a stress regime begins or ends), the 20-day shows the slower underlying trend approximating one trading month. When the two cross, momentum has shifted. When they converge, the market is consolidating.

For a 90-day analytical window in particular, having both timescales gives the dashboard more usable signal coverage — the 10-day SMA is defined on day 10 onwards, the 20-day on day 20 onwards.

**Exact definition (both):**
For each trading day `t`, the N-day SMA equals the arithmetic mean of the S&P 500 closing prices on trading days `t-(N-1)` through `t` inclusive.

```
SMA_N(t) = mean(close_{t-(N-1)}, close_{t-(N-2)}, ..., close_t)
```

**Inputs required:**
- S&P 500 daily close price
- Trading day index (derived from S&P 500 calendar)

**Windows:**
- `sp500_sma_10`: 10 trading days, rolling, right-aligned
- `sp500_sma_20`: 20 trading days, rolling, right-aligned

**Edge cases (both):**
- **First (N-1) days of the time series:** SMA is undefined. Rendered as a gap in the dashboard overlay — never as zero, never interpolated.
- **Missing close within the window:** Each window requires N valid closes. If fewer are available (one or more days quarantined), the SMA for that day is undefined and logged.
- **Production extension (v2):** In a production deployment, the ingestion stage would fetch an additional 20-day lookback window beyond the visible range, so both SMAs are defined on every dashboard day. In v1 the lookback is internal to the curated window, which is simpler and keeps the metric computation as a pure function of the visible curated data. Documented for traceability.

**Validation expectations:**
- Each SMA value at any day `t` must be ≤ max(close in its window) and ≥ min(close in its window)
- Neither SMA can be negative
- SMA values on consecutive days cannot differ by more than the largest single-day price move within the window (sanity bound)

---

## Metric 2 — Daily percentage change of S&P 500 close

**What it measures (plain language):**
How much the S&P 500 closing price moved from the previous trading day, expressed as a percentage. Positive = up day, negative = down day.

**Why it matters for the dashboard question:**
The most intuitive measure of daily market movement for a non-technical audience. Surfaces "watchpoint" days at a glance without requiring any statistical interpretation.

**Exact definition:**
For each trading day `t`:

> daily_pct_change(t) = (close(t) − close(t-1)) / close(t-1) × 100

Where `t-1` is the **immediately preceding trading day** (not calendar day).

**Inputs required:**
- S&P 500 daily close price
- Trading day index

**Window:** Single-day comparison.

**Edge cases:**
- **First day of the time series:** Daily change is undefined. Rendered as a gap.
- **Gap caused by a holiday:** Comparison runs against the most recent valid prior trading day. For example, the Tuesday after a Monday holiday compares to the previous Friday's close. This matches how returns are reported industry-wide.
- **Gap caused by a quarantined row:** Same handling as a holiday — comparison against most recent valid prior day. The quarantined day is logged.

**Validation expectations:**
- Value falls within ±25%. The largest single-day moves in S&P 500 history are approximately −20% (Black Monday 1987) and +12% (March 2020). Anything outside ±25% is treated as a likely data error and quarantines.
- Sum of daily percentage changes across the visible window should reconcile (within rounding) to the geometric total return over that window — used as a cross-check, not a hard validation.

---

## Metric 3 — VIX level (raw, undeived)

**What it measures (plain language):**
The market's expected volatility of the S&P 500 over the next 30 days, calculated by Cboe from S&P 500 option prices and published daily. Often referred to as the "fear index" — higher values indicate the market expects more volatility, lower values indicate it expects calm.

**Why it matters for the dashboard question:**
The dashboard question asks *"is there anything we should be watching."* VIX is the single most direct published answer to that question. Plotting VIX alongside S&P 500 price allows the user to visually identify periods where the market's *expectation* of risk diverges from observed *price action*.

**Exact definition:**
The daily published VIX closing value, ingested as-is from FRED (series `VIXCLS`). No smoothing, derivation, or transformation is applied.

**Inputs required:**
- VIX daily close from FRED

**Window:** None (point-in-time per trading day).

**Edge cases:**
- **VIX present but S&P close missing on same day:** Day excluded from the aligned dataset. The VIX value is still ingested and logged but not displayed.
- **VIX value of 0 or negative:** Quarantine. VIX has historically ranged from approximately 9 to 80 — values outside [5, 100] are flagged as suspect.

**Validation expectations:**
- Value within [5, 100] inclusive
- Non-null on every aligned trading day in the curated dataset

**Design decision — why VIX is used raw, not derived:**

A derived "volatility risk premium" metric (VIX minus realised volatility of S&P returns) was considered and rejected for v1. Reasons:

1. It introduces a calculation requiring defence of an additional window choice (realised volatility over what period?)
2. Its interpretation requires market-microstructure knowledge that the dashboard audience does not have
3. The dashboard question is answerable with raw VIX alone

This decision is documented here rather than buried in code review. It is a deliberate scope choice, not an oversight.

---

## RAG signal

**Purpose:**
A single traffic-light indicator on the dashboard that gives a non-technical user an immediate read on current market stress, without requiring them to interpret the underlying charts.

**Input:** Most recent published VIX closing value (T-1).

**Logic:**

| Condition | Signal | Plain-language meaning |
|---|---|---|
| VIX < 20 | 🟢 Green | Low volatility regime |
| 20 ≤ VIX ≤ 30 | 🟡 Amber | Elevated — monitor |
| VIX > 30 | 🔴 Red | Stressed market conditions |

**Threshold rationale:**

- The 20 and 30 levels are widely cited historical benchmarks for VIX regimes and are commonly used by risk desks and market commentary as boundary markers.
- VIX has spent the majority of the post-2000 period below 20 — these are calm-market regimes.
- The 20–30 band historically associates with periods of elevated uncertainty without crisis (rate-tightening cycles, geopolitical events).
- VIX has exceeded 30 during major stress events including the 2008 financial crisis, the 2020 COVID shock, and parts of the 2022 inflation-driven correction.
- **Absolute thresholds chosen over percentile-based thresholds** so the signal is interpretable without context: "calm by any historical standard," not "calm relative to the last 90 days."

**Edge cases:**
- **Latest VIX missing or quarantined:** Signal displays as "Unavailable" with explanation. The pipeline does not silently fall back to the prior day.

**Refinement roadmap (out of scope for v1):**
- Sustained-regime logic (e.g. require N consecutive days above threshold before flipping to Red, to dampen noise)
- Composite signal incorporating S&P drawdown depth
- Calibration with the post-trade risk team for institution-specific thresholds and regulatory alignment

---

## Out of scope for v1

The following were considered and explicitly excluded from this version:

- Intraday data (daily granularity is sufficient for a 90-day trend view)
- Multiple market indices (single S&P 500 only — adding ASX 200 or sector indices is a v2 candidate)
- Rolling correlation between VIX and S&P 500 (interpretive complexity exceeds value for this audience)
- Forecasting or predictive metrics (dashboard is descriptive)
- Derived volatility metrics (see Metric 3 design decision)

## Open questions for stakeholder review

In a real engagement, the following would be confirmed with the data product owner and post-trade risk team before production deployment:

1. Should the RAG thresholds be tuned to a Macquarie-specific risk appetite, or remain at industry-standard levels?
2. Should the dashboard refresh be strict daily (T-1 close every morning) or use last-available VIX intraday?
3. Should missing days be carried forward with a "stale" indicator, or rendered as gaps?
4. Is there a model risk dimension (calibration evidence, validation reporting under SR 11-7-equivalent expectations) that affects how this dashboard can be used in decision-making?

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | [DATE] | Dipanjan Ghosh | Initial definition prior to implementation |
