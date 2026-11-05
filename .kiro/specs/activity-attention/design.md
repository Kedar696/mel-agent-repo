# Design: Activity attention

## 1. Overview

A new pure module `mel/data/activity.py` reads a farmer's past conversations and labels each insight with a
**tier** (`surge` / `neutral` / `steady_high`) that says whether the farmer's activity is *changing* in a way
worth extra attention. The tier rides on `Decision.attention` (never on the hand-off or survey JSON, which the
organisers' schemas freeze), and three small, well-separated effects read it: priority (P3), question count
(P4), and send time (P2). A one-line toggle (`attention`, default off) keeps today's output byte-for-byte when
the feature is off.

Design follows two patterns already in the repo:
- **`send_time`:** new per-decision data that the schema cannot hold lives on the `Decision` object; `pipeline`
  computes it from the *unfiltered* insight set and passes it down (`chat_hours`), so `--farmer`/`--limit`
  never change a farmer's result.
- **history rules (H1–H4):** a feature that deliberately diverges from the brief, on in the app, off for
  scoring, with the trade-off shown in numbers.

```
insights (unfiltered) ─┐
farmers ──────────────┼─> ActivityHistory (counts per farmer, pre-cutoff, distinct conversations)
                       │
run_insight(insight, …, attention_result) ─> decide() ─> Decision
                                                 │           .attention = {tier, reason, …}
                                                 ├─ build_handoff(): priority adjusted by tier (P3)
                                                 ├─ write_surveys(): question cap by tier (P4)
                                                 └─ pick_send_time(): surge ⇒ window opening (P2)
```

## 2. The module: `mel/data/activity.py` (P1)

### 2.1 Settings — `config/activity_attention.json`
Outside the parity-checked folders, loaded with an `lru_cache` helper in the module (mirroring `config.rules()`).

```json
{
  "baseline_window": {"from_days": 70, "to_days": 14},
  "recent_days": 14,
  "min_dataset_age_days": 28,
  "quiet_baseline_max": 0.5,
  "jump_min_recent": 3,
  "jump_poisson_factor": 2.0,
  "jump_poisson_p": 0.001,
  "declining_ratio": 0.5,
  "steady_high_baseline": 1.5,
  "weights": {"surge": 1.5, "neutral": 1.0, "steady_high": 0.5},
  "high_promotion_window_days": 7
}
```
Thresholds are **starting values** (R-10.2) and are tuned with pipeline evidence; keeping them in config means
tuning does not touch code.

### 2.2 Data shape
```python
@dataclass(frozen=True)
class Attention:
    tier: str            # "surge" | "neutral" | "steady_high"
    reason: str          # insufficient_history | quiet_then_high_weight | activity_jump | declining | none
    baseline_per_week: float
    recent_count: int
    weight: float
    explanation: str
    def as_dict(self) -> dict: ...   # exactly the keys R-4 lists, for Decision.attention / JSON summary
```

### 2.3 History index (built once per run)
```python
class ActivityHistory:
    def __init__(self, insights, settings=None): ...
    #   groups non-junk insights by farmer_id; records (created_at, conversation_id) per row;
    #   dataset_start = min(created_at) over ALL given insights (used for insufficient_history).
    def attention_for(self, insight) -> Attention: ...
```
- **Junk filter:** skip any row where `mel.data.why_junk(row)` is non-empty, so broken/junk conversations never
  inflate counts (R-1.4, R-12).
- **Distinct conversations:** counts are over distinct `conversation_id`, computed by filtering rows strictly
  before the insight's `created_at`, dropping the insight's own `conversation_id`, then taking the set of
  conversation ids whose *earliest* row falls in the window. Extra insights / junk rows in one conversation
  therefore add nothing (R-12).
- **No leakage:** only rows with `created_at < insight.created_at` are considered (R-1.1).

### 2.4 Metrics (R-2)
Let `t0 = parse_ist(insight.created_at)`.
- **baseline_per_week:** distinct conversations with earliest row in `[t0-70d, t0-14d)`. The covered span is
  `min(t0-14d, now_of_window_end) - max(t0-70d, dataset_start or farmer_first)`, clamped to `(0, 56d]`; divide
  the count by `covered_days / 7`. If the covered span is 0 (no history reaches into the window),
  `baseline_per_week = 0.0`. This "use whatever part of the period the data covers" rule stops a brand-new
  farmer from looking artificially quiet because the 56-day window predates the dataset.
- **recent_count:** distinct conversations with earliest row in `[t0-14d, t0]`, **including the current
  conversation** (so it is always ≥ 1).
- **high_weight:** `mel.schedule.handoff.priority(insight) == "high"`. Reusing `priority()` keeps a single
  source of truth for "what counts as urgent" (R-2.3). (Import is local to avoid a P1→P3 import cycle at
  module load; `handoff` already imports only `config`/`timing`.)

### 2.5 Poisson tail
`P(X >= k)` for `X ~ Poisson(λ)`, `λ = baseline_per_week * jump_poisson_factor`, computed as
`1 - sum_{j<k} e^-λ λ^j / j!` with `math.exp`/`math.factorial` (k is small). This mirrors the deterministic,
dependency-free statistics already in `send_time._tail` (binomial there, Poisson here). When `λ == 0` the tail
is 1 for `k == 0` and 0 for `k >= 1`, so a truly silent baseline with a 3+ burst passes the test cleanly.

### 2.6 Tiering (R-3, first match wins)
```
if (t0 - dataset_start).days < min_dataset_age_days:        neutral / insufficient_history
elif baseline_per_week <= quiet_baseline_max and high_weight: surge / quiet_then_high_weight
elif recent_count >= jump_min_recent and poisson_tail(recent_count, baseline*2) < jump_poisson_p:
                                                             surge / activity_jump
elif baseline_per_week > 0 and recent_rate < declining_ratio * baseline_per_week:
                                                             neutral / declining
elif baseline_per_week >= steady_high_baseline:              steady_high / none
else:                                                        neutral / none
```
`recent_rate = recent_count / (recent_days/7)` per week. `weight` and a one-sentence `explanation` are filled
from the tier.

## 3. Wiring (P1-owned files)

### 3.1 `mel/pipeline.py`
- `run_pipeline(..., attention: bool = False)`. When true, build **one** `ActivityHistory` from the *unfiltered*
  `insights` (same place `FarmerMemory` and `by_farmer` are built), then for each chosen insight call
  `history.attention_for(insight)` and pass the result into `run_insight`.
- `run_insight(insight, farmer=None, history_hours=(), memory=None, attention=None)`: when `attention` is given,
  attach it to the Decision and let the three effects read it. `run_insight`'s default keeps today's behaviour.
- Because history is built from the unfiltered set, a farmer's tier is identical in a filtered and a full run
  (R-8). This is the exact pattern `by_farmer`/`chat_hours` already uses.

### 3.2 `mel/cli.py`
- `run` gains `--attention` (store_true, default off). `cmd_run` passes it to `run_pipeline`. With the flag
  absent, every write path is unchanged ⇒ identical files (R-7.2).
- `run_summary.json` gains `by_tier` (surge/neutral/steady_high) and `by_reason` (all reasons, always present,
  zero when off). Added alongside the existing counts in `PipelineResult.counts()`.

### 3.3 `Decision.attention`
`Decision` (P2's dataclass) needs an optional `attention: dict | None = None` field. This is a shared-shape
change to a P2 file, so it is in the request doc (R-13). Until P2 lands it, P1 attaches the dict dynamically in
`run_insight` (`setattr`), and the effects read `getattr(decision, "attention", None)`; the field makes it
first-class and keeps `counts()` clean.

## 4. The three effects (cross-owner — specified here, requested in the request doc)

The guiding rule: each effect is a **small, localised read** of `decision.attention`, gated so that when
attention is `None` (off) the code path is exactly today's.

### 4.1 Priority — `mel/schedule/handoff.py` (P3)
`build_handoff(insight, survey, attention=None)`:
```
prio = priority(insight)                       # unchanged brief priority
if attention is not None:
    prio = adjust_priority(prio, insight, attention)
```
`adjust_priority(brief_prio, insight, attention)`:
- `surge`: one step up (`low→normal`, `normal→high`, `high`→`high`). But **only** promote to `high` when the
  promotion budget allows it (R-6.2); the budget is enforced by a small per-ledger structure (below), so the
  *budget check* lives where the 7-day view exists — in the batch loop / CapLedger, not in a per-insight call.
  `build_handoff` promotes to the tier-implied priority; the once-per-7-days clamp for `activity_jump→high` is
  applied when hand-offs are admitted in send order.
- `neutral`: unchanged.
- `steady_high`: one step **down** only from `normal→low`; `high`→`high` and `low`→`low` (R-6.1 — never demote a
  brief-high survey).
- `exempt`/`wait_hours`/`channel_order` continue to derive from the final `prio`, so a promoted surge correctly
  gains voice fallback and the 6-hour waits, and a demoted steady_high loses the high-only extras.

**Once-per-7-days high budget (R-6.2).** A promotion to `high` whose *cause* is `activity_jump` is rate-limited
per farmer. Because this needs the rolling-7-day view, it is applied where surveys are seen in send order:
- the app and the CLI admit hand-offs through `CapLedger`/send-order already; a tiny `HighPromotionBudget`
  (farmer_id → list of promoted send-times) downgrades a second `activity_jump→high` within 7 days back to
  `normal` **before** the cap sees it. `quiet_then_high_weight` surges and brief-high surveys are not budgeted.

### 4.2 Question count — `mel/writer/` (P4)
The surge rule is "H4 does not apply; up to 3"; steady_high is "at most 2". Both must hold on the template and
LLM paths, with history on or off (R-6.5, R-6.6). The cleanest seam is `question_count` / `personalize`:
- Thread an optional `attention` (tier string is enough) into `write_surveys → compose_survey →
  template_items/_try_model` and into `history.personalize`.
- In `personalize` (H4): when tier is `surge`, skip the `activity_level == 'light'` clamp to 2 (H3 fatigue and
  the explicit schema cap still apply). When tier is `steady_high`, clamp the limit to `min(limit, 2)`.
- `question_count(insight, attention)`: unchanged default; `steady_high` ⇒ `min(result, 2)`. The LLM path in
  `_try_model` already asserts `len(items) == question_count(...)`, so passing the same `attention` keeps the
  model path consistent (R-6.6). The schema's 1–3 cap and `build_items`' real item count are the ceiling, so
  "up to 3" never invents questions (R-6.5).

### 4.3 Send time — `mel/timing/send_time.py` (P2)
`pick_send_time(insight, window, farmer=None, history_hours=(), attention=None)`: when tier is `surge`, return
the window-opening moment with a new rule id `attention_surge` ("Rising activity: send as soon as the window
opens."). This slots in **above** `advice_evening`/`usual_time` but is still inside the window via the existing
`_at(window, None, …)`, so it never sends before `not_before` (R-5.2). `high_severity` already does exactly
this for urgent cases; surge reuses that mechanism. neutral/steady_high leave send time unchanged.

## 5. Visibility (P5 — requested)

- **Highlighted farmers** panel (new, Overview or its own expander): rows where `tier != "neutral"`, sorted by
  `weight` desc then `created_at` desc, showing `explanation`. Driven by `decision.attention` from the batch.
- **Survey Studio:** show `tier` and `reason` for the picked insight; add an **attention demo** picker (made-up
  history) next to the "pretend survey history" demo — e.g. "quiet, then urgent", "steady heavy user",
  "went quiet" — constructed in-app exactly as the pretend-answers demo builds a `FarmerMemory`, because the
  pack has no designed surges.
- **Follow-up queue:** sort by `weight` first (then the current ordering).
- **Evaluation tab:** a before/after block (§6) naming the representative's request.
- App default: `run_pipeline(..., attention=True)` (the app already runs `history=True`).

## 6. Measure and report (P1 + P5)

A script (P1, e.g. `scripts/activity_report.py`) runs the full pack twice — `attention=False` then `True` —
through `run_pipeline`, plus the scorecard and golden eval, and writes `docs/results/activity_attention.md`
(and a small JSON for the Evaluation tab). It reports, per R-10:
- tier/reason counts broken down by `activity_level`;
- priority counts and cap outcomes (sent/moved/merged/skipped) on vs off;
- average questions per survey by `activity_level`, on vs off;
- golden decision / rule / channel / item similarity, on vs off (decision & rule must match; R-11.3);
- scorecard format / safety / timeliness (must stay 100%; R-10.1).
The prototype numbers are recorded as the *expected order of magnitude*; the real pipeline numbers replace
them, and thresholds in `config/activity_attention.json` are nudged if the real counts are wildly off (the
doc explains any change). The representative's request is named as the reason, per `CLAUDE.md`.

## 7. Determinism, safety, no-leakage checklist
- Pure arithmetic + `priority()`; no randomness, no I/O beyond the one config read. Same inputs ⇒ same tier.
- Only pre-`created_at` rows counted; dataset_start measured across the given set (R-1.1, R-3.1).
- Opt-outs (P3's `OptOutList`) are applied exactly as today, after attention, so a surge never overrides an
  opt-out (R-6.3). H3 fatigue in `personalize` runs regardless of surge (R-6.4).
- Hand-off/survey JSON gain no fields; `priority ∈ {high,normal,low}`; `parity` untouched (R-4, R-11).

## 8. Alternatives considered
- **Put tier on the hand-off JSON.** Rejected: the schema forbids extra fields and `parity` would fail. The
  Decision object is the established home for schema-excluded data (`send_time`).
- **A simple "activity doubled" ratio.** Rejected by the brief: it over-flags heavy/regular users. The Poisson
  tail on a doubled baseline, gated by `recent_count >= 3`, is the deterministic stand-in.
- **Detect change from `activity_level`.** Rejected: it is a static label (stated in the task and `farmers.csv`).
- **Enforce the once-per-7-days high budget inside `build_handoff`.** Rejected: a per-insight call cannot see
  the rolling window; the budget belongs where surveys are ordered (CapLedger/send loop).
