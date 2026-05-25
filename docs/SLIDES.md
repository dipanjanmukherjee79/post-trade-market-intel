# Post-Trade Market Intelligence
## Case Study Presentation — Data & Analytics Engineering Lead

**Author:** Dipanjan Mukherjee
**Format:** 10 slides | 20 minutes target
**Live dashboard:** `https://post-trade-market-intel.streamlit.app`
**Source repository:** `https://github.com/dipanjanmukherjee79/post-trade-market-intel`

> **Tone note.** Slide titles use the exact section names from the case study brief so the panel can tick each requirement as we go. The narrative is business-friendly throughout; technical depth is concentrated in Slide 3 (Pipeline walkthrough) and lightly referenced in Slide 4 (Data decisions). All deeper engineering artefacts — ADRs, AGENT_LOG, METRICS.md, 115 tests — live in the repository and are available for due diligence after the session.

---

## Slide 1 — Title

**Visual:** Dashboard screenshot as background or right-side preview. Title at top-left.

**Title:** *Post-Trade Market Intelligence*
**Subtitle:** *A 90-day analytical dashboard, and the partnerships that built it*

**Presenter block:**
- Dipanjan Mukherjee
- Data & Analytics Engineering Lead — case study presentation
- *Date*

**Footer:**
- Live dashboard: `https://post-trade-market-intel.streamlit.app`
- Source: `github.com/dipanjanmukherjee79/post-trade-market-intel`

**What I say (≈45 seconds):**

> "Thank you for the time. I'm going to spend twenty minutes walking through how I approached this case study. The dashboard is live — the URL is at the bottom of this slide, and you can open it on your own laptops if that's easier than looking at my screen. But I won't make the dashboard the centre of this conversation. I want to focus on the *decisions* I made along the way — because those decisions are what I'd bring to a partnership with your team."

---

## Slide 2 — Framing

**Visual:** Three sections stacked vertically. Title above: *"What I chose to focus on, and why."*

**Section 1 — Scope choices (three columns):**

| What the brief asks | How I interpreted it | What I deliberately did NOT try to answer |
|---|---|---|
| Market intelligence dashboard, 90 days | *Can you scope a data product from an open brief?* | Predictive modelling (this is a snapshot, not a forecast) |
| One macro series, one market index | *Can you make defensible decisions under ambiguity?* | Intraday tick data (out of scope for a 90-day view) |
| RAG signal with defined threshold | *Can you build something a non-technical user can act on?* | Macquarie-specific risk calibration (a conversation, not an assumption) |
| Document AI usage and data quality | *Will you partner with the business, or just deliver code?* | Cross-asset coverage (one macro + one index is enough to demonstrate the pattern) |

**Section 2 — Why these sources (FRED VIX + Yahoo S&P 500):**

- **Lower API friction for a 5-day build** — FRED's API and the `yfinance` library are mature and well-documented; ASX historical data via RBA is also free but the API surface needs more plumbing
- **Earlier daily publication** — US market data publishes mid-evening AEST, so I had a fresh data point every working day during development. ASX data would have been a day behind for half the build
- **Universal recognition** — S&P 500 and VIX don't need explaining in a 20-minute presentation; ASX 200 + RBA cash rate would need more context-setting
- **Architecture is source-agnostic** — adding ASX is implementing the existing base ingestion contract, not a redesign. **In a production deployment for an Australian bank, ASX would be added on day one.**

**Section 3 — What the architecture is designed to support (post-trade business decisions):**

- **Performance benchmarking** — was a quiet trading month genuinely quiet, or did the whole market move?
- **Risk position sizing** — calibrated to volatility regime, not just static limits
- **Post-trade analysis** — was a slow fill caused by market conditions or by operational lag?
- **Pre-emptive operational signalling** — volatility regimes correlate with settlement risk, liquidity stress, counterparty stress

**Below all three sections:** *"This is a v1 prototype. The point isn't the dashboard itself — it's that the architecture supports these four classes of business decision, and is built to be extended."*

**What I say (≈2.5 minutes):**

> "The brief is open-ended, so my first job was to set scope. The top section captures what the brief asks, how I interpreted it, and just as importantly — what I deliberately did NOT try to answer. **Boundary-setting is a partnership skill, and that's what I want to demonstrate.**
>
> The middle section explains why FRED and Yahoo, not RBA and ASX. **Practical reasons** — lower friction for a 5-day build, earlier daily data, universal recognition. **And one principled reason** — the architecture is source-agnostic, so adding ASX in production is a day's work, not a redesign. I want to be honest that in a real Macquarie deployment, ASX would be added on day one.
>
> The bottom section is the *why* of the whole architecture. The dashboard is a prototype; the architecture is built to support four classes of post-trade decisions — performance benchmarking, risk sizing, post-trade analysis, and operational signalling. **That's where this work earns its place in the business.** The dashboard is the demonstration; the architecture is the platform."

---

## Slide 3 — Pipeline walkthrough

**Visual:** Medallion architecture diagram (left to right):
```
   FRED API ────┐
                ├─► RAW (bronze) ──► ALIGNED ──► CURATED (silver) ──► SERVING (gold) ──► DASHBOARD
   Yahoo Finance ┘                       │
                                          └──► QUARANTINE LOG (audit trail)
```

Underneath the diagram, the layer table:

| Layer | What happens | Failure handling |
|---|---|---|
| **Raw (bronze)** | Daily ingest from each source, stored as Parquet | API errors fail fast; downstream stages skipped |
| **Aligned** | Outer-join on date so no row is silently dropped | Misaligned dates flagged, not discarded |
| **Curated (silver)** | DQ pass-fail split into curated table + quarantine log | Failures preserved with a typed reason code |
| **Serving (gold)** | Metric computation + RAG classification | NaN values rendered as gaps in the dashboard, never zeroed |

**Why this stack (callout below the table):**

| Component | Choice | Why v1 | Production swap-in |
|---|---|---|---|
| Language | Python | Mature data ecosystem; easy team onboarding | Same |
| Storage | Parquet + DuckDB | Zero infrastructure; analytical SQL out of the box | Iceberg / Delta on object storage |
| Dashboard | Streamlit | Fastest path from Python to deployed UI | Tableau / Power BI / custom React |
| Orchestration | GitHub Actions | Free CI; runs the daily pipeline on cron | Airflow / Dagster |
| Quality | In-code DQ heuristics | Tight integration with pipeline | Great Expectations / Soda |

**Below the stack table:** *"None of these is the production answer. All of them are the right v1 answer. **The architecture is layered so each component is independently replaceable** — the data contracts between layers don't change when the technology underneath does."*

**What I say (≈3 minutes):**

> "Here is the pipeline at a glance. Two sources on the left — VIX from FRED for the macro indicator, S&P 500 from Yahoo Finance for the market index. They flow through four layers — raw, aligned, curated, and serving — before reaching the dashboard.
>
> The two things worth pausing on are error handling and the stack choice.
>
> **Error handling.** Every layer has an explicit failure mode. When a source is missing — Good Friday, for example, when FRED publishes a placeholder and Yahoo doesn't open — the system doesn't crash and it doesn't silently drop the day. It quarantines the date with a typed reason code and continues. The dashboard shows you exactly which days were quarantined and why. **The system fails loudly, not quietly.**
>
> **Stack choice.** Python, DuckDB, Streamlit, GitHub Actions. The bottom table is the most important thing on this slide. **None of these is the production answer.** All of them are the right *prototype* answer — they're zero-infrastructure, they run locally, they're well-documented. The architecture is layered so when this moves to production, each component is replaceable. Streamlit becomes a managed BI tool. DuckDB becomes Snowflake or BigQuery. GitHub Actions becomes Airflow or Dagster. **The data contracts between layers don't change.** That's the architectural discipline that lets a v1 prototype mature into a production platform without a rewrite.
>
> Six ADRs in the repository document every one of these decisions — what we chose, what we rejected, and why. A junior engineer joining the team can read the ADRs and understand the design without needing me in the room."

---

## Slide 4 — Data decisions

**Visual:** Three rows, three columns: *The choice I faced* | *What I picked, and why* | *Who I'd partner with on this*.

| The choice | What I picked, and why | Who I'd partner with |
|---|---|---|
| **What to transform vs. what to exclude** | Compute SMA(10) and SMA(20) on close; quarantine rows where either source is missing; gap NaN values in the visual rather than imputing | Analyst team — they decide what's worth computing vs. what's noise |
| **How to handle missing data when sources disagree** | Outer-join with explicit quarantine logging. The default would be inner-join, which silently drops data. I chose to preserve every record with provenance. | Data product owner, risk function — *"when this happens in production, what action does each side trigger?"* |
| **How to set the RAG thresholds** | Fixed at VIX 20 / 30 based on industry convention. Documented as a v1 default. | Risk function, business stakeholders — *"what does an Amber signal mean operationally? What about Red?"* This is your calibration, not mine. |

**Below the table:** *"Assumptions I made (and would revisit with you): daily close is sufficient frequency; UTC alignment is acceptable for a US-market view; one macro indicator (VIX) is enough to demonstrate the pattern."*

**What I say (≈2 minutes):**

> "These are the three biggest data decisions I made. For each one I want to be transparent about two things — what I picked, and *who I'd want to partner with on that decision in a real engagement.*
>
> Take row two — the alignment policy. Two sources, sometimes one publishes and the other doesn't. The simple choice is to keep only the rows where both have data. The more thoughtful choice is to keep all the rows and explain the missing ones. I picked the second because I'd rather have a conversation about quarantined days than have the business discover quietly that the data was incomplete.
>
> Take row three — the RAG thresholds. I picked twenty and thirty because those are industry-conventional levels for VIX, and they're defensible. But the *right* numbers for Macquarie depend on your risk appetite and how your team would act on each signal. **That's a calibration discussion, not an engineering decision.** I'd want to have that discussion with you on day one of a real engagement."

---

## Slide 5 — Dashboard demo

**Visual:** Full-width screenshot of the live dashboard with five annotation callouts:
1. **KPI strip at top** — *"What a stakeholder sees in 5 seconds"*
2. **Price + trend lines** — *"Where the market is, where it's been trending"*
3. **VIX with RAG thresholds** — *"The risk regime, with the rules shown explicitly"*
4. **RAG signal band** — *"90 days at a glance"*
5. **DQ transparency** — *"How honest the data is — click to inspect"*

**Sub-callout — the story in the data:**
- *Late February:* Calm market, Green signal
- *March 6:* Amber begins (US jobs report, geopolitical stress)
- *March 27–30:* Red. Two consecutive days, VIX above 30, S&P 500 at the 90-day low (6344)
- *April–May:* Steady recovery. Green by mid-May, record close at 7501 on May 14

**What I say (≈3 minutes):**

> "This is the live dashboard. Five things, top to bottom. The KPI strip tells the stakeholder in five seconds whether we're in a calm, elevated, or stressed market. The two charts show the underlying data — the close price with two moving averages on top, and VIX with horizontal threshold lines explicitly drawn. The traffic-light band at the bottom is the story — at a glance you see the regime changes over the window.
>
> And what a window. The data captured a real market event. From late February the volatility was rising; March 6 took us into Amber; March 27 and 30 were Red — VIX above 30, S&P 500 at the 90-day low. Then a sharp reversal on March 31, and a steady recovery into a record closing high on May 14.
>
> **The point is what you didn't have to do to read that story.** No numbers. No explanation. Just look at the colours. That's what a non-technical dashboard should do — surface the story without requiring the audience to parse it. The numbers are there for audit; the colour is there for action."

---

## Slide 6 — AI agent reflection

**Visual:** Three rows, three columns: *What I asked AI* | *What it produced* | *How I identified the problem*.

| What I asked | What it produced | How I identified the problem |
|---|---|---|
| Write the alignment policy | Inner-join (the relational default) — would have silently dropped real Yahoo data on days when FRED hadn't yet published | Reviewing the live data on May 22 showed Yahoo had a close price but FRED had no row. The inner-join would have lost it. **I overrode the AI's default and chose outer-join with quarantine.** |
| Write a test for the yfinance rate-limit error | Used standard Python exception convention: `raise YFRateLimitError("message")` | When I ran the test, pytest failed with a `TypeError`. The yfinance library required a different argument structure (a `RemoteDataError` instance, not a message string). **The tests caught what code review missed.** I fixed the test to match the library's actual contract. |
| Predict what live FRED data would look like for holidays | Hypothesised that holidays would produce no row at all | When I ran live ingestion, FRED published a row with `"."` as the value on Good Friday. **The hypothesis was wrong — but having tests against fixtures meant the surprise was caught at the ingestion layer, not silently in production.** |

**Below the table:** *"Sixteen entries like these in the AGENT_LOG in the repo. The point isn't that AI is unreliable — it's that I treat AI as a junior engineer whose output I supervise. The tests, the ADRs, and the AGENT_LOG are the supervision artefacts."*

**What I say (≈2 minutes):**

> "The brief asks me to be specific about where the AI got things wrong. Let me take the middle row, which is the cleanest example. I asked Claude to write a unit test for the yfinance rate-limit error. It produced code that followed standard Python convention — pass a message string to the exception. The code looked correct on review. When I ran the test, it failed with a TypeError. The yfinance library is unusual — it requires you to pass a specific exception instance, not a string. **The AI couldn't have known this from training; the tests caught what review couldn't.**
>
> That's the pattern I'd apply across an AI-augmented team. **AI is a junior engineer. Its output is provisional. Tests, code review, and decision logging are how you supervise it.** The repo has the AGENT_LOG file with sixteen entries like the ones on this slide — each documenting a decision where I overrode, corrected, or learned."

---

## Slide 7 — Team and standards

**Visual:** Two side-by-side columns. Left: *Standards I'd put in place*. Right: *How I'd mentor — principles, not playbook*. Footer band below both columns.

**Left — Standards I'd put in place:**
- **Architecture Decision Records (ADRs)** for every significant choice. Status, context, decision, consequences. Reviewable as a PR.
- **Metric contract (METRICS.md)** for every metric, written *before* code. Definition, formula, edge cases, owner.
- **AGENT_LOG** for every AI override or correction. Same artefact pattern as ADRs; AI is treated the same as a junior engineer.
- **Test coverage threshold** — 90% minimum in CI; no merging below. This build sits at 98%.
- **Data quality contract** — no silent drops. Every excluded record has a reason code and lives in the audit log.

**Right — How I'd mentor — principles, not playbook:**

> *"I don't bring a fixed plan because the plan depends on the engineer. What I bring are principles that apply regardless of seniority."*

- **Decisions made visible by default.** New engineers learn what good engineering thinking looks like by reading the ADRs and the AGENT_LOG *before* being asked to write their own. This codebase is the onboarding material — six ADRs, sixteen log entries, a metric contract, an architecture diagram. **Two days of reading, demo back to me on day three.**
- **Pair before solo.** Whatever the first artefact is — reading a layer, writing a test, writing their first ADR — we do it together first. Velocity calibrates to ability; the goal is right thinking, not fast output.
- **Teach via the artefacts.** ADRs, PR reviews, and AGENT_LOG entries are the teaching surface. Engineering judgement is captured in writing, not just in code. A junior engineer who can write a good ADR can communicate to a stakeholder.
- **Standards modelled, not enforced.** The test coverage threshold, the no-silent-drops policy, the AI override pattern — these are how I work, not just what I demand. **The most consistent way to set a standard is to live it.**
- **The team scales by mentoring multiplying.** A senior engineer reading this codebase can be mentoring the next hire within a month. A junior takes longer, but the same principles apply. **The goal isn't an engineer who follows the standards — it's an engineer who teaches the next person.**

**Footer band (across both columns):** *"The artefacts on the left aren't just engineering documents — they are the format I'd teach a team of analysts to present in. An ADR teaches structured decision communication: context, decision, consequences. If your analysts can write in that pattern, they can present findings to business without getting questioned in the moment."*

**What I say (≈3 minutes):**

> "This is the slide I'd want you to remember. The role is 'Engineering Lead,' and leading is not the same as building. Building is what we just walked through. Leading is what I'm describing now.
>
> On the left are the standards I'd set up — ADRs for decisions, a metric contract before code, the AGENT_LOG for AI overrides, a coverage threshold in CI, and a data quality contract that prohibits silent drops. Five concrete artefacts. Each one is reviewable as a PR. Each one teaches what good looks like by being read, not just written.
>
> On the right is how I'd actually mentor. **I don't bring a fixed plan because the right plan depends on the engineer.** A senior joiner moves fast; a junior needs more pairing. What I bring are *principles* that apply regardless of seniority. Decisions are made visible by default — new joiners read the ADRs before writing their own. We pair before they go solo. We teach through the artefacts, not through lectures. And critically — **standards are modelled, not enforced.** The most consistent way to set a standard is to live it. If I'm cutting corners on tests, the team will too. If my ADRs are sloppy, theirs will be.
>
> The footer at the bottom is the line I want to land. **These artefacts aren't just for engineers.** An ADR is a template for structured decision communication — context, decision, consequences. If your analysts can write in that pattern, they can present findings to business without being questioned in the moment. That's how engineering rigour translates into business credibility."

---

## Slide 8 — If you had more time

**Visual:** Two columns. Left: *Production migration (the engineering)*. Right: *Business conversations (the partnerships)*.

**Left — Production migration:**
- **Lakehouse migration** — Iceberg or Delta on S3 / Azure Data Lake; move beyond Parquet-in-repo
- **Orchestration** — Airflow or Dagster in place of GitHub Actions
- **Data quality framework** — Great Expectations or Soda for declarative DQ
- **Lookback buffer for moving averages** — fetch 110 days, display 90, eliminate the start-of-window NaN
- **Percentile-based RAG thresholds** — replace fixed 20/30 with regime-aware bands
- **ASX 200 + RBA series ingestion** — Australian-market-first version

**Right — Business conversations:**
- *What does this dashboard need to do that it currently doesn't?* — talk to the actual end-users
- *How does it connect to existing dashboards?* — single source of truth, or a supplementary view?
- *Who's accountable for the signal?* — when it goes Red, who acts?
- *What's the cross-asset roadmap?* — equities first, then FX, then bonds?
- *Macquarie-specific calibration* — RAG thresholds tuned to the team's actual risk profile and historical data

**Underneath both columns:** *"The technical migration is half the work. The other half — the conversations — is what makes the migration actually deliver value."*

**What I say (≈2 minutes):**

> "If I were continuing past the case study, the work splits in two. The left column is the engineering migration — lakehouse, orchestrator, proper DQ tooling, and an ASX-first ingestion path. These are well-understood patterns and the ADRs in the repo describe them.
>
> The right column is what I want you to notice. **A production dashboard isn't a technical artefact, it's a decision-support tool.** It only delivers value when the people using it are clear on what action it triggers. That clarity comes from conversations with stakeholders, not from code.
>
> I'd run both tracks in parallel from day one of a real engagement. The engineering track gets us to production. The conversation track makes the production system useful."

---

## Slide 9 — Bonus: Partnering with the data product owner

**Visual:** Two columns. Left: *What I'd want from the data product owner*. Right: *What I'd bring to the partnership*. Below: *A simple "concept-to-delivery" arrow showing four phases: Shape → Design → Build → Measure*.

**Left — What I'd want from the data product owner:**
- A clear picture of who consumes this dashboard and what action they take
- The business definition of "elevated" and "stressed" — not the technical thresholds
- Access to the risk function and end-users for calibration discussions
- Visibility into adjacent dashboards so we don't duplicate or contradict
- Permission to set up time with end-users directly, not just through the product owner

**Right — What I'd bring to the partnership:**
- A technical roadmap that respects business priorities, not engineering preferences
- Honest trade-off analysis — *"we could do X, but it costs Y; here's what I recommend and why"*
- Transparency on data quality — every surface where the data is uncertain is visible to the business
- Incremental delivery — a working dashboard in weeks, not months
- A team I'm coaching to do the same — not just my own output

**Bottom arrow:** *Shape → Design → Build → Measure*. Below each phase, one line:
- **Shape:** Workshop with PO and end-users; agree on scope and success criteria. ADR-level documentation begins here.
- **Design:** Architecture review with engineering; lock the medallion contract and the metric contract. PO signs off the metric contract.
- **Build:** Incremental delivery with PO as first reviewer. AGENT_LOG and PR reviews surface AI work.
- **Measure:** Did this change the decisions stakeholders make? If not, the dashboard isn't done — redesign.

**Underneath:** *"The role title is 'Engineering Lead.' The 'lead' part isn't the engineering — it's the partnership."*

**What I say (≈2.5 minutes):**

> "The brief makes this slide optional. I made it required, because the role isn't about being the best engineer — it's about leading engineering in a way that delivers for the business.
>
> The two columns capture what I'd want from a data product owner partnership and what I'd bring back. Notice that almost none of it is about technology. It's about how we'd work together — what conversations we'd have, what decisions I'd surface, what trade-offs I'd ask you to make.
>
> The arrow at the bottom is the concept-to-delivery shape. Four phases — Shape, Design, Build, Measure. The thing I want to emphasise about this shape is **the Measure phase**. A new data product isn't delivered when it ships. It's delivered when stakeholders are making different decisions because of it. If the answer is no, the product owner and I redesign. That's how data products earn their place in the business — through measured impact, not feature count.
>
> The bottom line is the sentence at the bottom of this slide. The engineering is how I earn credibility. The partnership is how I lead."

---

## Closing / Q&A

**What I say (≈30 seconds before opening to questions):**

> "I'll stop there. The dashboard URL is on the title slide; the repository has every artefact I mentioned today — the ADRs, the AGENT_LOG, the architecture diagrams, the test suite, the metric contract. Everything is open and self-contained. **I'd rather use the rest of our time for questions. What would you like to dig into?"

---

# Appendix — Speaker notes

Not part of the deck. Personal notes for Dipanjan.

## Pacing

- 20-minute target.
- Slides 3 (Pipeline walkthrough) and 7 (Team and standards) are the two anchor slides — give them ~3 minutes each.
- Slides 2 (Framing) and 5 (Dashboard demo) are also major — ~2.5-3 minutes each.
- Other slides are ~2 minutes each.
- Closing leaves ~3 minutes for Q&A on a clean run.

## Voice

- First-person, confident, direct. *"I chose,"* *"I'd want to,"* *"I'd partner with."*
- Avoid hedging — *"I think maybe,"* *"it might be,"* *"perhaps."*
- Don't use the words *"obviously"* or *"simply"* — they tell the listener you've stopped explaining.
- Don't say *"AI"* without qualifying it once. Say *"Claude"* the first time, *"the AI assistant"* thereafter.
- The narration above is for tone — paraphrase in your own voice on the day. Don't read it.

## What the panel is listening for (business-focused panel)

- **Can this person work with us, not just for us?** → Slides 2, 4, 8, 9
- **Will they bring engineering rigour without making us feel the engineering is in charge?** → Slides 3, 7, 8, 9
- **Have they done the work, or are they bluffing?** → Slide 3 (pipeline detail + stack) + Slide 6 (AI honesty) + the repo
- **Are they a leader or an individual contributor?** → Tone throughout, especially Slide 7 and Slide 9

## Trapdoors to avoid

- **Don't go deep on technical architecture unless asked.** The repo is the evidence; the deck is the pitch.
- **Don't apologise for v1 limitations** (NaN gaps, fixed thresholds, US-market choice) — frame them as deliberate v1 boundaries with a clear v2 path.
- **Don't praise AI unprompted.** If asked, be specific and honest. If not asked, don't bring it up beyond Slide 6.
- **Don't volunteer the CI failure.** It's a documented deferred issue. If asked specifically, be honest: *"the CI test job has one failing dependency I haven't prioritised because it doesn't block local development. Five-minute fix I deferred to focus on the deliverable."*
- **Don't demo `make run` from a terminal.** The dashboard is the demo; the repo is the evidence. Terminal during a non-technical panel demo is the wrong centre of gravity.

## Likely questions, and short crisp answers

**Q: Why FRED and Yahoo instead of RBA and ASX?**
A: Three reasons. Lower API friction for a 5-day build. Earlier daily publication so I had fresh data every working day. Universal recognition — no need to explain VIX in a 20-minute session. **In a Macquarie production deployment, ASX would be the priority — the architecture is source-agnostic, so adding it is implementing the existing base contract.**

**Q: Why this stack — Python, DuckDB, Streamlit?**
A: Right v1 answer, not the production answer. Zero infrastructure, runs locally, well-documented. Each component is independently replaceable in production: Streamlit → Tableau or Power BI; DuckDB → Snowflake or BigQuery; GitHub Actions → Airflow or Dagster. **The data contracts between layers don't change when the technology underneath does.**

**Q: What business decisions does this architecture support?**
A: Four. Performance benchmarking (was a quiet month genuinely quiet, or did the market move?). Risk position sizing calibrated to regime. Post-trade analysis (slow fill from market or operational lag?). Pre-emptive operational signalling (volatility regimes correlate with settlement risk).

**Q: Why did you commit data to the repo?**
A: So a reviewer can experience the dashboard without running the pipeline. The committed silver and gold layers represent the demo state. The raw bronze layer is regeneratable. ADR-0001 documents the trade-off.

**Q: Why outer-join over inner-join?**
A: Inner-join silently loses data. We saw it live on May 22 — Yahoo had a close price, FRED hadn't yet published the VIX. An inner-join would have dropped that row. Outer-join preserves it; DQ decides what to do with it. ADR-0006.

**Q: Why two SMAs, not one?**
A: Different timescales tell different stories. Fast (10-day) catches regime changes early; slow (20-day) shows underlying trend. When they cross, momentum has shifted — a story a non-technical user can read off the chart.

**Q: How would you mentor a junior engineer joining your team?**
A: I don't bring a fixed plan because it depends on the engineer. What I bring are principles. Decisions are made visible — they read the ADRs and AGENT_LOG before writing their own. We pair before they go solo. We teach through the artefacts, not lectures. And critically, **standards are modelled, not enforced.** If my tests are sloppy, theirs will be too.

**Q: How would you scale this?**
A: The pure functions (alignment, DQ, metrics) are scale-agnostic — they'd migrate to a lakehouse without code change. Orchestration shifts from GitHub Actions to Airflow or Dagster. Tests extend, not rewrite.

**Q: How did AI help and hurt?**
A: It accelerated the boilerplate (test scaffolding, ADR templates, dashboard rendering). It hurt in two specific places documented in the AGENT_LOG. Net positive — but only because supervision was active.

**Q: What would you change about your approach?**
A: Three things. I would have started the slide deck on day one rather than waiting until the build was done. I would have set up CI properly before iterating, not as polish. And I would have committed the data to the repo earlier, so the reviewer experience was always one click.

---

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-24 | Dipanjan Mukherjee | Initial business-first deck structure |
| 2.0 | 2026-05-25 | Dipanjan Mukherjee | Restructured against case study brief: added Pipeline walkthrough (Slide 3), added Team and standards (Slide 7), renamed sections to match brief language exactly |
| 2.1 | 2026-05-25 | Dipanjan Mukherjee | Added source rationale + business decisions to Slide 2 (Framing); added "Why this stack" to Slide 3 (Pipeline walkthrough); restructured Slide 7 mentoring content from rigid week-by-week plan to principles-and-strategy that scales by engineer |
