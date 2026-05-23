# ADR-0005: Data contracts and schema evolution

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Related | ADR-0001 (Storage), ADR-0004 (Analytical layer), METRICS.md |

## Context

A data pipeline is a chain of producers and consumers. Each layer produces data and each layer consumes from the layer above. Without explicit contracts between layers, a change anywhere in the chain can silently break anything downstream — and the cost of that breakage is borne disproportionately by the layers closest to the user (the dashboard, the metric layer), which are the last to discover it.

The case study explicitly requires handling at least one failure scenario, naming schema change as an example. The architectural question this raises is broader than the failure case itself: **what is the contract between each pair of layers, and how does a change in a producer get validated, surfaced, and migrated rather than silently broken?**

This question is the same at two-source scale as at two-hundred-source scale. The pattern is what matters; scale only determines the tooling. Establishing the pattern at small scale is what makes growth manageable, and is what separates engineering from scripting.

## Decision

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

## Rationale

The contract pattern earns its place even at small scale for three reasons:

1. **A broken contract is detectable; a missing contract is not.** Without explicit contracts, a schema change in a source manifests as garbage data downstream, often days after the change happened. With explicit contracts, the violation surfaces at the boundary where it happened, with a clear log entry pointing at the responsible layer.
2. **Contracts are documentation that cannot drift.** A schema definition expressed in code is automatically true. A schema definition recorded in a README rots within weeks of the first refactor.
3. **The pattern scales without code rewrite.** Two-source contracts and twenty-source contracts use the same shape; only the number of contract files changes. The work invested in establishing the pattern at v1 pays compound returns as sources are added.

## Consequences

### Positive

- A schema change in a source produces a clear, logged failure at the ingestion boundary rather than silent corruption downstream. This directly satisfies the case study requirement to handle a schema-change failure scenario.
- New engineers reading the code understand what each layer expects to receive and produce, without having to trace runtime behaviour.
- The DQ quarantine pattern (established in METRICS.md and ADR-0001) is the enforcement mechanism — every contract violation lands in the quarantine log with a reason. There is no separate "contract violation" handling to build; the existing log is the contract enforcement record.
- The contract layer is the natural attachment point for future regulatory, audit, and governance requirements (lineage, calibration evidence, change history). Establishing the pattern now means those requirements can be retro-fitted without restructuring.

### Negative / Trade-offs

- **Contracts add code that produces no visible output.** A schema definition for two daily values is overhead at this scope. Acknowledged. Mitigation: contracts are kept minimal — type, range, presence; nothing more.
- **Schema evolution is procedural rather than tooled at v1.** A production platform would have automated tooling for versioned schemas, contract negotiation, and consumer notification. At this scope, it is a CONTRIBUTING.md convention and code review. Acceptable for the prototype; explicitly v2 work for production.
- **No formal data catalogue or lineage tooling.** Contracts are local to each layer; there is no central registry. The file path of each contract is implicit lineage. Documented as v2 direction.

### Mitigations

- The quarantine log (`logs/dq_quarantine.log`) is the runtime contract-violation record. Any record failing a contract is written to quarantine with the contract name and the failure reason.
- README and CONTRIBUTING.md document how to extend a contract — what to update, what to test, what to document.

## Alternatives considered

### Option A: Implicit schemas (read what arrives)
Read whatever comes in, infer types at runtime, hope for the best. Rejected — this is the failure mode the case study explicitly calls out. Implicit schemas turn schema changes into silent data corruption that is discovered, if ever, by the dashboard user noticing wrong numbers.

### Option B: Fail-fast with no recovery
Detect schema violations and crash the pipeline. Rejected — too brittle for a system ingesting from external sources. A single bad row from FRED's "`.`-for-holiday" pattern should not stop the daily refresh. Quarantine and continue is the right behaviour.

### Option C: Adopt a formal data contract framework
Use a dedicated product that handles contract definition, validation, evolution, and consumer notification centrally. Rejected at this scope — operational overhead is unjustified for two sources. The pattern in this ADR is the conceptual prerequisite for adopting such a framework later; the framework itself is a v2 decision.

### Option D: Contracts as runtime assertions only, not persisted as definitions
Validate at boundaries but do not persist schema definitions in code or files. Rejected — loses the documentation property that is half the value of contracts. A schema must be inspectable without running the pipeline.

## Open questions / future revisions

- At what platform scale should contracts move from in-code definitions to a central registry? Pragmatic threshold: when more than three consumers depend on the same producer's contract.
- How should contract versions interact with metric versions (ADR-0004)? Likely they should be co-versioned — a metric that depends on a schema is tied to the schema version it was computed against. Worth a dedicated ADR at platform scale.
- Should contracts include lineage metadata (which upstream system, which transformation produced this)? At platform scale, yes. At this scope, the file path of the producing layer is implicit lineage and is sufficient.

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-20 | Dipanjan Ghosh | Initial decision |
