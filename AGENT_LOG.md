# AGENT_LOG.md

This file records non-trivial AI-assisted decisions, overrides, and discoveries made during development. The objective is panel-visible evidence that AI output was supervised, not accepted blindly — and that the engineer engaged critically with what the system produced.

Entries are reverse-chronological. Each entry captures: **what was asked**, **what the AI produced**, **what was overridden or accepted**, and **why**.

---

## 2026-05-23 — Live FRED run: data tells a story, hypothesis partly wrong

**What was asked.** Run the FRED ingestor against live data for a 90-day window and verify the output makes sense.

**What we found.** 64 rows ingested in 0.44s, single attempt, no transient failures. The data captured a full market stress regime: VIX rose from the high teens in late February into the 20s in early March, peaked at 29.49 on **March 6, 2026** (the day of the disappointing US jobs report and the start of Operation Midnight Hammer strikes on Iranian infrastructure), stayed elevated through the Strait of Hormuz closure on March 20, then unwound through April and May to the high teens by window end.

**The data quality finding.** Exactly 1 NaN row in the `value` column. The diagnostic — comparing FRED's returned dates against all US weekdays in the window — confirmed that FRED returned every weekday, including Good Friday (April 3). The NaN is the translation of FRED's `.` placeholder for the closed-market day.

**Where the AI was wrong, and the correction.** When asked to predict what live FRED would look like, I hypothesised two possible quirks: (a) FRED writes `.` for closed days, and (b) FRED *might also* omit some weekdays entirely. The diagnostic showed (b) does not happen — at least for this series and window. The simpler model is correct: **FRED's calendar contract is "row per US weekday, value is `.` when markets are closed."** I had overcomplicated the design upfront. The DQ logic doesn't need to handle "absent weekday" specially; that case never arises.

This is a useful reminder: **if you cannot verify a hypothesis with live data, don't design for it speculatively.** The "fail-on-absent-weekday" path I had mentally reserved for the transformation stage can be dropped. If a future series ever does omit weekdays, that's a new investigation, not an a-priori safeguard.

**Outcome.** Live FRED works. DQ quarantine for the single Good Friday NaN happens at the transformation stage (yet to be built). The data has a strong narrative arc suitable for the dashboard demo.

---

## 2026-05-23 — Workflow note: chat-bundle downloads land as individual files

**What happened.** I received a zip bundle of updated repo files. The chat client downloaded the zip alongside the individual files I had also been shown for inline viewing, dropping them all into the same destination folder. The result was a destination full of loose `.py` files **plus** a `.zip` of the same content. My subsequent instruction `unzip ~/Downloads/post-trade-market-intel.zip` ran against the original (older) bundle, so no updates landed.

**Why this is worth recording.** It is not an AI failure, it is an operational quirk of pulling assets out of a chat session. But it cost ~20 minutes of confusion when `make run` returned the old stub output even though I believed I had updated the code. For anyone who clones this repo later or picks up where I left off, the lesson is: **trust the file timestamps, not the file names**. If you re-extract a bundle and the behaviour doesn't change, `ls -la` is the diagnostic.

**Outcome.** Real new bundle extracted via `unzip -o post-trade-market-intel.zip -d /tmp/extracted` and copied with `cp -r .../. .` to preserve dotfiles. Verified with `wc -l scripts/run_pipeline.py` returning the expected count.

---

## 2026-05-23 — Deprecation caught and fixed: pd.Timestamp.utcnow() and datetime.utcnow()

**What was asked.** Implement `FREDIngestor` with FRED-specific HTTP handling and the "." holiday placeholder translation.

**What the AI produced.** A working implementation that used `pd.Timestamp.utcnow()` for the `fetched_at` provenance column. Subsequent `scripts/run_pipeline.py` used `datetime.utcnow()` for the same provenance purpose.

**What was overridden, and why.** Running the test suite surfaced `Pandas4Warning: Timestamp.utcnow is deprecated`. The first run of `make run` later surfaced `DeprecationWarning: datetime.datetime.utcnow() is deprecated`. Both are the kind of thing that would pass CI today and break silently on the next major version. Replaced `pd.Timestamp.utcnow()` with `pd.Timestamp.now("UTC")` and `datetime.utcnow()` with `datetime.now(timezone.utc)`.

**Outcome.** Both fixed. Tests pass with zero warnings; `make run` no longer prints deprecation noise. Worth noting that the test surface was correctly built to surface deprecation warnings rather than ignore them — that's the discipline that catches latent issues before they become outages.

---

## 2026-05-21 — Ingestion base contract: per-instance source_name override

**What was asked.** Build an abstract `Ingestor` base class with retry, timeout, failure classification, structured logging, and idempotent writes.

**What the AI produced first.** A version where `source_name` was a class-level constant set on each subclass.

**What was overridden, and why.** That design works for a single-purpose subclass but doesn't extend cleanly to a parameterised one like `FREDIngestor`, which needs to ingest different FRED series (`VIXCLS`, potentially `DFF`, etc) each with a unique output path. With class-level `source_name`, a second instance would overwrite the first's class attribute, or the output path would collide.

I asked for a small refactor: keep the class-level default for backwards compatibility, but allow `source_name` to be passed at construction time. The instance attribute then shadows the class attribute and the output path becomes per-series.

The base class change was a single-line addition to `__init__`. All 13 existing tests pass without modification. `FREDIngestor("VIXCLS", ...)` now produces `data/raw/fred_vixcls_*.parquet`, `FREDIngestor("DFF", ...)` produces `data/raw/fred_dff_*.parquet`.

**Outcome.** Accepted with the refactor. The architectural pattern documented in `src/ingestion/base.py` docstring.

---

## 2026-05-21 — Failure classification: deliberate choice not to raise

**What was asked.** Should `Ingestor.fetch()` raise on permanent failures, or return a classified result?

**What the AI proposed.** Raise — that's the standard Python pattern.

**What was overridden, and why.** Returning a normalised `IngestionResult` with an outcome enum is the better design for this use case. The pipeline orchestrator inspects the outcome and decides whether to continue (e.g. transient failure on FRED but Yahoo succeeded — keep going) or to fail-stop (permanent failure across all sources). Raising would force every caller to write try/except scaffolding around every ingestion call.

The trade-off: the caller has to remember to inspect `.outcome`. Documented in the base class docstring with an example.

**Outcome.** Accepted. The pattern is now visible in `scripts/run_pipeline.py`, which inspects the outcome to decide its exit code.

---

## Template for future entries

```
## YYYY-MM-DD — Short title

**What was asked.** ...

**What the AI produced.** ...

**What was overridden, and why.** ...

**Outcome.** ...
```

---

## 2026-05-23 — Orphan src/base.py from earlier file-copy confusion

**What was found.** When `make test` was run with `--cov-report`, coverage surfaced an orphan `src/base.py` with 0% coverage. The real base contract has always lived at `src/ingestion/base.py` (100% covered). The duplicate file was a leftover from this morning's zip/loose-files extraction confusion documented in the workflow note entry.

**What was overridden, and why.** Removed `src/base.py`. Coverage recovered from 62% (misleadingly low) to 99% — the real picture.

**Outcome.** Repo no longer has a phantom file. Lesson worth keeping: **coverage reports are useful not just for "did I write tests" but for surfacing files that shouldn't exist.** A high-coverage repo with one mysterious 0% file is a stronger signal than a uniformly-medium-coverage repo.
