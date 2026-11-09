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
    tier: str  # "surge" | "neutral" | "steady_high"
    reason: str  # insufficient_history | quiet_then_high_weight | activity_jump | declining | none
    baseline_per_week: float
    recent_count: int
    weight: float
    explanation: str

    def as_dict(self) -> dict: ...  # exactly the keys R-4 lists, for Decision.attention / JSON summary
```

### 2.3 History index (built once per run)
```python
class ActivityHistory:
    def __init__(self, insights, settings=None): ...
    #   groups non-junk insights by farmer_id; records (created_at, conversation_id) per row;
    #   dataset_start = min(created_at) over VALID, non-junk rows only (see below).
    def attention_for(self, insight) -> Attention: ...
```
- **Junk filter:** skip any row where `mel.data.why_junk(row)` is non-empty, so broken/junk conversations never
  inflate counts (R-1.4, R-12).
- **Robust parsing (R-1.5):** a row is usable only if it has a `farmer_id` and a `created_at` that
  `parse_ist` accepts. Unusable rows are dropped silently — they never crash the run, never contribute to any
  count, and never affect `dataset_start`. `dataset_start = min(created_at)` over the usable, non-junk rows.
- **Distinct conversations:** counts are over distinct `conversation_id`, computed by filtering usable rows
  strictly before the insight's `created_at`, dropping the insight's own `conversation_id`, then taking the set
  of conversation ids whose *earliest* row falls in the window. Extra insights / junk rows in one conversation
  therefore add nothing (R-12).
- **No leakage:** only rows with `created_at < insight.created_at` are considered (R-1.1).

### 2.4 Metrics (R-2)
Let `t0 = parse_ist(insight.created_at)`.
- **baseline_per_week:** distinct conversations with earliest row in `[t0-70d, t0-14d)`. The covered span is
  `(t0-14d) - max(t0-70d, dataset_start)`, clamped to `(0, 56d]`; divide the count by `covered_days / 7`. The
  lower bound is **`dataset_start` only** (not the farmer's first chat; correction 4), so a farmer who happens
  to have no earlier rows is not rewarded with a tiny divisor. If the covered span is 0 (the whole 56-day
  window predates `dataset_start`, i.e. an insight inside the first 14 days of the dataset), `baseline_per_week
  = 0.0`; such insights are already `insufficient_history` anyway (first 28 days).
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
  `insights` (same place `FarmerMemory` and `by_farmer` are built), then for each chosen insight compute
  `history.attention_for(insight)` and pass the (possibly budget-clamped) result into `run_insight`.
- **The once-per-7-days `activity_jump→high` budget lives here (correction 1), not in a send/admit loop**, because
  `mel.cli run` never uses `CapLedger`. Walk **every** usable insight of the unfiltered set, grouped by farmer
  and sorted by `created_at`; for each one that would be an `activity_jump` surge promoting a `normal` brief
  priority to `high`, allow the promotion only if no earlier allowed `activity_jump→high` for that farmer falls
  within the prior 7 days — otherwise clamp its tier's effect to `normal` by annotating the attention dict with
  `"high_budget": "spent"`. This decision is made **before** `build_handoff`, so `priority`, `channel_order`,
  `wait_hours` and `frequency_cap.exempt` all see the same final priority. The walk is over the unfiltered,
  `created_at`-ordered set and is independent of input order, `--farmer` and `--limit` (R-6.2, R-8).
- `run_insight(insight, farmer=None, history_hours=(), memory=None, attention=None)`: `attention` (an
  `Attention`/dict or `None`) is passed to `decide()` so `pick_send_time` can read it, and to the effects.
  `run_insight`'s default keeps today's behaviour.
- Because history and the budget are built from the unfiltered set, a farmer's tier and promotion outcome are
  identical in a filtered and a full run (R-8). This is the exact pattern `by_farmer`/`chat_hours` already uses.

### 3.2 `mel/cli.py`
- `run` gains `--attention` (store_true, default off). `cmd_run` reads it with `getattr(a, "attention", False)`
  (correction 8, so arg builders in existing tests that omit it keep working) and passes it to `run_pipeline`.
  With the flag off, every write path is unchanged ⇒ identical files (R-7.2).
- `run_summary.json` gains `by_tier` (surge/neutral/steady_high) and `by_reason` **only when attention is on**
  (correction 6). With attention off the summary is byte-for-byte today's. `PipelineResult.counts()` gains an
  `attention`-gated extension that returns these two maps; `cmd_run` merges them into the summary only when the
  flag is on.

### 3.3 `Decision.attention` (real field, correction 7)
`Decision` (P2's dataclass, `mel/decision/rules.py`) gains a real `attention: dict | None = None` field — not a
dynamic `setattr`. `decide(insight, farmer=None, history_hours=(), attention=None)` threads it to
`pick_send_time` and stores it on the returned `Decision`. This is required because `pick_send_time` runs inside
`decide()`, so the attention result must be available at that point. `decide()` still never changes survey vs
no-survey, the rule or the send window — `attention` is read only by `pick_send_time` and only for a surge send
moment inside the window. P2 has agreed to this change (request doc).

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
`adjust_priority(brief_prio, insight, attention)` is a **pure per-insight** function — it does not own any
rolling window:
- `surge`: one step up (`low→normal`, `normal→high`, `high`→`high`), **unless** `attention["high_budget"] ==
  "spent"`, in which case the step up stops at `normal` (the 7-day budget decision was already made upstream in
  `run_pipeline`, correction 1).
- `neutral`: unchanged.
- `steady_high`: one step **down** only from `normal→low`; `high`→`high` and `low`→`low` (R-6.1 — never demote a
  brief-high survey).
- `exempt`/`wait_hours`/`channel_order` continue to derive from the final `prio`, so a promoted surge correctly
  gains voice fallback and the 6-hour waits, and a demoted steady_high loses the high-only extras.

**Once-per-7-days high budget (R-6.2).** Decided in `run_pipeline` (§3.1), not here. `run_pipeline` sets
`attention["high_budget"] = "spent"` on any `activity_jump` surge whose `normal→high` promotion would be the
second within 7 days for that farmer; `adjust_priority` simply honours that flag. `quiet_then_high_weight`
surges and brief-high surveys are never budgeted. `HighPromotionBudget` from the earlier draft is **removed**.

### 4.2 Question count — `mel/writer/` (P4)
The surge rule is "H4 does not apply; up to 3"; steady_high is "at most 2". Both must hold on the template and
LLM paths, with history on or off (R-6.5, R-6.6). **`template_items` only calls `personalize` when memory is
present, so a steady_high cap placed only in `personalize` would silently fail with history off** (correction
2). The cap therefore lives in `question_count`, which both paths already honour:
- Thread an optional `attention` (tier string is enough) into `write_surveys → compose_survey →
  template_items/_try_model`, into `history.personalize`, **and into `history_notes`**.
- `question_count(insight, attention)`: unchanged default; `steady_high` ⇒ `min(result, 2)`. `build_items` uses
  `question_count`, and `template_items` truncates to it; the LLM path in `_try_model` already asserts
  `len(items) == question_count(...)`. Passing the same `attention` to all three keeps template and model paths
  consistent **with history on or off** (R-6.6).
- In `personalize` (H4): when tier is `surge`, skip the `activity_level == 'light'` clamp to 2 (H3 fatigue and
  the schema cap still apply). This keeps surge "up to 3" even for a light user with history on.
- `history_notes(insight, memory, attention)`: when the surge skips H4, `personalize` must **not** append an
  `H4` note, so the rationale and the UI never claim a rule that was not applied (correction 2). Passing
  `attention` into `history_notes → personalize` makes the note set match what actually happened.
- The schema's 1–3 cap and `build_items`' real item count are the ceiling, so surge "up to 3" never invents
  questions (R-6.5).

### 4.3 Send time — `mel/decision/rules.py` + `mel/timing/send_time.py` (P2)
`pick_send_time` runs inside `decide()`, so `decide(insight, farmer, history_hours, attention=None)` threads
`attention` through to `pick_send_time(insight, window, farmer, history_hours, attention)` (correction 7).
When tier is `surge`, `pick_send_time` returns the window-opening moment with a new rule id `attention_surge`
("Rising activity: send as soon as the window opens."). This slots in **above**
`high_severity`/`advice_evening`/`usual_time` but is still inside the window via the existing
`_at(window, None, …)`, so it never sends before `not_before` (R-5.2). `high_severity` already does exactly
this for urgent cases; surge reuses that mechanism. neutral/steady_high leave send time unchanged. `decide()`
still returns the same `survey`/`rule`/`send_window`; only `send_time` can differ for a surge.

## 5. Visibility (P5 — requested)

- **Highlighted farmers** panel (new, Overview or its own expander): **surge insights only** (never
  steady_high; correction 3), sorted by `weight` desc then `created_at` desc, showing `explanation`. Driven by
  `decision.attention` from the batch.
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
- **Enforce the once-per-7-days high budget inside `build_handoff`, or in a `CapLedger`/send loop.** Rejected:
  a per-insight call cannot see the rolling window, and `mel.cli run` never uses `CapLedger`, so a send-loop
  budget would never run in the CLI. The budget is decided in `run_pipeline` over the unfiltered,
  `created_at`-ordered set, before `build_handoff`, so every derived field (priority, channel order, waits,
  cap exemption) agrees and the result is independent of input order and filtering (correction 1).
