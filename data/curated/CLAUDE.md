# CLAUDE.md — agent instructions for this repository

This file tells Claude (and similar AI assistants) how to work in this repo. The objective is consistent, reviewable, test-backed engineering output regardless of who or what is writing the code.

## Project context

- This is a case study deliverable for a Data & Analytics Engineering Lead role.
- The scope is deliberately constrained — two daily time series, three metrics, one dashboard.
- The architectural pattern (medallion layering, contracted boundaries, separated metric layer) matters more than the code volume.
- Architectural decisions live in `docs/adrs/` — read them before proposing changes that touch their subject matter.

## Hard rules

1. **METRICS.md is the metric contract.** Do not add, remove, or change a metric in code without updating METRICS.md in the same change.
2. **Storage layers are physical, not conceptual.** `data/raw/`, `data/curated/`, `data/serving/` are real directories. Do not collapse them.
3. **Transformations never write to their input layer.** A function that reads from `data/raw/` writes to `data/curated/`. Never the same layer.
4. **The dashboard reads only from `data/serving/`.** Do not import metric computation into `dashboard/`.
5. **Data quality violations go to `logs/dq_quarantine.log`** with a structured reason. Never silently drop a row.
6. **Tests precede or accompany code.** A PR without tests for new logic is incomplete.

## Style

- Type hints on all public functions.
- Docstrings on every module and every public class/function.
- Prefer pure SQL (DuckDB) for transformations and metrics where possible. Use Python only for orchestration, I/O, and logic that SQL cannot express cleanly.
- Logging via stdlib `logging`, structured where practical. No `print()` in non-script code.

## Working with this codebase

When asked to add a new source, follow the pattern in `src/ingestion/base.py`. When asked to add a metric, update METRICS.md first, then implement.

When in doubt, ask before guessing.
