# ADR-0002: Scheduling and orchestration

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Supersedes | — |

## Context

The case study requires ingestion to run on a **scheduled or repeatable basis**. The dashboard is hosted on Streamlit Community Cloud and refreshes its data from the curated layer. We need a scheduler that:

- Triggers the pipeline at least once per trading day
- Runs without manual intervention
- Produces visible, auditable logs of each run
- Costs nothing to operate (case study scope)
- Can be operated by a junior engineer without infrastructure access
- Continues to work when the developer's laptop is off

Production-grade orchestrators (Airflow, Prefect, Dagster) are designed for hundreds of interdependent tasks with complex retry, backfill, SLA, and lineage requirements. We have one workflow with two sources, three transformation steps, one data-quality stage, and one signal computation. The scheduler decision is therefore not about orchestration richness — it is about choosing the least operational surface area that still satisfies the brief.

## Decision

Use **GitHub Actions** as the scheduler. A single workflow (`.github/workflows/refresh.yml`) runs on a `cron` schedule at 22:00 UTC on US business days. The workflow:

1. Checks out the repository
2. Sets up Python and installs dependencies
3. Runs `python scripts/run_pipeline.py`, which executes ingestion → storage → transformation → quality → signal
4. Commits the updated `data/curated/` Parquet files back to the repository on the `main` branch
5. Uploads run logs as a workflow artifact

Streamlit Cloud watches the repository and redeploys on commit, so the dashboard refreshes automatically within minutes of pipeline completion. The pipeline also runs locally via `make run` for development and ad-hoc execution.

## Rationale

GitHub Actions wins for five reasons:

1. **Free and already part of the submission surface.** The repo is being submitted to GitHub anyway. The scheduler comes with it. No additional account, infrastructure, or hosting is required.
2. **Visible to reviewers.** Anyone with read access to the repo can see the workflow file, the run history, the logs, and the exit codes. This is the same visibility a production team would want — the panel sees it for free.
3. **Junior-friendly.** The workflow file is ~30 lines of YAML and reads like a recipe. A junior engineer modifying the schedule, adding a new source, or fixing a failing run does not need to learn an orchestrator's DAG syntax.
4. **Reproducible environment.** Each run starts from a clean Ubuntu image. There is no drift between developer machines and the scheduled run.
5. **Built-in observability.** GitHub Actions records each run with timestamps, exit codes, log output, and re-run capability. Failed runs send notifications by default. This satisfies the "log data quality outcomes" requirement at the infrastructure layer in addition to the application layer.

## Consequences

### Positive

- Zero operational cost.
- The scheduler, the code, and the data live in one place — the repo. Reviewers and team members can audit the entire pipeline from a single URL.
- Dashboard refresh is automatic: commit to `main` triggers Streamlit redeploy.
- A junior engineer can take this over with a single page of documentation in the README.

### Negative / Trade-offs

- **Scheduled runs are not real-time.** GitHub Actions cron has up to 15 minutes of latency from the scheduled trigger time. Acceptable for a daily T-1 dashboard; documented in the README.
- **Coupling between data and code in the repo.** The committed Parquet files in `data/curated/` are an unconventional pattern. Justified by the trivial data volume and the need for Streamlit Cloud to read them without separate infrastructure. Revisit if data volume grows.
- **No native concept of DAGs, sensors, or backfill.** If the pipeline grows beyond a linear sequence — for example, parallel ingestion of many sources or backfill of a date range — this scheduler becomes inadequate.
- **GitHub Actions is not a regulated-bank-grade scheduler.** Suitable for a public-data prototype; not suitable for a production system where pipeline metadata is itself regulated.

### Mitigations

- The workflow includes a manual trigger (`workflow_dispatch`) so the pipeline can be re-run on demand.
- The pipeline is idempotent — re-running it produces the same curated output for the same input. This is the only safety mechanism we need at this scope.

## Alternatives considered

### Option A: Local cron + shell script
Rejected. Does not run when the developer machine is off. No log retention. Not portable to other team members. No visibility for reviewers.

### Option B: Apache Airflow
Rejected at this scope. Airflow requires a metadata database, a scheduler process, a webserver, and a worker process. For one workflow with five linear steps, this is operational overhead with no functional benefit. Airflow is the right answer at a platform scale of dozens of pipelines with complex inter-task dependencies, and is mentioned in the "If I had more time" slide as the natural migration target when the platform grows.

### Option C: Prefect or Dagster (managed)
Rejected. Modern orchestrators with better UX than Airflow, but still introduce an external service dependency and a hosted account. For this scope they offer no advantage over GitHub Actions, which is already required for the repo.

### Option D: APScheduler running inside a long-lived Python process
Rejected. Requires somewhere to host the long-lived process. No log retention or visibility without additional tooling. No advantage over GitHub Actions.

### Option E: AWS EventBridge + Lambda (or equivalent cloud-native)
Rejected for this case study. Adds a cloud account dependency for the reviewer to run anything locally. Would be a credible production choice in a real engagement and is mentioned in the v2 roadmap.

## Open questions / future revisions

- If the pipeline grows to handle more than one source class (e.g. macro + market + alternative data), revisit whether a proper orchestrator is justified. Likely yes at five or more sources or any cross-source dependency logic.
- If the dashboard becomes user-interactive (filters, parameter changes that re-trigger computation), the scheduler model needs to be supplemented by an on-demand compute layer.
- If the pipeline ever ingests data that is itself subject to model risk or regulatory lineage requirements, GitHub Actions is no longer the appropriate scheduler — the run metadata becomes a regulated artifact and needs a tool with formal audit support.

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-20 | Dipanjan Ghosh | Initial decision |
