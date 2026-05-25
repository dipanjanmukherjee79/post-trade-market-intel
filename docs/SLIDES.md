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

**Visual:** Three columns. Title above: *"What I chose to focus on, and why."*

**Column 1 — What the brief asks:**
- Build a market intelligence dashboard
- 90 days of post-trade activity
- One macro series, one market index
- RAG signal with defined threshold
- Document AI usage and data quality

**Column 2 — How I interpreted it:**
- *Can you scope a data product from an open brief?*
- *Can you make defensible decisions under ambiguity?*
- *Can you build something a non-technical user can act on?*
- *Will you partner with the business, or just deliver code?*

**Column 3 — What I deliberately did NOT try to answer:**
- Predictive modelling (this is a snapshot, not a forecast)
- Intraday tick data (out of scope for a 90-day view)
- Macquarie-specific risk calibration (that's a conversation, not an assumption)
- Cross-asset coverage (S&P 500 + VIX is enough to demonstrate the pattern)

**What I say (≈2 minutes):**

> "The brief is a single page, and it's deliberately open-ended. My first decision wasn't about technology — it was about scope. The middle column captures the four questions I think the brief is really asking. The third column is, I think, the more important one. It lists the things I deliberately did not try to answer alone. Each of those is a conversation I'd want to have with you — your data product owner, your risk function, your business stakeholders. **Boundary-setting is a partnership skill, and I want to show you mine.** I'd rather come into a real engagement and ask the right questions than make assumptions and discover later they were wrong."

---

## Slide 3 — Pipeline walkthrough

**Visual:** A medallion architecture diagram (left to right):
```
   FRED API ────┐
                ├─► RAW (bronze) ──► ALIGNED ──► CURATED (silver) ──► SERVING (gold) ──► DASHBOARD
   Yahoo Finance ┘                       │
                                          └──► QUARANTINE LOG (audit trail)
```

Underneath the diagram, four columns labelled by layer, each one sentence:

| Layer | What happens | Failure handling |
|---|---|---|
| **Raw (bronze)** | Daily ingest from each source, stored as Parquet | API errors fail fast; downstream stages skipped |
| **Aligned** | Outer-join on date so no row is silently dropped | Misaligned dates flagged, not discarded |
| **Curated (silver)** | DQ pass-fail split into curated table + quarantine log | Failures preserved with a typed reason code |
| **Serving (gold)** | Metric computation + RAG classification | NaN values rendered as gaps in the dashboard, never zeroed |

**Below the table:** *"Two sources (macro: FRED VIX, market index: Yahoo Finance S&P 500), four layers, full audit trail. The architecture is documented in six ADRs in the repo."*

**What I say (≈3 minutes):**

> "Here is the pipeline at a glance. Two sources on the left — VIX from FRED, which is the macro indicator, and S&P 500 from Yahoo Finance, which is the market index. Per the brief, one macro and one market series. They flow through four layers — raw, aligned, curated, and serving — before reaching the dashboard.
>
> The two things worth pausing on are error handling and handoff.
>
> **Error handling.** Every layer has an explicit failure mode. When a source is missing — like Good Friday, when FRED publishes a placeholder and Yahoo doesn't open at all — the system doesn't crash and it doesn't silently drop the day. It quarantines the date with a typed reason code and continues. The dashboard shows you exactly which days were quarantined and why. **The system fails loudly, not quietly.**
>
> **Handoff.** Every layer is independently testable. There are 115 unit tests across the codebase with 98% coverage. The architectural decisions are documented in six ADRs in the repository — what we chose, what we rejected, and why. A junior engineer joining the team can read the ADRs and understand the design without needing me in the room. That's what good handoff looks like."

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

**Visual:** Two side-by-side columns. Left: *Standards I'd put in place*. Right: *How I'd hand this off to a junior engineer*.

**Left — Standards I'd put in place:**
- **Architecture Decision Records (ADRs)** for every significant choice. Status, context, decision, consequences. Reviewable as a PR.
- **Metric contract (METRICS.md)** for every metric, written *before* code. Definition, formula, edge cases, owner.
- **AGENT_LOG** for every AI override or correction. Same artefact pattern as ADRs; AI is treated the same as a junior engineer.
- **Test coverage threshold** — 90% minimum in CI; no merging below. This build sits at 98%.
- **Data quality contract** — no silent drops. Every excluded record has a reason code and lives in the audit log.

**Right — How I'd hand this off:**
- Day 1: walk the new engineer through the medallion architecture and the ADRs. ~1 hour.
- Day 2-3: pair on the first new ADR they write. They lead; I review.
- Week 1: they pick up one ticket against this codebase. PR template requires a test, a passing build, and an ADR if architecture changes.
- Week 2+: they own a layer (typically ingestion first — clear contract, low risk). I review PRs, no longer pair.
- Always: the AGENT_LOG pattern extends to their AI use. If they override Claude, they log the override.

**Across the bottom, in a footer band:** *"The artefacts on the left are how I'd coach a team of analysts to present a story — the dashboard, the ADRs, and the AGENT_LOG are not just engineering documents, they are the format I'd teach the team to write in."*

**What I say (≈3 minutes):**

> "This is the slide I'd want you to remember. The role is 'Engineering Lead,' and leading is not the same as building. Building is what we just walked through. Leading is what I'm describing now.
>
> On the left are the standards I'd set up. Every architectural decision is captured in an ADR — short, reviewable, version-controlled. Every metric is defined in a contract before code is written. Every AI override is recorded in the AGENT_LOG. The pattern is consistent across humans and AI — both produce work that gets reviewed, both get a clean record of decisions made.
>
> On the right is how I'd actually hand this off. Not 'here's the codebase, good luck.' Day 1 is a walkthrough. Days 2 and 3 we pair. Week 1 they take their first ticket with a PR template that requires a test, a passing build, and an ADR if the design changes. By week 2 they own a layer.
>
> And — this matters for a non-technical team — the same artefacts are how I'd coach an analyst team to *present* information. **An ADR is not just an engineering document; it's a template for how to communicate a decision to a stakeholder.** Context, decision, consequences. If your analysts can write that pattern, they can present findings to business in a way that doesn't get questioned in the moment. That's what I'd teach."

---

## Slide 8 — If you had more time

**Visual:** Two columns. Left: *Production migration (the engineering)*. Right: *Business conversations (the partnerships)*.

**Left — Production migration:**
- **Lakehouse migration** — Iceberg or Delta on S3 / Azure Data Lake; move beyond Parquet-in-repo
- **Orchestration** — Airflow or Dagster in place of GitHub Actions
- **Data quality framework** — Great Expectations or Soda for declarative DQ
- **Lookback buffer for moving averages** — fetch 110 days, display 90 days, eliminate the start-of-window NaN
- **Percentile-based RAG thresholds** — replace fixed 20/30 with regime-aware bands

**Right — Business conversations:**
- *What does this dashboard need to do that it currently doesn't?* — talk to the actual end-users
- *How does it connect to existing dashboards?* — single source of truth, or a supplementary view?
- *Who's accountable for the signal?* — when it goes Red, who acts?
- *What's the cross-asset roadmap?* — equities first, then FX, then bonds?
- *Macquarie-specific calibration* — RAG thresholds tuned to the team's actual risk profile and historical data

**Underneath both columns:** *"The technical migration is half the work. The other half — the conversations — is what makes the migration actually deliver value."*

**What I say (≈2 minutes):**

> "If I were continuing past the case study, the work splits in two. The left column is the engineering migration — lakehouse, orchestrator, proper DQ tooling. These are well-understood patterns and the ADRs in the repo describe them.
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
- Slides 5 (Dashboard demo) and 9 (Partnership) are also major — ~2.5-3 minutes each.
- Other slides are ~2 minutes each.
- Closing leaves ~5 minutes for Q&A on a clean run.

## Voice

- First-person, confident, direct. *"I chose,"* *"I'd want to,"* *"I'd partner with."*
- Avoid hedging — *"I think maybe,"* *"it might be,"* *"perhaps."*
- Don't use the words *"obviously"* or *"simply"* — they tell the listener you've stopped explaining.
- Don't say *"AI"* without qualifying it once. Say *"Claude"* the first time, *"the AI assistant"* thereafter.
- The narration above is for tone — paraphrase in your own voice on the day. Don't read it.

## What the panel is listening for (per business-focused panel)

- **Can this person work with us, not just for us?** → Slides 4, 8, 9
- **Will they bring engineering rigour without making us feel the engineering is in charge?** → Slides 7, 8, 9
- **Have they done the work, or are they bluffing?** → Slide 3 (pipeline detail) + Slide 6 (AI honesty) + the repo
- **Are they a leader or an individual contributor?** → Tone throughout, especially Slide 7 and Slide 9

## Trapdoors to avoid

- **Don't go deep on technical architecture unless asked.** The repo is the evidence; the deck is the pitch.
- **Don't apologise for v1 limitations** (NaN gaps, fixed thresholds, etc) — frame them as deliberate v1 boundaries with a clear v2 path.
- **Don't praise AI unprompted.** If asked, be specific and honest. If not asked, don't bring it up beyond Slide 6.
- **Don't volunteer the CI failure.** It's a documented deferred issue. If asked specifically, be honest: *"the CI test job has one failing dependency I haven't prioritised because it doesn't block local development. Five-minute fix I deferred to focus on the deliverable."*
- **Don't demo `make run` from a terminal.** The dashboard is the demo; the repo is the evidence. Terminal during a non-technical panel demo is the wrong centre of gravity.

## Likely questions, and short crisp answers

**Q: Why did you commit data to the repo?**
A: So a reviewer can experience the dashboard without running the pipeline. The committed silver and gold layers represent the demo state. The raw bronze layer is regeneratable. ADR-0001 documents the trade-off.

**Q: Why outer-join over inner-join?**
A: Inner-join silently loses data. We saw it live on May 22 — Yahoo had a close price, FRED hadn't yet published the VIX. An inner-join would have dropped that row. Outer-join preserves it; DQ decides what to do with it. ADR-0006.

**Q: Why two SMAs, not one?**
A: Different timescales tell different stories. Fast (10-day) catches regime changes early; slow (20-day) shows underlying trend. When they cross, momentum has shifted — a story a non-technical user can read off the chart.

**Q: How would you scale this?**
A: The pure functions (alignment, DQ, metrics) are scale-agnostic — they'd migrate to a lakehouse without code change. Orchestration would shift from GitHub Actions to Airflow or Dagster. Tests extend, not rewrite.

**Q: How did AI help and hurt?**
A: It accelerated the boilerplate (test scaffolding, ADR templates, dashboard rendering). It hurt in two specific places documented in the AGENT_LOG. Net positive — but only because supervision was active.

**Q: What would you change about your approach?**
A: Three things. I would have started the slide deck on day one rather than waiting until the build was done. I would have set up CI properly before iterating, not as polish. And I would have committed the data to the repo earlier, so the reviewer experience was always one click.

**Q: What if the panel cares more about the technical detail than I think?**
A: ADR-0006 (alignment), ADR-0003 (RAG threshold rationale), and the architecture diagram in `docs/architecture-current-state.mmd` are the three places to point them at. The AGENT_LOG entry on the all-NaN-Close design decision is a good demonstration of design judgment.

---

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-24 | Dipanjan Mukherjee | Initial business-first deck structure |
| 2.0 | 2026-05-25 | Dipanjan Mukherjee | Restructured against case study brief: added Pipeline walkthrough (Slide 3), added Team and standards (Slide 7), renamed sections to match brief language exactly |
