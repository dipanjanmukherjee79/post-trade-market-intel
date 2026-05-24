# Post-Trade Market Intelligence Pipeline

> **Live dashboard:** https://post-trade-market-intel.streamlit.app
>

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

## Dashboard

Run locally:

```bash
make dashboard
```

This starts a Streamlit server on `localhost:8501`. The dashboard reads `data/serving/serving.parquet` (produced by `make run`) and renders:

- KPI strip with latest signal, S&P 500 close, VIX, and both moving averages
- S&P 500 close with fast (10-day) and slow (20-day) SMA overlays — NaN rendered as gaps
- VIX with horizontal RAG threshold lines at 20 (green/amber) and 30 (amber/red)
- Per-day RAG signal history across the full window
- DQ transparency section showing any quarantined dates from the latest run
- Methodology disclosure for reviewers wanting the depth

### Deploying to Streamlit Community Cloud

The dashboard is designed for the free tier of Streamlit Community Cloud:

1. Push the repo to GitHub (data files committed per ADR-0001)
2. At https://share.streamlit.io, point a new app at this repo with main file path `dashboard/app.py`
3. Set Python version to 3.12 (Streamlit Cloud default — pyproject.toml is compatible)
4. Deploy

No secrets are required for the dashboard itself — it reads only committed data. The `FRED_API_KEY` is only needed for the pipeline (`make run`), which is a developer / CI concern, not a dashboard concern.

## Documentation

- `docs/ADRs.md` — consolidated architecture decisions
- `METRICS.md` — plain-language metric contract
- `CONTRIBUTING.md` — engineering standards including AI-assisted code review
- `CLAUDE.md` — agent instructions for this repo
- `AGENT_LOG.md` — log of AI-assisted work, including failures and overrides

## Status

🚧 Work in progress. See `AGENT_LOG.md` for daily progress notes.
