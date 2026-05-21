# Architecture Decision Records

## About this document

This document consolidates the five architecture decision records (ADRs) for the Market Intelligence Platform case study. Each ADR is also maintained as a separate file in `docs/adrs/` following the standard one-decision-per-file convention. This consolidated view exists for reviewers who prefer to read the decisions linearly.

ADRs follow a MADR-style format: status, context, decision, rationale, consequences, alternatives considered, and open questions. Status is "Accepted" for all five — no decision has been superseded.

## Table of contents

1. [ADR-0001: Storage and transformation layer](#adr-0001-storage-and-transformation-layer)
2. [ADR-0002: Scheduling and orchestration](#adr-0002-scheduling-and-orchestration)
3. [ADR-0003: RAG signal threshold logic](#adr-0003-rag-signal-threshold-logic)
4. [ADR-0004: Analytical layer and metric contract architecture](#adr-0004-analytical-layer-and-metric-contract-architecture)
5. [ADR-0005: Data contracts and schema evolution](#adr-0005-data-contracts-and-schema-evolution)

---

## ADR-0001: Storage and transformation layer

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Supersedes | — |

### Context

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

### Decision

Use **DuckDB as the query engine** with **Parquet files as the on-disk storage format**, arranged in two physically separate directories:

- `data/raw/` — landing zone for source-shape Parquet files (one per source per ingestion run)
- `data/curated/` — post-transformation Parquet files (aligned, validated, metric-ready)

DuckDB reads and writes both directories. Transformation logic in `src/transformation/` operates on raw and emits to curated. The dashboard reads exclusively from curated. No code path writes to raw from outside ingestion, and no code path writes to curated from outside transformation.

### Rationale

DuckDB plus Parquet was chosen because it is the smallest stack that satisfies every functional requirement without compromise:

1. **Zero infrastructure dependency.** Pip-installable, embedded engine, no daemon, no Docker, no credentials. Runs anywhere Python runs, which is what "must run locally" requires.
2. **Native columnar storage via Parquet.** Efficient for time-series data, language-agnostic, readable by any future tool (Spark, Trino, Polars, pandas) without re-engineering.
3. **First-class SQL with window functions.** The 20-day rolling SMA is a one-line `OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)` query. No bespoke iteration code.
4. **Streamlit-compatible.** DuckDB and Parquet are both readable directly from the dashboard process with no network or auth.
5. **Pattern survives scale-up.** The raw → curated directory structure mirrors the bronze and silver stages of a medallion architecture, which is the standard layering pattern in any modern lakehouse. The migration path to a production deployment preserves the layering and swaps out the underlying engines — storage moves to an object store, the query engine moves to a cloud-native compute layer, and transformations move to a managed orchestration framework. The choice of specific platform (e.g. Snowflake, Databricks, or an open-table-format lakehouse) is deliberately deferred and would be made based on the wider platform strategy, not by this pipeline. No code reorganisation is required for any of these targets.

### Consequences

#### Positive

- A junior engineer can read, query, and modify the entire data layer with `duckdb` CLI and standard SQL knowledge.
- No deployment surface area — the entire stack ships in the repo.
- The transformation layer is genuinely a different file from the storage layer, satisfying the brief unambiguously.
- Adding a third source is a matter of writing one ingestion module and one Parquet file path. No schema migrations.

#### Negative / Trade-offs

- **Single-writer model.** DuckDB on the same file does not support concurrent writes. Acceptable here because the pipeline runs as a single scheduled job. Documented in the README.
- **DuckDB is less familiar than Postgres or SQLite.** Junior engineers may need a short ramp-up. Mitigated by the fact that the SQL dialect is near-standard and the documentation is excellent.
- **Files in `data/curated/` are committed to the repo for dashboard hosting.** This is unconventional. Justified because data volume is trivial and Streamlit Cloud reads from the repo. Flagged for review if data volume grows beyond ~10 MB.

#### Mitigations

- The README documents the single-writer constraint and the file-in-repo pattern explicitly.
- `CONTRIBUTING.md` includes a section on extending storage — what to do if the next source needs a different shape.

### Alternatives considered

#### Option A: Postgres
Rejected. Requires Docker or a managed instance for local execution, adds credentials management, adds a service to start before the pipeline runs. Overkill for two daily series with no concurrency requirement. The README setup would become significantly heavier with no functional benefit at this scope.

#### Option B: SQLite with raw tables
Rejected. Row-oriented storage is suboptimal for analytical queries on time-series data. SQLite's window function support is limited compared to DuckDB. Has no clear advantage over DuckDB for this workload.

#### Option C: Full lakehouse architecture (managed transformation, object-store backed, open or proprietary table format)
Rejected at this scope. A lakehouse with a managed transformation framework over an object-store-backed table layer is the appropriate target for a production data platform with multiple sources, multiple contributors, and operational reliability requirements. Specific platform choice — for example Snowflake, Databricks, or an open-table-format stack on a cloud-native query engine — would follow the wider organisation's data platform strategy and is intentionally not pre-decided here. For a two-source, single-developer, 5-day prototype, the operational overhead of any of these options consumes more time than it saves. Documented as the v2 migration path in the "If I had more time" slide.

#### Option D: Plain Parquet files with pandas, no query engine
Rejected. Loses SQL ergonomics for transformation logic. The metric calculations end up as imperative pandas code that is harder to review and harder for junior engineers to extend safely. SQL is the standard contract for transformation in a production team; using it here keeps the pattern transferable.

### Open questions / future revisions

- If a third or fourth source is added (e.g. RBA cash rate, ASX 200), revisit whether the raw schema should be normalised into a single tall fact table keyed on `(date, series_id)` rather than one file per source. Likely yes at three or more sources.
- If the data volume grows past ~10 MB, the file-in-repo pattern should be replaced with a dedicated storage location (S3, Streamlit secrets-backed cloud DB, or a separate data repository).
- If concurrent writes become a requirement (e.g. multiple parallel ingestion jobs), DuckDB is no longer suitable and we move to Postgres or Iceberg-backed storage.

---

## ADR-0002: Scheduling and orchestration

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Supersedes | — |

### Context

The case study requires ingestion to run on a **scheduled or repeatable basis**. The dashboard is hosted on Streamlit Community Cloud and refreshes its data from the curated layer. We need a scheduler that:

- Triggers the pipeline at least once per trading day
- Runs without manual intervention
- Produces visible, auditable logs of each run
- Costs nothing to operate (case study scope)
- Can be operated by a junior engineer without infrastructure access
- Continues to work when the developer's laptop is off

Production-grade orchestrators (Airflow, Prefect, Dagster) are designed for hundreds of interdependent tasks with complex retry, backfill, SLA, and lineage requirements. We have one workflow with two sources, three transformation steps, one data-quality stage, and one signal computation. The scheduler decision is therefore not about orchestration richness — it is about choosing the least operational surface area that still satisfies the brief.

### Decision

Use **GitHub Actions** as the scheduler. A single workflow (`.github/workflows/refresh.yml`) runs on a `cron` schedule at 22:00 UTC on US business days. The workflow:

1. Checks out the repository
2. Sets up Python and installs dependencies
3. Runs `python scripts/run_pipeline.py`, which executes ingestion → storage → transformation → quality → signal
4. Commits the updated `data/curated/` Parquet files back to the repository on the `main` branch
5. Uploads run logs as a workflow artifact

Streamlit Cloud watches the repository and redeploys on commit, so the dashboard refreshes automatically within minutes of pipeline completion. The pipeline also runs locally via `make run` for development and ad-hoc execution.

### Rationale

GitHub Actions wins for five reasons:

1. **Free and already part of the submission surface.** The repo is being submitted to GitHub anyway. The scheduler comes with it. No additional account, infrastructure, or hosting is required.
2. **Visible to reviewers.** Anyone with read access to the repo can see the workflow file, the run history, the logs, and the exit codes. This is the same visibility a production team would want — the panel sees it for free.
3. **Junior-friendly.** The workflow file is ~30 lines of YAML and reads like a recipe. A junior engineer modifying the schedule, adding a new source, or fixing a failing run does not need to learn an orchestrator's DAG syntax.
4. **Reproducible environment.** Each run starts from a clean Ubuntu image. There is no drift between developer machines and the scheduled run.
5. **Built-in observability.** GitHub Actions records each run with timestamps, exit codes, log output, and re-run capability. Failed runs send notifications by default. This satisfies the "log data quality outcomes" requirement at the infrastructure layer in addition to the application layer.

### Consequences

#### Positive

- Zero operational cost.
- The scheduler, the code, and the data live in one place — the repo. Reviewers and team members can audit the entire pipeline from a single URL.
- Dashboard refresh is automatic: commit to `main` triggers Streamlit redeploy.
- A junior engineer can take this over with a single page of documentation in the README.

#### Negative / Trade-offs

- **Scheduled runs are not real-time.** GitHub Actions cron has up to 15 minutes of latency from the scheduled trigger time. Acceptable for a daily T-1 dashboard; documented in the README.
- **Coupling between data and code in the repo.** The committed Parquet files in `data/curated/` are an unconventional pattern. Justified by the trivial data volume and the need for Streamlit Cloud to read them without separate infrastructure. Revisit if data volume grows.
- **No native concept of DAGs, sensors, or backfill.** If the pipeline grows beyond a linear sequence — for example, parallel ingestion of many sources or backfill of a date range — this scheduler becomes inadequate.
- **GitHub Actions is not a regulated-bank-grade scheduler.** Suitable for a public-data prototype; not suitable for a production system where pipeline metadata is itself regulated.

#### Mitigations

- The workflow includes a manual trigger (`workflow_dispatch`) so the pipeline can be re-run on demand.
- The pipeline is idempotent — re-running it produces the same curated output for the same input. This is the only safety mechanism we need at this scope.

### Alternatives considered

#### Option A: Local cron + shell script
Rejected. Does not run when the developer machine is off. No log retention. Not portable to other team members. No visibility for reviewers.

#### Option B: Apache Airflow
Rejected at this scope. Airflow requires a metadata database, a scheduler process, a webserver, and a worker process. For one workflow with five linear steps, this is operational overhead with no functional benefit. Airflow is the right answer at a platform scale of dozens of pipelines with complex inter-task dependencies, and is mentioned in the "If I had more time" slide as the natural migration target when the platform grows.

#### Option C: Prefect or Dagster (managed)
Rejected. Modern orchestrators with better UX than Airflow, but still introduce an external service dependency and a hosted account. For this scope they offer no advantage over GitHub Actions, which is already required for the repo.

#### Option D: APScheduler running inside a long-lived Python process
Rejected. Requires somewhere to host the long-lived process. No log retention or visibility without additional tooling. No advantage over GitHub Actions.

#### Option E: AWS EventBridge + Lambda (or equivalent cloud-native)
Rejected for this case study. Adds a cloud account dependency for the reviewer to run anything locally. Would be a credible production choice in a real engagement and is mentioned in the v2 roadmap.

### Open questions / future revisions

- If the pipeline grows to handle more than one source class (e.g. macro + market + alternative data), revisit whether a proper orchestrator is justified. Likely yes at five or more sources or any cross-source dependency logic.
- If the dashboard becomes user-interactive (filters, parameter changes that re-trigger computation), the scheduler model needs to be supplemented by an on-demand compute layer.
- If the pipeline ever ingests data that is itself subject to model risk or regulatory lineage requirements, GitHub Actions is no longer the appropriate scheduler — the run metadata becomes a regulated artifact and needs a tool with formal audit support.

---

## ADR-0003: RAG signal threshold logic

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Supersedes | — |
| Related | METRICS.md (metric definitions and signal contract) |

### Context

The dashboard is required to display a single Red/Amber/Green signal answering *"is there anything we should be watching?"* for a financially literate but non-technical audience. The case study explicitly asks for a justified threshold.

A RAG signal is a high-leverage piece of the dashboard: it sits above the charts, it is what a busy user reads first, and it is what they will quote in a meeting. The threshold logic must therefore be:

- **Interpretable without context.** A user glancing at "Amber" should know what that means without consulting a methodology document.
- **Defensible without specialist domain knowledge.** The author of this dashboard is a data engineering lead, not a market microstructure specialist. The defence of the threshold must rest on widely understood conventions, not proprietary research.
- **Stable across time.** A user who sees Green today and Green next quarter should be able to interpret both readings consistently.
- **Easy to test and maintain.** A junior engineer must be able to add tests for the signal logic and verify behaviour at boundaries.

The signal logic is also the place where over-engineering is most tempting and least rewarded. A regime-switching model, change-point detection, or composite multi-input signal would be technically more accurate but would create a "defend the model" obligation that exceeds the scope of this case study and the depth of expertise the author can credibly claim.

### Decision

Implement a **fixed-threshold RAG signal** on the **most recent published VIX value (T-1)**:

| Input condition | Signal | Interpretation |
|---|---|---|
| VIX < 20 | **Green** | Low volatility regime — calm market |
| 20 ≤ VIX ≤ 30 | **Amber** | Elevated volatility — monitor |
| VIX > 30 | **Red** | Stressed market conditions |

The signal reads only the latest available VIX close. It does not look at S&P 500 price action, does not require sustained readings, and does not adjust for time-of-day or recent history.

If the latest VIX is missing or has been quarantined by the data quality stage, the signal displays as **"Unavailable"** with the date of the last good reading.

### Rationale

The 20 and 30 thresholds are the most widely recognised regime boundaries for VIX. They are used in market commentary, sell-side research, and risk desk dashboards across the industry as conventional reference points. Their historical alignment with observable market regimes is the basis of their defence:

- **VIX has spent the majority of post-2000 trading days below 20.** This is the empirical "normal" state of US equity markets. A reading below 20 is calm by any reasonable historical reference.
- **The 20–30 band has historically associated with periods of elevated uncertainty without crisis** — rate-hike cycles, geopolitical events, earnings shocks. It is the warning zone, not the panic zone.
- **VIX has exceeded 30 during every major market stress event of the last 25 years**, including the 2008 global financial crisis, the August 2011 European debt crisis, the COVID-2020 shock (peak ~82), and parts of the 2022 inflation-driven correction. Above 30 is genuine market stress.

**Why fixed thresholds were chosen over percentile-based thresholds:**

A percentile-based threshold (e.g. "Red when VIX is in the top third of the last 90 days") was considered and rejected. The problem with percentile thresholds is that they are relative to the window, not to market reality. If the most recent 90 days were uniformly calm, a percentile-based signal would still report some days as Amber and Red — even though the absolute VIX level was firmly in the Green regime by any historical standard. The signal would say "this is the most volatile recent period," not "this is volatile in absolute terms." For the dashboard's audience and question, the absolute reading is more useful.

**Why a single-input signal was chosen over a composite signal:**

A composite signal incorporating VIX, S&P 500 drawdown, and rolling volatility was considered. It would be more accurate at distinguishing genuine stress regimes from transient spikes, but every additional input creates an additional weighting decision that must be defended. For v1, the simpler signal is more defensible. A composite is the natural v2 enhancement and is mentioned in the roadmap.

### Consequences

#### Positive

- The signal is interpretable on its own terms. A panel member asking "why Amber?" gets an answer ("VIX is 23, which is the conventional elevated-but-not-crisis band") rather than a model explanation.
- Tests for the signal logic are trivial — three input ranges, three outputs, plus the missing-data case. The full test surface is four assertions.
- The threshold can be reviewed and adjusted by the risk team without changing any code structure — only the constants change.
- The signal is interpretable historically. Anyone looking back at the dashboard during the COVID-2020 period would have seen Red and known why.

#### Negative / Trade-offs

- **Static thresholds do not adapt to regime shifts in baseline volatility.** If markets enter a sustained low-volatility regime where 15 is the new normal, the signal will report Green even when something is genuinely off relative to the new baseline. Mitigation: the thresholds are constants in code, reviewable annually.
- **Single-day reads can flicker around boundaries.** A VIX reading of 19.8 followed by 20.2 will toggle Green to Amber. The signal makes no attempt to dampen this. Mitigation: documented in the v2 roadmap as a persistence-rule enhancement.
- **The signal ignores the direction of the underlying market.** A VIX of 22 with S&P 500 rallying is treated the same as VIX of 22 with S&P 500 falling. This is intentional — the signal is about expected volatility, not direction — but a panel member may probe it. The defence is in the design.

#### Mitigations

- The dashboard displays both the VIX value and the corresponding signal, so users can see the reading that produced the colour and form their own judgement on boundary cases.
- The `notes` field on the dashboard adjacent to the signal will say something like *"Signal based on VIX close at \[date\]. Thresholds: <20 Green, 20–30 Amber, >30 Red."* This makes the logic visible without requiring the user to consult documentation.

### Alternatives considered

#### Option A: Rolling 90-day percentile thresholds
Rejected. Interpretation is window-dependent — "Red" means different absolute values in different time periods. Loses the "interpretable without context" property that is the primary requirement for a RAG on a non-technical dashboard.

#### Option B: N-day persistence rule (e.g. VIX > 30 for 3 consecutive days = Red)
Rejected for v1. Would reduce boundary flicker and produce a more conservative signal. Adds complexity that requires more justification than the simpler signal. Listed as the highest-priority v2 enhancement.

#### Option C: Composite signal — VIX + S&P 500 drawdown + realised vol
Rejected for v1. Each additional input requires defending its weight in the composite. The defence escalates quickly into model-validation territory that exceeds the scope. Documented as a v2 candidate, ideally co-designed with the post-trade risk team.

#### Option D: Statistical regime detection (HMM, change-point models)
Rejected. Black-box from a panel-defence perspective. Requires explanation of the model, its assumptions, and its training data. Inappropriate for a dashboard whose primary audience is non-technical.

#### Option E: Sell-side or vendor signal (e.g. a published market stress index)
Rejected because the case study restricts sources to publicly available data and the chosen list. Worth noting as a v2 option if the platform is permitted to license third-party signals.

### Open questions / future revisions

These would be raised with the data product owner and the post-trade risk team in a real engagement:

- **Should the thresholds be Macquarie-specific rather than industry-conventional?** A bank's risk appetite may justify tighter or looser bands. This is a calibration conversation, not an engineering decision.
- **What action does each colour imply for the post-trade team?** A RAG signal that does not drive a decision is decoration. The thresholds should be tied to operational responses (e.g. "Red triggers enhanced collateral monitoring," or similar). This is a product-owner conversation.
- **Should there be a model risk treatment for this signal?** Even simple decision-support outputs may, depending on the internal model risk framework, require calibration evidence, periodic review, and challenger model comparison. The simpler the signal, the lower the bar, but the bar exists.

---

## ADR-0004: Analytical layer and metric contract architecture

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Related | ADR-0001 (Storage and transformation), METRICS.md (metric contract) |

### Context

The case study requires the pipeline to produce three calculated metrics and a derived RAG signal. A naive implementation would treat these computations as just another step in the transformation pipeline — code that runs between curated data and the dashboard. That conflation is a common failure mode in data engineering and one that compounds rapidly as the number of metrics, consumers, or contributors grows.

The architectural question is therefore: **where do metric computations live, what contract do they fulfil, and what makes a metric different from a transformation?**

This question is worth answering even at two-source, three-metric scale because the patterns established at small scale determine whether the pipeline can absorb growth without rewrite. A pipeline that mixes data preparation and metric computation in a single layer is fast to build and slow to extend. A pipeline that separates them is fractionally slower to build and indefinitely easier to grow.

### Decision

Treat **transformation** and **metric computation** as architecturally distinct layers in the pipeline:

- **Transformations** operate on data shape and quality. They produce the curated layer — validated, aligned, type-correct facts about the world. Transformation code lives in `src/transformation/`. Output: curated Parquet files.
- **Metrics** are analytical computations expressing business meaning over curated data. They produce the serving layer — analytical outputs ready for the dashboard. Metric code lives in `src/metrics/` (and `src/signals/` for the RAG signal). Output: a derived table or view over the curated layer.

The dashboard reads exclusively from the serving layer. It does not read from the curated layer directly. It contains no metric computation logic.

`METRICS.md` is the canonical contract for metrics. Every metric in code must correspond to an entry in METRICS.md and must compute exactly what the document specifies. The implementation can change; the contract cannot change without a documented update to METRICS.md committed in the same change.

### Rationale

Four reasons the separation is justified, even at this scope:

1. **Metrics need a plain-language contract; transformations do not.** A 20-day rolling average has a precise definition that a dashboard user can interrogate ("what does this number mean?"). A timezone normalisation transformation does not — it is mechanical and invisible to the user. Different artifact, different audience, different lifecycle.
2. **Metrics are consumer-facing contracts and must be stable.** Once the dashboard depends on "daily percentage change," changing what that means breaks the user's mental model of the dashboard. Transformations can evolve as data quality work progresses; metrics should not, except via a deliberate contract change.
3. **A new metric should not require touching transformation code.** Separation lets a junior engineer add a metric by writing a SQL view, a METRICS.md entry, and a test — without needing to understand the upstream data quality logic.
4. **The same metric should produce the same answer regardless of where it is computed.** Locating metric logic in one place rather than scattering it across transformations, dashboard code, and any future report scripts is what makes that guarantee enforceable. This is the architectural prerequisite for any future metric layer, semantic layer, or feature store.

### Consequences

#### Positive

- A new metric can be added with no risk of regressing data quality or alignment logic.
- The dashboard becomes a pure rendering layer with no computation responsibility. This makes it easier to swap visualisation tools, add a second consumer of the same metrics, or expose metrics via an API in future.
- METRICS.md is the single source of truth for "what each number means," which directly addresses the case study requirement to define metrics in plain language before writing code.
- Tests for metrics can be written against the metric layer in isolation, without requiring a full pipeline run.
- The medallion layering established in ADR-0001 maps directly: raw → curated is transformation, curated → serving is metric computation.

#### Negative / Trade-offs

- **One additional layer means one additional set of files to maintain.** Mitigated by keeping the metric layer thin — at this scope each metric is one SQL view or one short Python function.
- **At three metrics, the metric layer is barely distinct from the transformation layer in volume.** The pattern is justified by what it enables at growth, not by what it saves at v1. Acknowledged risk: at this scope it can look like folder organisation dressed as architecture. Defence: the *contract* (METRICS.md) is the substantive piece, not the folder.
- **METRICS.md must stay in sync with code.** A discipline issue, not a structural one. CI enforces it via a contract-cross-check test.

#### Mitigations

- A test (`tests/test_metrics_contract.py`) cross-checks that every metric referenced in code has a corresponding entry in METRICS.md, and that every METRICS.md entry has implementing code. CI fails if they drift.
- CONTRIBUTING.md will require any metric change to update METRICS.md and the contract test in the same PR.

### Alternatives considered

#### Option A: Monolithic transformation layer
Mix metric computation into the transformation step. Curated data and metric outputs live in the same table. Rejected — produces a wide pseudo-fact table where the meaning of each column is unclear without external documentation. Common anti-pattern. Hard to extend without breaking downstream readers.

#### Option B: Compute metrics in the dashboard
The dashboard reads curated data and computes metrics on the fly. Rejected — couples metric logic to the dashboard implementation, prevents the same metric being consumed by anything other than the dashboard, and makes consistency testing harder. Also exposes the dashboard to the cost of every metric computation on every page load.

#### Option C: Eagerly precompute everything in one wide table
Compute every metric, signal, and derived value during transformation and write them all to curated as additional columns. Rejected — recomputes everything every time anything changes, conflates layers, and fails the "should this pattern survive growth" test.

#### Option D: Adopt a formal semantic layer or metric store
Use a dedicated product that enforces metric definitions, exposes them through an API, and provides governance over usage. Rejected for v1 — operational overhead exceeds the value at this scope. This is the natural v2 direction once the number of metric consumers exceeds the dashboard. The pattern established here is the conceptual prerequisite for adopting such a tool later.

### Open questions / future revisions

- At what point in platform growth does a formal metric layer become justified? Pragmatic threshold: when more than one consumer (dashboard, report, alert, downstream system) depends on the same metric definition.
- Should metric outputs be persisted (written to the serving layer) or computed on read (view-based)? Currently persisted, since DuckDB views are cheap and dashboard reads are frequent. Worth revisiting at higher cardinality.
- How should metric versioning work? A metric definition change is currently a breaking change with manual coordination cost. At platform scale this becomes a versioned-API question and warrants its own ADR.

---

## ADR-0005: Data contracts and schema evolution

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Related | ADR-0001 (Storage), ADR-0004 (Analytical layer), METRICS.md |

### Context

A data pipeline is a chain of producers and consumers. Each layer produces data and each layer consumes from the layer above. Without explicit contracts between layers, a change anywhere in the chain can silently break anything downstream — and the cost of that breakage is borne disproportionately by the layers closest to the user (the dashboard, the metric layer), which are the last to discover it.

The case study explicitly requires handling at least one failure scenario, naming schema change as an example. The architectural question this raises is broader than the failure case itself: **what is the contract between each pair of layers, and how does a change in a producer get validated, surfaced, and migrated rather than silently broken?**

This question is the same at two-source scale as at two-hundred-source scale. The pattern is what matters; scale only determines the tooling. Establishing the pattern at small scale is what makes growth manageable, and is what separates engineering from scripting.

### Decision

Define an **explicit contract at every layer boundary**, enforced at the point of write:

| Boundary | Contract owner | Validated at |
|---|---|---|
| Source → Ingestion | The source (FRED, Yahoo) — observed schema | Ingestion module: response shape, field names, types |
| Ingestion → Raw landing | Ingestion module | Schema-on-write to Parquet raw layer |
| Raw → Curated | Transformation layer | Type, range, completeness checks in `src/quality/` |
| Curated → Serving (metric) | METRICS.md | Cross-check test enforced in CI |
| Serving → Dashboard | Serving table column contract | Dashboard fails fast if a required column is missing or mistyped |

Contracts are expressed in code as typed schema definitions — Python `TypedDict` or `pydantic` models for in-memory data, Parquet schema for on-disk data. The data quality stage validates the curated layer against its contract and quarantines violators with a logged reason. A violation produces a clear log entry, not a silent drop.

Schema evolution is handled procedurally at this scope:

1. Any change to a contract is a versioned change, captured in a PR.
2. The PR documents the migration plan — what consumers are affected, what their migration is.
3. Where backwards compatibility is possible, both versions are supported during a deprecation window.

At this scope the discipline is procedural and enforced by code review. In production, contract versioning and consumer notification would be tooled.

### Rationale

The contract pattern earns its place even at small scale for three reasons:

1. **A broken contract is detectable; a missing contract is not.** Without explicit contracts, a schema change in a source manifests as garbage data downstream, often days after the change happened. With explicit contracts, the violation surfaces at the boundary where it happened, with a clear log entry pointing at the responsible layer.
2. **Contracts are documentation that cannot drift.** A schema definition expressed in code is automatically true. A schema definition recorded in a README rots within weeks of the first refactor.
3. **The pattern scales without code rewrite.** Two-source contracts and twenty-source contracts use the same shape; only the number of contract files changes. The work invested in establishing the pattern at v1 pays compound returns as sources are added.

### Consequences

#### Positive

- A schema change in a source produces a clear, logged failure at the ingestion boundary rather than silent corruption downstream. This directly satisfies the case study requirement to handle a schema-change failure scenario.
- New engineers reading the code understand what each layer expects to receive and produce, without having to trace runtime behaviour.
- The DQ quarantine pattern (established in METRICS.md and ADR-0001) is the enforcement mechanism — every contract violation lands in the quarantine log with a reason. There is no separate "contract violation" handling to build; the existing log is the contract enforcement record.
- The contract layer is the natural attachment point for future regulatory, audit, and governance requirements (lineage, calibration evidence, change history). Establishing the pattern now means those requirements can be retro-fitted without restructuring.

#### Negative / Trade-offs

- **Contracts add code that produces no visible output.** A schema definition for two daily values is overhead at this scope. Acknowledged. Mitigation: contracts are kept minimal — type, range, presence; nothing more.
- **Schema evolution is procedural rather than tooled at v1.** A production platform would have automated tooling for versioned schemas, contract negotiation, and consumer notification. At this scope, it is a CONTRIBUTING.md convention and code review. Acceptable for the prototype; explicitly v2 work for production.
- **No formal data catalogue or lineage tooling.** Contracts are local to each layer; there is no central registry. The file path of each contract is implicit lineage. Documented as v2 direction.

#### Mitigations

- The quarantine log (`logs/dq_quarantine.log`) is the runtime contract-violation record. Any record failing a contract is written to quarantine with the contract name and the failure reason.
- README and CONTRIBUTING.md document how to extend a contract — what to update, what to test, what to document.

### Alternatives considered

#### Option A: Implicit schemas (read what arrives)
Read whatever comes in, infer types at runtime, hope for the best. Rejected — this is the failure mode the case study explicitly calls out. Implicit schemas turn schema changes into silent data corruption that is discovered, if ever, by the dashboard user noticing wrong numbers.

#### Option B: Fail-fast with no recovery
Detect schema violations and crash the pipeline. Rejected — too brittle for a system ingesting from external sources. A single bad row from FRED's "`.`-for-holiday" pattern should not stop the daily refresh. Quarantine and continue is the right behaviour.

#### Option C: Adopt a formal data contract framework
Use a dedicated product that handles contract definition, validation, evolution, and consumer notification centrally. Rejected at this scope — operational overhead is unjustified for two sources. The pattern in this ADR is the conceptual prerequisite for adopting such a framework later; the framework itself is a v2 decision.

#### Option D: Contracts as runtime assertions only, not persisted as definitions
Validate at boundaries but do not persist schema definitions in code or files. Rejected — loses the documentation property that is half the value of contracts. A schema must be inspectable without running the pipeline.

### Open questions / future revisions

- At what platform scale should contracts move from in-code definitions to a central registry? Pragmatic threshold: when more than three consumers depend on the same producer's contract.
- How should contract versions interact with metric versions (ADR-0004)? Likely they should be co-versioned — a metric that depends on a schema is tied to the schema version it was computed against. Worth a dedicated ADR at platform scale.
- Should contracts include lineage metadata (which upstream system, which transformation produced this)? At platform scale, yes. At this scope, the file path of the producing layer is implicit lineage and is sufficient.

---

## Change log (consolidated document)

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-20 | Dipanjan Ghosh | Initial consolidation of ADRs 0001–0005 |
