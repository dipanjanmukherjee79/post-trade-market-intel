# ADR-0003: RAG signal threshold logic

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-05-20 |
| Author | Dipanjan Ghosh |
| Supersedes | — |
| Related | METRICS.md (metric definitions and signal contract) |

## Context

The dashboard is required to display a single Red/Amber/Green signal answering *"is there anything we should be watching?"* for a financially literate but non-technical audience. The case study explicitly asks for a justified threshold.

A RAG signal is a high-leverage piece of the dashboard: it sits above the charts, it is what a busy user reads first, and it is what they will quote in a meeting. The threshold logic must therefore be:

- **Interpretable without context.** A user glancing at "Amber" should know what that means without consulting a methodology document.
- **Defensible without specialist domain knowledge.** The author of this dashboard is a data engineering lead, not a market microstructure specialist. The defence of the threshold must rest on widely understood conventions, not proprietary research.
- **Stable across time.** A user who sees Green today and Green next quarter should be able to interpret both readings consistently.
- **Easy to test and maintain.** A junior engineer must be able to add tests for the signal logic and verify behaviour at boundaries.

The signal logic is also the place where over-engineering is most tempting and least rewarded. A regime-switching model, change-point detection, or composite multi-input signal would be technically more accurate but would create a "defend the model" obligation that exceeds the scope of this case study and the depth of expertise the author can credibly claim.

## Decision

Implement a **fixed-threshold RAG signal** on the **most recent published VIX value (T-1)**:

| Input condition | Signal | Interpretation |
|---|---|---|
| VIX < 20 | **Green** | Low volatility regime — calm market |
| 20 ≤ VIX ≤ 30 | **Amber** | Elevated volatility — monitor |
| VIX > 30 | **Red** | Stressed market conditions |

The signal reads only the latest available VIX close. It does not look at S&P 500 price action, does not require sustained readings, and does not adjust for time-of-day or recent history.

If the latest VIX is missing or has been quarantined by the data quality stage, the signal displays as **"Unavailable"** with the date of the last good reading.

## Rationale

The 20 and 30 thresholds are the most widely recognised regime boundaries for VIX. They are used in market commentary, sell-side research, and risk desk dashboards across the industry as conventional reference points. Their historical alignment with observable market regimes is the basis of their defence:

- **VIX has spent the majority of post-2000 trading days below 20.** This is the empirical "normal" state of US equity markets. A reading below 20 is calm by any reasonable historical reference.
- **The 20–30 band has historically associated with periods of elevated uncertainty without crisis** — rate-hike cycles, geopolitical events, earnings shocks. It is the warning zone, not the panic zone.
- **VIX has exceeded 30 during every major market stress event of the last 25 years**, including the 2008 global financial crisis, the August 2011 European debt crisis, the COVID-2020 shock (peak ~82), and parts of the 2022 inflation-driven correction. Above 30 is genuine market stress.

**Why fixed thresholds were chosen over percentile-based thresholds:**

A percentile-based threshold (e.g. "Red when VIX is in the top third of the last 90 days") was considered and rejected. The problem with percentile thresholds is that they are relative to the window, not to market reality. If the most recent 90 days were uniformly calm, a percentile-based signal would still report some days as Amber and Red — even though the absolute VIX level was firmly in the Green regime by any historical standard. The signal would say "this is the most volatile recent period," not "this is volatile in absolute terms." For the dashboard's audience and question, the absolute reading is more useful.

**Why a single-input signal was chosen over a composite signal:**

A composite signal incorporating VIX, S&P 500 drawdown, and rolling volatility was considered. It would be more accurate at distinguishing genuine stress regimes from transient spikes, but every additional input creates an additional weighting decision that must be defended. For v1, the simpler signal is more defensible. A composite is the natural v2 enhancement and is mentioned in the roadmap.

## Consequences

### Positive

- The signal is interpretable on its own terms. A panel member asking "why Amber?" gets an answer ("VIX is 23, which is the conventional elevated-but-not-crisis band") rather than a model explanation.
- Tests for the signal logic are trivial — three input ranges, three outputs, plus the missing-data case. The full test surface is four assertions.
- The threshold can be reviewed and adjusted by the risk team without changing any code structure — only the constants change.
- The signal is interpretable historically. Anyone looking back at the dashboard during the COVID-2020 period would have seen Red and known why.

### Negative / Trade-offs

- **Static thresholds do not adapt to regime shifts in baseline volatility.** If markets enter a sustained low-volatility regime where 15 is the new normal, the signal will report Green even when something is genuinely off relative to the new baseline. Mitigation: the thresholds are constants in code, reviewable annually.
- **Single-day reads can flicker around boundaries.** A VIX reading of 19.8 followed by 20.2 will toggle Green to Amber. The signal makes no attempt to dampen this. Mitigation: documented in the v2 roadmap as a persistence-rule enhancement.
- **The signal ignores the direction of the underlying market.** A VIX of 22 with S&P 500 rallying is treated the same as VIX of 22 with S&P 500 falling. This is intentional — the signal is about expected volatility, not direction — but a panel member may probe it. The defence is in the design.

### Mitigations

- The dashboard displays both the VIX value and the corresponding signal, so users can see the reading that produced the colour and form their own judgement on boundary cases.
- The `notes` field on the dashboard adjacent to the signal will say something like *"Signal based on VIX close at \[date\]. Thresholds: <20 Green, 20–30 Amber, >30 Red."* This makes the logic visible without requiring the user to consult documentation.

## Alternatives considered

### Option A: Rolling 90-day percentile thresholds
Rejected. Interpretation is window-dependent — "Red" means different absolute values in different time periods. Loses the "interpretable without context" property that is the primary requirement for a RAG on a non-technical dashboard.

### Option B: N-day persistence rule (e.g. VIX > 30 for 3 consecutive days = Red)
Rejected for v1. Would reduce boundary flicker and produce a more conservative signal. Adds complexity that requires more justification than the simpler signal. Listed as the highest-priority v2 enhancement.

### Option C: Composite signal — VIX + S&P 500 drawdown + realised vol
Rejected for v1. Each additional input requires defending its weight in the composite. The defence escalates quickly into model-validation territory that exceeds the scope. Documented as a v2 candidate, ideally co-designed with the post-trade risk team.

### Option D: Statistical regime detection (HMM, change-point models)
Rejected. Black-box from a panel-defence perspective. Requires explanation of the model, its assumptions, and its training data. Inappropriate for a dashboard whose primary audience is non-technical.

### Option E: Sell-side or vendor signal (e.g. a published market stress index)
Rejected because the case study restricts sources to publicly available data and the chosen list. Worth noting as a v2 option if the platform is permitted to license third-party signals.

## Open questions / future revisions

These would be raised with the data product owner and the post-trade risk team in a real engagement:

- **Should the thresholds be Macquarie-specific rather than industry-conventional?** A bank's risk appetite may justify tighter or looser bands. This is a calibration conversation, not an engineering decision.
- **What action does each colour imply for the post-trade team?** A RAG signal that does not drive a decision is decoration. The thresholds should be tied to operational responses (e.g. "Red triggers enhanced collateral monitoring," or similar). This is a product-owner conversation.
- **Should there be a model risk treatment for this signal?** Even simple decision-support outputs may, depending on the internal model risk framework, require calibration evidence, periodic review, and challenger model comparison. The simpler the signal, the lower the bar, but the bar exists.

## Change log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-20 | Dipanjan Ghosh | Initial decision |
