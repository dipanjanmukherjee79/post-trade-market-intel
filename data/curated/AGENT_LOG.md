# AGENT_LOG.md

This file records non-trivial AI-assisted decisions, overrides, and discoveries made during development. The objective is panel-visible evidence that AI output was supervised, not accepted blindly — and that the engineer engaged critically with what the system produced.

Entries are reverse-chronological. Each entry captures: **what was asked**, **what the AI produced**, **what was overridden or accepted**, and **why**.

---


## 2026-05-23 — DQ module: pure/impure shell pattern reinforced; one botched str_replace

**What was asked.** Build the DQ module (`src/quality/checks.py`) implementing the policy from ADR-0006: split aligned rows into promoted (curated) and quarantined (audit log) frames, with typed reason codes derived from the alignment-stage `*_fetched_at` provenance.

**The design contribution.** The reason taxonomy uses the two-signal pattern: `value is NaN` answers "is the value present?", `fetched_at is NaT` answers "did the source even respond?". Combined, they distinguish publication lag from value null, which are operationally different (lag resolves on next run; value null is permanent). This is only possible because the alignment stage deliberately preserved the per-source `fetched_at` columns — a design choice I almost dropped because they "looked redundant." They aren't.

**The bug I made on the orchestrator side.** When wiring DQ into `run_pipeline.py` via `str_replace`, I targeted the wrong block boundary. The intended insertion was inside the existing `try:` block (so DQ shares the same alignment exception handler). What I actually produced was a duplicate `except`/`else` clause with the DQ block at wrong indentation between them. Python's parser caught it immediately with `IndentationError: unexpected indent`.

The fix was a wider `str_replace` that rewrote the entire orchestration block cleanly, with the DQ logic inside the original `try:` block before the `except:` clause. Total impact: ~30 seconds of debugging, no functional change to behaviour. But the lesson is real: **`str_replace` operations on nested control flow are brittle when the patch crosses block boundaries.** For inserts that span an existing `except` clause, prefer a wider rewrite over a narrow insert.

**Outcome.** 15 new DQ tests, 82 total tests passing. Coverage 98%. The pure/impure separation held up cleanly: all 15 tests construct DataFrames in memory and call `assess_alignment()` directly. No fixtures, no temp paths, no mocking. The orchestration side (JSONL log writing) is exercised by the live `make run` rather than unit tests — which is correct, because that's where the I/O lives.

---

## 2026-05-23 — Alignment module: separation of "what to align" from "what to do with it"

**What was asked.** Build the alignment module (`src/transformation/alignment.py`) implementing ADR-0006's outer-join policy.

**The design choice worth noting.** I deliberately split the work into two collaborating modules rather than one. Alignment outputs an aligned-but-not-yet-validated DataFrame with NaN values for any source's missing data. The DQ stage (yet to be written) decides what to do with those NaNs — promote to curated, quarantine, or both. This matters because the two responsibilities have different lifecycles: alignment's logic is a join, which is set-theoretic and stable; DQ's logic is policy, which changes as the team's risk appetite evolves.

If the two were collapsed into a single function "align_and_filter", a DQ policy change (e.g. "we now want to retain rows with only Yahoo data") would require touching alignment code. With the split, alignment stays untouched and DQ is the only place policy lives.

**The four-bucket summary.** The `AlignmentSummary` dataclass categorises every aligned row into exactly one of: complete, vix_only, sp500_only, no_data. The four buckets sum to total_rows by construction, asserted in the code. The `no_data` bucket is Good Friday's case (FRED row with NaN, no Yahoo row) — almost missed it during design. Catching it now means the DQ stage has clean input categories to make decisions on.

**Outcome.** 15 alignment tests, 67 total tests passing. Coverage 97%. Two uncovered lines in alignment.py are a defensive MergeError guard for the should-never-happen case where validation misses a duplicate — left honestly uncovered rather than gamed with `# pragma: no cover`.

---

## 2026-05-23 — Alignment policy revised after live data exposed publication lag

**What was asked.** Decide the alignment policy between FRED VIX and Yahoo ^GSPC: inner join, left join, or outer join.

**What the AI proposed initially.** Inner join, with an open question for stakeholder review about carry-forward vs exclude. The original METRICS.md said: *"Inner join on trading day. VIX and S&P 500 must both be present for that day to enter the curated dataset."*

**What was overridden, and why.** The live ingestion run on 2026-05-23 exposed two distinct calendar mismatches between the sources:

1. Good Friday (April 3, 2026) — FRED has a NaN row, Yahoo has no row at all. Different holiday semantics.
2. May 22, 2026 — Yahoo has a row (the most recent trading day), FRED does not. This is a **publication-lag artifact**: the pipeline ran before FRED's publication window for the day, so FRED hadn't shipped VIX yet.

Under inner-join policy, May 22 would have been silently dropped — a perfectly valid Yahoo observation lost to scheduler timing. Over a 90-day window that is one row in 64, or ~1.5% data loss to operational coincidence. At platform scale, this compounds.

The push back I received from the engineer was clean: *"inner join is not a great design decision for a data analytics pipeline."* Correct. Inner join optimises for simplicity at the cost of information; analytical pipelines should preserve every valid observation and handle incompleteness explicitly.

**Revised policy.** Outer join across sources, DQ quarantine for incomplete rows, stateless rebuild handles late-arriving records via medallion-architecture idempotency. Documented in METRICS.md (alignment and missing-data sections) and ADR-0006. The architectural pattern of "downstream is derived, not maintained" means a row missing on run N that arrives on run N+1 automatically promotes from quarantine to curated without explicit logic.

**The broader lesson.** This is the second time in this session that live data overrode an upfront design choice. The first was the FRED holiday-quirks investigation (where I had over-engineered for the possibility of absent weekdays that turned out not to exist). The second is this one (where I had under-engineered for the publication-lag case that turned out to be real). **Both directions of error are surfaced only by running the code against real data — not by reasoning about it.** Worth re-emphasising in CONTRIBUTING.md: design proposals are hypotheses until they survive contact with live data.

**Outcome.** METRICS.md alignment section rewritten. ADR-0006 added. Original "open question for stakeholder review" closed — decision made and documented with rationale. Transformation/alignment code to be written against the revised policy.

---

## 2026-05-23 — Yahoo ingestor: third-party exception signature discovered the hard way

**What was asked.** Implement `YahooIngestor` with explicit handling of yfinance's known failure modes — all-NaN Close, partial NaN, missing columns, rate limits.

**What the AI produced.** Working implementation plus 17 tests. 16 passed first run; one failed.

**What broke and why.** The test for the rate-limit transient classification did:

```python
mock_inst.history.side_effect = YFRateLimitError("rate limited")
```

— the standard Python idiom of constructing an exception with a message. This raised `TypeError: YFRateLimitError.__init__() takes 1 positional argument but 2 were given`.

Investigation: `yfinance.exceptions.YFRateLimitError.__init__` has signature `(self)`. The error message ("Too Many Requests. Rate limited. Try after a while.") is **hardcoded into the class**, not passed at construction time. This is a non-standard convention compared to the Python core — most exception classes follow `Exception(message)` — but yfinance has chosen otherwise.

**Resolution.** Test fixed to call `YFRateLimitError()` with no args, which is portable across:
- The real yfinance exception (newer versions, signature `(self)`)
- Our placeholder fallback class (when import fails on older versions, signature `(self, *args, **kwargs)` inherited from Exception)

Documented in the test with an inline comment so the next person to look at it understands why the bare constructor.

**Outcome.** Tests now 52/52 passing. The lesson is broader than this one test: **third-party libraries don't always follow Python convention, and you only discover this by actually running the code, not by reading the docs.** The integration smoke run (whether unit-level or live) is where these things surface.

---

## 2026-05-23 — Yahoo ingestor: "all-NaN Close" handled as PERMANENT not EMPTY

**What was asked.** When yfinance returns a DataFrame full of NaN, should we treat it as EMPTY (no data) or PERMANENT_FAILURE (broken upstream)?

**What the AI proposed first.** Treat both as EMPTY, since technically the response is "rows with no usable content."

**What was overridden, and why.** The two cases are qualitatively different and conflating them hides real failures:

- **EMPTY** = the source legitimately had no data to give us (weekends, pre-IPO dates, extended market closures). Information correctly communicated by the upstream system.
- **All-NaN Close** = the response envelope is structurally valid but the content is broken. Something failed in the upstream producer's pipeline. For yfinance specifically, this is the canonical signal that Yahoo restructured their frontend HTML and the scraper is no longer parsing prices.

Treating the second case as EMPTY would let the pipeline silently continue with no usable data — exactly the silent-corruption anti-pattern the contract pattern is designed to prevent.

Decision: all-NaN Close raises `YahooDataError` (non-transient) -> base classifies as PERMANENT_FAILURE -> `run_pipeline.py` exits non-zero -> investigation triggered.

A 50% NaN heuristic threshold was added for the "partial scraper failure" case, with an explicit comment that it's a v1 heuristic and proper DQ tooling (Great Expectations / Soda) would replace it with a configurable expectation.

**Outcome.** Tests cover both the all-NaN and >50% NaN cases as permanent failures, plus the boundary case (exactly 50% NaN is accepted, per strict `>` operator). The pattern is documented in the module docstring of `src/ingestion/yahoo.py`.

---

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
