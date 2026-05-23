# ADR-0001: Storage and transformation layer

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Supersedes | — |

## Context

The case study requires:

- Ingestion of two daily time series (FRED VIX, Yahoo S&P 500) on a scheduled basis
- **Storage layer separated from transformation layer** (explicit requirement)
- Local execution with a README setup
- Data quality outcomes logged and quarantined, not silently dropped
- A hosted Streamlit dashboard reading curated data
- A 5-day delivery timeline
- Code a junior engineer can extend within the team's standards

Data volume is small and well-bounded: ~250 trading days per year per series, two numeric values per row. Total dataset size remains well under 1 MB even with several years of history. There is no concurrent-write requirement, no multi-user analytics, no streaming, and no need for transactional guarantees beyond "don't corrupt the file."

The architectural decision is therefore not "which warehouse" but "what is the minimum credible storage stack that still demonstrates the raw-vs-curated separation the brief asks for, and that can scale up the data product roadmap if the platform expands."

## Decision

Use **DuckDB as the query engine** with **Parquet files as the on-disk storage format**, arranged in two physically separate directories:

- `data/raw/` — landing zone for source-shape Parquet files (one per source per ingestion run)
- `data/curated/` — post-transformation Parquet files (aligned, validated, metric-ready)

DuckDB reads and writes both directories. Transformation logic in `src/transformation/` operates on raw and emits to curated. The dashboard reads exclusively from curated. No code path writes to raw from outside ingestion, and no code path writes to curated from outside transformation.

## Rationale

DuckDB plus Parquet was chosen because it is the smallest stack that satisfies every functional requirement without compromise:

1. **Zero infrastructure dependency.** Pip-installable, embedded engine, no daemon, no Docker, no credentials. Runs anywhere Python runs, which is what "must run locally" requires.
2. **Native columnar storage via Parquet.** Efficient for time-series data, language-agnostic, readable by any future tool (Spark, Trino, Polars, pandas) without re-engineering.
3. **First-class SQL with window functions.** The 20-day rolling SMA is a one-line `OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)` query. No bespoke iteration code.
4. **Streamlit-compatible.** DuckDB and Parquet are both readable directly from the dashboard process with no network or auth.
5. **Pattern survives scale-up.** The raw → curated directory structure mirrors the bronze and silver stages of a medallion architecture, which is the standard layering pattern in any modern lakehouse. The migration path to a production deployment preserves the layering and swaps out the underlying engines — storage moves to an object store, the query engine moves to a cloud-native compute layer, and transformations move to a managed orchestration framework. The choice of specific platform (e.g. Snowflake, Databricks, or an open-table-format lakehouse) is deliberately deferred and would be made based on the wider platform strategy, not by this pipeline. No code reorganisation is required for any of these targets.

## Consequences

### Positive

- A junior engineer can read, query, and modify the entire data layer with `duckdb` CLI and standard SQL knowledge.
- No deployment surface area — the entire stack ships in the repo.
- The transformation layer is genuinely a different file from the storage layer, satisfying the brief unambiguously.
- Adding a third source is a matter of writing one ingestion module and one Parquet file path. No schema migrations.

### Negative / Trade-offs

- **Single-writer model.** DuckDB on the same file does not support concurrent writes. Acceptable here because the pipeline runs as a single scheduled job. Documented in the README.
- **DuckDB is less familiar than Postgres or SQLite.** Junior engineers may need a short ramp-up. Mitigated by the fact that the SQL dialect is near-standard and the documentation is excellent.
- **Files in `data/curated/` are committed to the repo for dashboard hosting.** This is unconventional. Justified because data volume is trivial and Streamlit Cloud reads from the repo. Flagged for review if data volume grows beyond ~10 MB.

### Mitigations

- The README documents the single-writer constraint and the file-in-repo pattern explicitly.
- `CONTRIBUTING.md` includes a section on extending storage — what to do if the next source needs a different shape.

## Alternatives considered

### Option A: Postgres
Rejected. Requires Docker or a managed instance for local execution, adds credentials management, adds a service to start before the pipeline runs. Overkill for two daily series with no concurrency requirement. The README setup would become significantly heavier with no functional benefit at this scope.

### Option B: SQLite with raw tables
Rejected. Row-oriented storage is suboptimal for analytical queries on time-series data. SQLite's window function support is limited compared to DuckDB. Has no clear advantage over DuckDB for this workload.

### Option C: Full lakehouse architecture (managed transformation, object-store backed, open or proprietary table format)
Rejected at this scope. A lakehouse with a managed transformation framework over an object-store-backed table layer is the appropriate target for a production data platform with multiple sources, multiple contributors, and operational reliability requirements. Specific platform choice — for example Snowflake, Databricks, or an open-table-format stack on a cloud-native query engine — would follow the wider organisation's data platform strategy and is intentionally not pre-decided here. For a two-source, single-developer, 5-day prototype, the operational overhead of any of these options consumes more time than it saves. Documented as the v2 migration path in the "If I had more time" slide.

### Option D: Plain Parquet files with pandas, no query engine
Rejected. Loses SQL ergonomics for transformation logic. The metric calculations end up as imperative pandas code that is harder to review and harder for junior engineers to extend safely. SQL is the standard contract for transformation in a production team; using it here keeps the pattern transferable.

## Open questions / future revisions

- If a third or fourth source is added (e.g. RBA cash rate, ASX 200), revisit whether the raw schema should be normalised into a single tall fact table keyed on `(date, series_id)` rather than one file per source. Likely yes at three or more sources.
- If the data volume grows past ~10 MB, the file-in-repo pattern should be replaced with a dedicated storage location (S3, Streamlit secrets-backed cloud DB, or a separate data repository).
- If concurrent writes become a requirement (e.g. multiple parallel ingestion jobs), DuckDB is no longer suitable and we move to Postgres or Iceberg-backed storage.

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-20 | Dipanjan Ghosh | Initial decision |
