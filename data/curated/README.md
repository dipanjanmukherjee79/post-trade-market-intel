# Post-Trade Market Intelligence Pipeline

> Case study deliverable — a data engineering prototype demonstrating a scoped market intelligence dashboard for a fictional post-trade team.

## What this is

A small, scheduled pipeline that ingests two daily time series (FRED VIX + Yahoo S&P 500), validates and aligns them, computes a small set of metrics and a Red/Amber/Green market signal, and surfaces the result on a Streamlit dashboard.

The repository deliberately uses a minimal stack — DuckDB + Parquet + GitHub Actions + Streamlit — sized to the scope. The same architectural pattern (medallion layering, contracted boundaries) scales up to a production lakehouse without code reorganisation. The scale-up path is documented in `docs/adrs/` and visualised in `docs/architecture-target-state.mmd`.

## Quick start

```bash
make install        # install dependencies
cp .env.example .env # add your FRED_API_KEY
make run            # run the pipeline end-to-end
make dashboard      # start the Streamlit dashboard locally
```

## Layout

```
src/
  ingestion/        # source-specific fetchers (FRED, Yahoo) over a shared base contract
  storage/          # DuckDB + Parquet read/write helpers
  transformation/   # alignment, timezone normalisation
  quality/          # data quality checks + quarantine logic
  metrics/          # SMA, daily % change
  signals/          # RAG signal logic
data/
  raw/              # bronze — landed source data
  curated/          # silver — aligned and validated
  serving/          # gold — metric outputs the dashboard reads
dashboard/          # Streamlit app
tests/              # pytest tests
docs/
  adrs/             # architecture decision records
  *.mmd             # architecture diagrams (Mermaid)
scripts/            # pipeline entrypoint
.github/workflows/  # CI + scheduled refresh
```

## Documentation

- `docs/ADRs.md` — consolidated architecture decisions
- `METRICS.md` — plain-language metric contract
- `CONTRIBUTING.md` — engineering standards including AI-assisted code review
- `CLAUDE.md` — agent instructions for this repo
- `AGENT_LOG.md` — log of AI-assisted work, including failures and overrides

## Status

🚧 Work in progress. See `AGENT_LOG.md` for daily progress notes.
