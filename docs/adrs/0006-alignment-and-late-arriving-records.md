# ADR-0006: Source alignment and late-arriving record handling

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-23 |
| Author | Dipanjan Mukherjee |
| Supersedes | — |
| Related | METRICS.md (alignment and missing-data policy), ADR-0001 (medallion storage), ADR-0005 (data contracts) |

## Context

The pipeline ingests two daily time series from different providers with different operational characteristics:

- **FRED VIX (VIXCLS)** publishes once per US business day, after Cboe's official close at 16:15 ET. FRED writes a row for every business day including market holidays — closed-market days carry the literal value `"."` (translated to NaN at ingestion).
- **Yahoo Finance ^GSPC** publishes intraday and end-of-day at 16:00 ET. Yahoo omits closed-market days entirely.

These differences mean that on any given pipeline run, the two sources can disagree about which dates have data. The live ingestion run on 2026-05-23 surfaced two specific cases:

1. **Holiday semantics differ.** Good Friday (April 3, 2026) appears in FRED with NaN value; absent from Yahoo entirely.
2. **Publication lag.** The most recent trading day (Friday May 22, 2026) appeared in Yahoo's response but not FRED's, because the pipeline run occurred before FRED's publication window for the day.

A naive inner-join alignment policy — the default mental model for joining time-series data — would silently drop both cases. The Good Friday case loses minimal information (FRED's NaN row had no actual value), but the publication-lag case loses a perfectly valid Yahoo observation due to a scheduler timing artifact. For a 90-day analysis window, that is one row in 64, or ~1.5% of the dataset lost to operational coincidence.

At scale and over time, this kind of silent loss compounds. Late-arriving records are a first-class operational concern in any production data pipeline. A policy that conflates "missing because no data exists" with "missing because the upstream hasn't published yet" is a policy that ages badly.

## Decision

Three coordinated decisions, applied at the transformation stage:

1. **Outer join across sources on trading day.** The curated layer's date set is the union of FRED's and Yahoo's calendars after ingestion. Every date for which either source returned data appears as a candidate row in the curated layer.

2. **DQ quarantine routes incomplete rows out of curated.** Rows where any metric-required input (VIX value, S&P close) is NaN are written to `logs/dq_quarantine.log` with the date, the reason, which source(s) were incomplete, and the partial data received. They do not enter the curated layer. The metric layer reads only from the curated layer; quarantined rows have no impact on metric computation.

3. **Late-arriving records are handled by stateless rebuild.** Each pipeline run re-ingests raw data idempotently (same date range → same output path → overwrite) and rebuilds the curated layer from scratch from the current raw. A record missing on run N that arrives on run N+1 will automatically appear in run N+1's curated output without any explicit "promote from quarantine" logic. The pipeline holds no per-run quarantine state.

## Rationale

### Why outer join is the right choice for analytical pipelines

Inner join is the default for relational joins because relational tables represent entities and the inner join produces a logically consistent entity-relationship view. Time-series alignment is a different problem. The objects being joined are observations of separate, asynchronous publishers — and asymmetric availability is the rule, not the exception. **The right behaviour for asynchronous time-series sources is to preserve every observation and handle incompleteness explicitly.** Inner join optimises for simplicity at the cost of information.

### Why DQ-as-quarantine, not DQ-as-imputation

Carry-forward, interpolation, and last-observation-carried-forward are all forms of silent imputation. They produce a curated dataset that "looks complete" but contains synthetic values. For a regulated-environment use case — even a public-data prototype intended to demonstrate the pattern — synthetic values that look like real data are a model risk hazard. Quarantine preserves the truthfulness of the curated layer: every value present is a value the source actually published.

### Why stateless rebuild instead of stateful backfill

A stateful backfill machine would track which rows were quarantined on which runs, and on each new run, attempt to promote previously-quarantined rows that now have complete data. That works but adds complexity proportional to the number of historical quarantine events.

A stateless rebuild — each run re-ingests current data and re-aligns from scratch — achieves the same outcome with zero state. Idempotent ingestion (the date range determines the output path) plus deterministic alignment (curated is a pure function of raw) means: if FRED publishes VIX for May 22 by next Monday's run, May 22 will appear in the curated layer that run, with no explicit logic required.

This is the same pattern medallion-architecture data platforms use at scale: downstream layers are derived, not maintained. The trade-off is recomputation cost, which at this scope is trivial (one daily run, ~250 rows total).

## Consequences

### Positive

- No legitimate data is lost to scheduler timing. The Yahoo May 22 case — a real risk we observed — is correctly preserved.
- The pipeline has no quarantine state machine. Adding a third source does not require thinking about cross-source promotion logic.
- The pattern scales without code change. Whether two sources or twenty, the algorithm is the same: outer-join, DQ-validate, promote-or-quarantine.
- Quarantine log is a real audit artifact. Anyone investigating "why is the dashboard missing March 13?" has a single file with date, reason, and which source was incomplete.
- The medallion contract is preserved. Silver = "validated, trusted." Quarantined rows are visible elsewhere (the log) but never contaminate the silver layer.

### Negative / Trade-offs

- **The curated layer's row count varies day to day for the same date.** A date that is quarantined on run N due to publication lag will appear in curated on run N+1. Consumers must understand that the curated layer is the *current best view*, not an immutable record.
- **Quarantine log can grow unbounded.** At this scope (~1 quarantine row per ~64 trading days), this is negligible. At platform scale, log rotation and retention policy become a v2 concern.
- **Stateless rebuild assumes ingestion is cheap.** True at this scope (sub-second per source). False at scale with millions of rows per ingestion; that scenario would require incremental processing, but it is out of scope for this prototype and documented as the v2 migration path.

### Mitigations

- The `logs/dq_quarantine.log` schema includes a run timestamp, so a consumer asking "when was this quarantined, when did it resolve?" can correlate across runs.
- The pipeline emits a structured log line for every quarantine event, making it discoverable in CI logs and dashboards.

## Alternatives considered

### Option A: Inner join, exclude incomplete rows
Rejected. Loses valid data on publication-lag days, which are an unavoidable operational reality. Silent data loss is the worst outcome for an analytical pipeline; the policy that produces it is wrong even if it is simpler.

### Option B: Left join anchored on one source
Rejected. Privileges one source over the other arbitrarily. If anchored on FRED, Yahoo's late-arriving data on Friday is lost. If anchored on Yahoo, Good Friday's FRED row is lost. Outer join is the only option that does not privilege a source.

### Option C: Outer join with carry-forward imputation
Rejected. Imputation produces synthetic values that look like real observations. For a dashboard whose entire purpose is to surface market reality, this is the wrong kind of silence. Quarantine is honest; carry-forward is misleading.

### Option D: Stateful quarantine with explicit promotion logic
Rejected for v1. Adds complexity for no behavioural difference vs stateless rebuild at this scope. The decision could be revisited at platform scale where re-ingestion of all historical data per run is no longer feasible.

### Option E: Window-based late-arriving tolerance
Rejected for v1. Could be appropriate at platform scale (e.g. "if FRED publishes May 22's VIX within 72 hours, retroactively update curated"). At this scope, the stateless rebuild achieves the same outcome without the tolerance window.

## Open questions / future revisions

- **At what scale does stateless rebuild stop being viable?** The trigger is the cost of re-ingesting all historical raw data per run. Threshold is environment-specific but on the order of millions of rows or hundreds of sources.
- **Should quarantine log entries be versioned?** Currently each run appends new entries. At scale, deduplication and "resolved by run X" annotations would be useful.
- **Should the dashboard surface quarantine status?** A small "data quality: 3 dates pending" indicator on the dashboard would give the end user transparency into the latest run's completeness. Not in v1 scope.

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-23 | Dipanjan Mukherjee | Initial decision, driven by live-run discoveries of holiday semantics and publication-lag cases |
