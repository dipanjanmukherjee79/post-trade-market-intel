# Contributing

This document describes the engineering standards for this repository. It is also the place where the team's AI-assisted code review process is articulated.

## Pull request checklist

Before merging:

- [ ] Tests pass: `make test`
- [ ] Lint passes: `make lint`
- [ ] METRICS.md is in sync with any metric changes (enforced by `tests/test_metrics_contract.py`)
- [ ] If a new architectural decision was made, an ADR was added to `docs/adrs/`
- [ ] If any data contract changed, the migration plan is documented in the PR description
- [ ] AI-assisted code passes the AI review checklist (below)

## AI-assisted code review

AI-generated code is welcome in this repository. It is reviewed differently from human-written code, with additional attention to common AI failure modes:

- [ ] **Imports are real**, not hallucinated. Every imported symbol is from a real package and a real exported name.
- [ ] **Type hints match reality**, not aspirations. The function actually returns what it says it returns.
- [ ] **Error handling is meaningful**, not boilerplate. `except Exception: pass` is never acceptable.
- [ ] **The code matches the architectural pattern in the relevant ADR**, not a generic web-tutorial pattern.
- [ ] **No silent fallbacks** for missing data, failed assertions, or quarantine cases.
- [ ] **Tests test behaviour**, not implementation. Mocking should be at the boundary, not the implementation detail.
- [ ] **`AGENT_LOG.md` records any non-trivial AI-assisted change** including: what was asked, what the AI produced, what was overridden, and why.

## Extending storage

See ADR-0001 for the storage layer design and ADR-0005 for data contracts.

## Extending metrics

See METRICS.md (the contract) and ADR-0004 (the architecture). Every metric needs a plain-language entry in METRICS.md before any code is written.
