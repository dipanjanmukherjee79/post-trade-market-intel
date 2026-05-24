# Post-Trade Market Intelligence
## Case Study Presentation — Data & Analytics Engineering Lead

**Author:** Dipanjan Mukherjee
**Format:** 8 slides + 1 partnership slide | 20 minutes target
**Live dashboard:** `https://post-trade-market-intel.streamlit.app` *(to be filled after deploy)*
**Source repository:** `https://github.com/dipanjanmukherjee79/post-trade-market-intel`

> **Tone note:** Business-first throughout. The technical depth lives in the
> repository (ADRs, AGENT_LOG, METRICS.md, 115 tests) as evidence for due
> diligence — not centred in the spoken narrative. The deck demonstrates
> *judgement, partnership, and the ability to navigate the business through
> a data journey* — which is what the role is hiring for.

---

## Slide 1 — Title

**Visual:** Clean title slide with the dashboard screenshot as a subtle background or right-side preview.

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

> "Thank you for the time. I'm going to spend twenty minutes walking you through how I approached this case study. The dashboard you'll see is operational — the URL is at the bottom of this slide, and you can click through to it on your own afterwards. But the dashboard isn't really what I want to talk about. What I want to talk about is the *decisions* I had to make to build it — because those decisions are where I'd partner with the business, and that partnership is what I'd bring to this role."

---

## Slide 2 — My interpretation of the brief

**Visual:** Three columns side-by-side. Title above: *"What I think you're really asking."*

**Column 1 — What the brief says:**
- Build a market intelligence dashboard
- 90 days of post-trade activity
- RAG signal to inform decisions
- Document AI usage and data quality

**Column 2 — What I think you're actually asking:**
- *Can you scope a data product from a one-page brief?*
- *Can you make defensible decisions when the brief is ambiguous?*
- *Can you build something that helps a non-technical user act?*
- *Will you partner with the business or just deliver code?*

**Column 3 — What I deliberately did NOT try to answer:**
- Predictive modelling (not a forecast tool)
- Real-time intraday tick data (out of scope; the brief said daily)
- Macquarie-specific risk calibration (that's a conversation, not an assumption)
- Cross-asset coverage (S&P + VIX is sufficient to demonstrate the pattern)

**What I say (≈2 minutes):**

> "The brief is one page, and it's deliberately open. The first decision I made was *not what to build, but what to ask.* I read the brief and identified what I thought were four real questions underneath the explicit ask. And just as importantly, I identified what I was *not* trying to answer — boundary-setting is a partnership skill, and I want to show you mine. The third column is the more important one: it lists the things I assumed are conversations I'd have *with you*, not assumptions I should make alone. That instinct is what I'd bring to a real engagement."

---

## Slide 3 — Three decisions, and the partners they invited

**Visual:** Three rows, each with three columns: *The choice I faced* | *What I picked, and why* | *Who I'd partner with on this*

| The choice | What I picked, and why | Who I'd partner with |
|---|---|---|
| **How to handle missing data when sources disagree** | Outer-join with explicit quarantine logging. Industry default is inner-join, which silently drops data. I chose the more sophisticated path because losing data quietly is worse than logging it loudly. | Data product owner, risk team — *"when this happens in production, what action does each side trigger?"* |
| **How to calibrate the RAG thresholds** | Fixed at 20/30 from industry convention. Documented as a v1 placeholder. | Risk function, business stakeholder — *"what does an Amber signal mean operationally to your team? What about Red?"* This is YOUR calibration, not mine. |
| **How much technical depth to expose in the dashboard** | Hidden by default, available on click. The "Data Quality" section expands to show quarantined dates. | End user, then product — *"do you want to see why a date is missing, or trust that the system handled it?"* Two valid answers, two different UX patterns. |

**What I say (≈3 minutes):**

> "I want to walk you through three of the decisions I made, but the point isn't the decisions themselves — the point is to show you how I think about *who I'd bring into each one.* Take the first row. Two sources, one had data, one didn't. The technical default would be to drop the row and move on. I chose a more sophisticated approach where every missing record is preserved with an explanation. **The reason isn't technical — it's that I'd rather have a conversation with the business about what to do with quarantined records than have them discover quietly later that the data was incomplete.** That's the partnering instinct. Same with the RAG thresholds — I picked numbers that are defensible from industry convention, but in your environment those numbers should be calibrated to *your* risk appetite, by *your* people. That's a conversation I'd want to have on day one."

---

## Slide 4 — The dashboard, end-to-end

**Visual:** Full-width screenshot of the live dashboard. Annotations point at:
1. **KPI strip at top** — *"What a stakeholder sees in 5 seconds"*
2. **Price + trend lines** — *"Where the market is, where it's been trending"*
3. **VIX with threshold lines** — *"The risk regime, with the rules of the road shown explicitly"*
4. **RAG band** — *"The story of the last 90 days at a glance"*
5. **DQ transparency** — *"How honest the data is. Click to inspect."*

**What I say (≈2 minutes):**

> "Here's the dashboard. Single page. Five things, top to bottom. The KPI strip is what a stakeholder sees in five seconds — am I in a calm market, an elevated one, or a stressed one. The middle two charts show the underlying data. The horizontal RAG band at the bottom is the *story* — at a glance, you see the regime changes across the window. And the data quality expander at the bottom is where I show, transparently, where the data has gaps and why. **A non-technical user can use this without help. A technical user can click in and audit the source data quality. The same surface serves both.** That dual-audience design was deliberate."

---

## Slide 5 — The data story it tells

**Visual:** Annotated chart screenshot showing the March 27–30 climax. Three callouts:
- **Late February:** Green, calm market
- **March 6:** Amber begins. Disappointing US jobs report; geopolitical escalation
- **March 27–30:** Red. Two consecutive days with VIX > 30; S&P 500 at the 90-day low of 6344
- **April–May:** Recovery. Returns to Green by mid-May; record closing high of 7501 on May 14

**Underneath:** *"The dashboard didn't just plot data. It captured a full stress regime."*

**What I say (≈2 minutes):**

> "What you see on screen captures a real market event. From the end of February through March, geopolitical stress drove volatility from the high teens into the high 20s. Two specific days — March 27 and 30 — crossed VIX 30 with sustained closing-day stress. The S&P 500 hit its 90-day low on March 30 at 6344. Then a sharp reversal on March 31, and from there a steady recovery into a record high in mid-May. **A stakeholder using this dashboard during those eleven days in March would have seen the signal flip Amber, then Red, then back to Amber — without having to read a single number.** That's the value of the visual. The numbers are there for audit, but the *story* is told in colour."

---

## Slide 6 — Where I'd want help

**Visual:** A section title "Open questions I'd bring to the data product owner" with each item as a row with two columns: *Open question* | *Who needs to weigh in*.

| Open question | Who needs to weigh in |
|---|---|
| What does Amber mean *operationally* to Macquarie? An email alert? A review meeting? Nothing until Red? | Data product owner, business stakeholder |
| Are these the right thresholds for Macquarie's risk appetite, or should they be calibrated against our own historical distribution of trading days? | Risk function, model risk team |
| Should quarantined trading days produce a notification, or stay in the audit log only? | Operations, data steward |
| For the production version: which other indicators should be on this dashboard? Cross-asset (FX, bonds)? Liquidity proxies? Trading-flow specific? | Trading desk, portfolio management |
| How frequently is "fresh enough" for this audience? Daily was sufficient for the brief, but is intraday or near-real-time what production needs? | End user, operations |

**Below the table:** *"I built v1 with defensible defaults. Production calibration is a partnership, not an engineering decision."*

**What I say (≈3 minutes):**

> "This is the slide where I deliberately show you the things I *didn't* try to answer alone. Look at row two — RAG thresholds. I set them at 20 and 30 based on industry convention, and the dashboard works. But the *right* numbers for Macquarie depend on Macquarie's specific risk appetite, your historical distribution of trading days, and how risk-averse the consuming function is. **That's not an engineering decision, it's a partnership.** Same with the alerting question — does Amber mean we send an email, or does it mean we wait until Red? I don't know, because I haven't talked to your stakeholders. **What I'm signalling here is that I understand the boundary between what I should decide alone and what I should bring to you.** And I'd want to start that conversation on day one of a real engagement."

---

## Slide 7 — How I used AI responsibly

**Visual:** Three concrete examples in three rows. Each row: *What I asked AI to do* | *Where I overrode it* | *What I learned*.

| What I asked AI | Where I overrode | What I learned |
|---|---|---|
| Generate the source alignment policy | AI proposed inner-join (the relational default). I changed it to outer-join with explicit quarantine. | The default isn't always right for the domain. Time-series alignment has different optimal semantics than relational joins. |
| Implement the data quality stage | AI's first draft treated "row with NaN value" the same as "no row from source." I split them into separate reason codes. | Subtle distinctions matter. The audit log is more useful when it preserves *why* something was missing, not just *that* it was. |
| Predict what live FRED data would look like | AI hypothesised that holidays would produce no row at all. Live data showed FRED publishes a row with "." for holidays. | Design proposals are hypotheses until they survive contact with real data. |

**Footer:** *"The AGENT_LOG in the repository has sixteen entries like these, each documenting a decision where I supervised, overrode, or learned. AI-augmented engineering means the engineer is still the engineer."*

**What I say (≈2 minutes):**

> "I want to address AI directly, because it's relevant to the role. I used Claude extensively throughout this build. I also overrode it repeatedly. The repository contains an AGENT_LOG file with sixteen specific examples where I caught the AI being wrong, made a different design choice, or learned something from running live data that the AI couldn't have known from training. **The point isn't that AI is unreliable — it's that I treat it as a junior partner whose output I verify, not a senior engineer whose output I accept.** That's how I'd use AI in a Macquarie environment too — accelerated delivery without abdicating judgement."

---

## Slide 8 — What I'd do next, with the team

**Visual:** Two-column layout. Left column: *Production migration*. Right column: *Business conversations*.

**Left — Production migration (conversations with engineering):**
- Lakehouse migration (Iceberg or Delta on S3/ADLS) — move beyond Parquet-in-repo
- Orchestration via Airflow or Dagster — replace GitHub Actions
- Proper data quality framework (Great Expectations or Soda) — replace the in-code DQ heuristics
- Lookback buffer for moving averages — fetch 110 days, display 90, eliminate the start-of-window NaN gap
- Percentile-based RAG thresholds — replace fixed 20/30 with regime-aware bands

**Right — Business conversations (conversations with the team):**
- *What does the user actually want this for?* — Trading reporting? Risk surveillance? Client-facing? Each answer changes the design.
- *How does this connect to existing dashboards?* — Single-source-of-truth or supplementary?
- *Who's accountable for the signal?* — When the dashboard says Red, who has to act?
- *Cross-asset expansion roadmap* — equities first, then FX, then bonds? Or simultaneously?
- *Macquarie-specific calibration* — RAG thresholds tuned to the team's actual risk profile

**Underneath:** *"The technical roadmap is half of it. The other half — the conversations — is what makes the technical roadmap actually deliver value."*

**What I say (≈2 minutes):**

> "If I were continuing this beyond a case study, the work splits into two tracks. The left column is the engineering migration — lakehouse, orchestrator, proper DQ tooling, the things you'd expect. I won't dwell on these; they're table stakes and they're in the ADRs in the repo. **The right column is what I want to emphasise: the conversations.** A production dashboard isn't a technical artefact, it's a *decision-support artefact* — and it only becomes valuable when the people who use it are clear on what action it triggers. That clarity comes from conversations, not from code. **I'd want to start those conversations early, and I'd want to do them in parallel with the technical migration, not after.**"

---

## Slide 9 (Partnership slide — promoted from optional to required)

**Title:** *Partnering with the data product owner*

**Visual:** A simple two-column layout. Left: *What I'd want from the product owner on day one*. Right: *What I'd bring to the partnership*.

**Left — What I'd want from the data product owner:**
- A clear picture of who consumes this dashboard and what they do with it
- The business definition of "elevated" and "stressed" — not the technical thresholds
- Access to risk/model-risk teams for calibration discussions
- Visibility into adjacent dashboards so we don't duplicate or contradict
- Permission to set up time with end-users — not just the product owner

**Right — What I'd bring back to the partnership:**
- A technical roadmap that respects business priorities (not engineering whim)
- Honest trade-off analysis — "we could do X, but that costs Y; here's what I'd recommend and why"
- Transparency on data quality — *every* surface where the data is uncertain is visible to the business
- A working dashboard within weeks, not months — incremental delivery
- A team I'm coaching to do the same — not just my own output

**At the bottom:** *"The role title is 'Data & Analytics Engineering Lead.' The 'lead' part isn't the engineering — it's the partnership."*

**What I say (≈2 minutes):**

> "This slide was optional in the brief. I made it required, because the role isn't about being the best engineer — it's about leading engineering in a way that delivers for the business. The left column is what I'd want from a data product owner partnership on day one. The right column is what I'd bring back. None of it is about technology — it's about how we'd work together. **One sentence at the bottom captures my read of this role: the 'lead' part isn't the engineering, it's the partnership. The engineering is how I prove I'm credible to do the leading.**"

---

## Closing / Q&A (≈2 minutes left)

**What I say:**

> "I'll stop there. The dashboard URL is in front of you and on the title slide. The source code, the architecture decisions, the data quality audit trail, and the AI usage log are all in the repository — you're welcome to look through any of them after this. I'd rather use the rest of the time for questions. **What would you like to dig into?**"

---

# Appendix — Notes for the speaker

These notes are NOT part of the deck. They are personal speaker notes for Dipanjan.

## Pacing

- 20-minute target. ~2 min/slide for 8 main slides plus ~3 min for Q&A intro.
- Slides 3 (decisions) and 6 (where I'd want help) are the strategic slides — give them slightly more time.
- Slides 4 (dashboard) and 5 (data story) are visual — let the screen do the work, don't read it out.

## Voice

- First-person, confident, direct. "I chose," "I'd want to," "I'd partner with."
- Avoid hedging ("I think maybe", "it might be that").
- Don't use the words "obviously" or "simply" — they signal the speaker has stopped explaining.
- Don't say "AI" without qualifying it. Say "Claude" or "the AI assistant I used." Specificity matters in a regulated-environment interview.

## What the panel is listening for (per the role brief intelligence)

- **Can this person work with us, not just for us?** → Slides 3, 6, 9
- **Will this person bring engineering rigor without making us feel like the engineering is in charge?** → Slide 8 right column, Slide 9
- **Has this person done the work, or are they bluffing?** → Slide 7 (AI honesty), and the repo
- **Is this person a leader or an individual contributor?** → Tone throughout, especially Slide 9

## Trapdoors to avoid

- Don't go deep on the technical architecture unless asked. The repo is the evidence; the deck is the pitch.
- Don't apologise for the v1 limitations (NaN gaps, fixed thresholds) — *frame them as deliberate boundaries.*
- Don't praise AI unprompted. If asked, be specific and honest. If not asked, don't bring it up beyond Slide 7.
- Don't volunteer the CI failure (deferred issue from AGENT_LOG). If asked about CI specifically, be honest — "I have a CI workflow set up; one test job is failing on a missing dependency that I haven't prioritised because it doesn't block local development. It's a five-minute fix I deferred to focus on the deliverable."

## Likely questions, and short crisp answers

**Q: Why did you commit data to the repo?**
A: So a reviewer can experience the dashboard without running the pipeline. The committed silver and gold layers represent the demo state; the raw bronze is regeneratable. ADR-0001 in the repo documents the trade-off.

**Q: How do you handle the case where neither source has data?**
A: That's the "both_missing" reason code. It's in the quarantine log with full provenance. The dashboard's DQ section surfaces it. Currently the only case in production is Good Friday — we'd quarantine it explicitly rather than try to fill it.

**Q: Why outer-join over inner-join?**
A: Inner-join silently loses data. Specifically it lost a real Yahoo S&P close because FRED hadn't published the VIX yet. We saw this in live data on May 22. Outer-join preserves the observation; DQ decides what to do with it. ADR-0006.

**Q: Why two SMAs?**
A: Different timescales tell different stories. Fast (10-day) catches regime changes the moment they begin. Slow (20-day) shows the underlying trend. When they cross, momentum has shifted — that's a story a non-technical user can read off the chart.

**Q: How would you scale this?**
A: The pure functions (alignment, DQ, metrics) are scale-agnostic — they're already vendor-neutral and would migrate to a lakehouse without code change. The orchestration shell would change from GitHub Actions to an enterprise orchestrator. Tests would extend, not rewrite.

**Q: How did AI help and hurt?**
A: It accelerated by ~3x on the boilerplate (test scaffolding, ADR templates, dashboard rendering). It hurt twice in specific ways — both documented in the AGENT_LOG. Net positive but only because I supervised it.

**Q: What would you change about your approach?**
A: Three things. I would have started the slide deck on day one rather than waiting until the build was done — the deck-led the build, not the other way around. I would have set up CI properly before iterating instead of treating it as polish. And I would have committed the data to the repo earlier so the dashboard's reviewer experience was always one click.

---

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-24 | Dipanjan Mukherjee | Initial business-first deck structure, 8 slides + 1 partnership slide |
