# ADR-0004: Analytical layer and metric contract architecture

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Related | ADR-0001 (Storage and transformation), METRICS.md (metric contract) |

## Context

The case study requires the pipeline to produce three calculated metrics and a derived RAG signal. A naive implementation would treat these computations as just another step in the transformation pipeline — code that runs between curated data and the dashboard. That conflation is a common failure mode in data engineering and one that compounds rapidly as the number of metrics, consumers, or contributors grows.

The architectural question is therefore: **where do metric computations live, what contract do they fulfil, and what makes a metric different from a transformation?**

This question is worth answering even at two-source, three-metric scale because the patterns established at small scale determine whether the pipeline can absorb growth without rewrite. A pipeline that mixes data preparation and metric computation in a single layer is fast to build and slow to extend. A pipeline that separates them is fractionally slower to build and indefinitely easier to grow.

## Decision

Treat **transformation** and **metric computation** as architecturally distinct layers in the pipeline:

- **Transformations** operate on data shape and quality. They produce the curated layer — validated, aligned, type-correct facts about the world. Transformation code lives in `src/transformation/`. Output: curated Parquet files.
- **Metrics** are analytical computations expressing business meaning over curated data. They produce the serving layer — analytical outputs ready for the dashboard. Metric code lives in `src/metrics/` (and `src/signals/` for the RAG signal). Output: a derived table or view over the curated layer.

The dashboard reads exclusively from the serving layer. It does not read from the curated layer directly. It contains no metric computation logic.

`METRICS.md` is the canonical contract for metrics. Every metric in code must correspond to an entry in METRICS.md and must compute exactly what the document specifies. The implementation can change; the contract cannot change without a documented update to METRICS.md committed in the same change.

## Rationale

Four reasons the separation is justified, even at this scope:

1. **Metrics need a plain-language contract; transformations do not.** A 20-day rolling average has a precise definition that a dashboard user can interrogate ("what does this number mean?"). A timezone normalisation transformation does not — it is mechanical and invisible to the user. Different artifact, different audience, different lifecycle.
2. **Metrics are consumer-facing contracts and must be stable.** Once the dashboard depends on "daily percentage change," changing what that means breaks the user's mental model of the dashboard. Transformations can evolve as data quality work progresses; metrics should not, except via a deliberate contract change.
3. **A new metric should not require touching transformation code.** Separation lets a junior engineer add a metric by writing a SQL view, a METRICS.md entry, and a test — without needing to understand the upstream data quality logic.
4. **The same metric should produce the same answer regardless of where it is computed.** Locating metric logic in one place rather than scattering it across transformations, dashboard code, and any future report scripts is what makes that guarantee enforceable. This is the architectural prerequisite for any future metric layer, semantic layer, or feature store.

## Consequences

### Positive

- A new metric can be added with no risk of regressing data quality or alignment logic.
- The dashboard becomes a pure rendering layer with no computation responsibility. This makes it easier to swap visualisation tools, add a second consumer of the same metrics, or expose metrics via an API in future.
- METRICS.md is the single source of truth for "what each number means," which directly addresses the case study requirement to define metrics in plain language before writing code.
- Tests for metrics can be written against the metric layer in isolation, without requiring a full pipeline run.
- The medallion layering established in ADR-0001 maps directly: raw → curated is transformation, curated → serving is metric computation.

### Negative / Trade-offs

- **One additional layer means one additional set of files to maintain.** Mitigated by keeping the metric layer thin — at this scope each metric is one SQL view or one short Python function.
- **At three metrics, the metric layer is barely distinct from the transformation layer in volume.** The pattern is justified by what it enables at growth, not by what it saves at v1. Acknowledged risk: at this scope it can look like folder organisation dressed as architecture. Defence: the *contract* (METRICS.md) is the substantive piece, not the folder.
- **METRICS.md must stay in sync with code.** A discipline issue, not a structural one. CI enforces it via a contract-cross-check test.

### Mitigations

- A test (`tests/test_metrics_contract.py`) cross-checks that every metric referenced in code has a corresponding entry in METRICS.md, and that every METRICS.md entry has implementing code. CI fails if they drift.
- CONTRIBUTING.md will require any metric change to update METRICS.md and the contract test in the same PR.

## Alternatives considered

### Option A: Monolithic transformation layer
Mix metric computation into the transformation step. Curated data and metric outputs live in the same table. Rejected — produces a wide pseudo-fact table where the meaning of each column is unclear without external documentation. Common anti-pattern. Hard to extend without breaking downstream readers.

### Option B: Compute metrics in the dashboard
The dashboard reads curated data and computes metrics on the fly. Rejected — couples metric logic to the dashboard implementation, prevents the same metric being consumed by anything other than the dashboard, and makes consistency testing harder. Also exposes the dashboard to the cost of every metric computation on every page load.

### Option C: Eagerly precompute everything in one wide table
Compute every metric, signal, and derived value during transformation and write them all to curated as additional columns. Rejected — recomputes everything every time anything changes, conflates layers, and fails the "should this pattern survive growth" test.

### Option D: Adopt a formal semantic layer or metric store
Use a dedicated product that enforces metric definitions, exposes them through an API, and provides governance over usage. Rejected for v1 — operational overhead exceeds the value at this scope. This is the natural v2 direction once the number of metric consumers exceeds the dashboard. The pattern established here is the conceptual prerequisite for adopting such a tool later.

## Open questions / future revisions

- At what point in platform growth does a formal metric layer become justified? Pragmatic threshold: when more than one consumer (dashboard, report, alert, downstream system) depends on the same metric definition.
- Should metric outputs be persisted (written to the serving layer) or computed on read (view-based)? Currently persisted, since DuckDB views are cheap and dashboard reads are frequent. Worth revisiting at higher cardinality.
- How should metric versioning work? A metric definition change is currently a breaking change with manual coordination cost. At platform scale this becomes a versioned-API question and warrants its own ADR.

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-20 | Dipanjan Ghosh | Initial decision |
