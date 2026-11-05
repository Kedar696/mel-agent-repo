# Request: small changes for the activity-attention feature

From: P1 (Data, Contracts & Integration)
To: P2 (Decision & Timing), P3 (Scheduler), P4 (Survey Writing), P5 (Evaluation & Demo)
Status: **proposed, not applied.** P1 has not edited any file under `mel/timing/`, `mel/schedule/`,
`mel/writer/`, `mel/evaluation/` or `app/`. Spec: `.kiro/specs/activity-attention/`.

## Why
The beneficiary's representative asked us to focus survey attention on positive **change** in activity, not on
high activity itself. P1 adds a pure, off-by-default module `mel/data/activity.py` that labels each insight with
a tier — `surge` (quiet then a jump or an urgent question), `steady_high` (constantly busy), or `neutral`
(everyone else, including farmers who go quiet). The tier rides on `Decision.attention` (the hand-off/survey
schemas forbid extra fields, so it goes on the Decision exactly as `send_time` does). Three small effects read
it. **With attention off, every output is identical to today**; this is the regression guarantee.

What P1 provides and these changes call:
- `Decision.attention` — a **real dataclass field**: `{tier, reason, baseline_per_week, recent_count, weight,
  explanation, high_budget?}` or `None` (off). `high_budget == "spent"` marks an `activity_jump` surge whose
  promotion to `high` is over the 7-day budget (decided in `run_pipeline`).
- Tiers: `"surge" | "neutral" | "steady_high"`. Weight 1.5 / 1.0 / 0.5.
- `run_pipeline(..., attention=False)` / CLI `--attention` (default off; the app passes `attention=True`).

Each change below is gated so that when `attention is None` the path is **exactly** today's code.

**Status: all four owners have agreed to the changes below (Phase 1 approval).**

---

## P2 — `mel/decision/rules.py` and `mel/timing/send_time.py`

### 2a. Add a real field to `Decision` and thread it through `decide()` (`mel/decision/rules.py`)
`pick_send_time` runs **inside** `decide()`, so attention must reach `decide()` — a dynamic `setattr` after the
fact is too late for send time. Add a real dataclass field and an `attention` parameter:
```python
@dataclass
class Decision:
    ...
    send_time: dict | None = None
    attention: dict | None = None   # {tier, reason, ...}; None = off

def decide(insight, farmer=None, history_hours=(), attention=None) -> Decision:
    ...  # every no-survey branch is UNCHANGED and ignores attention
    return Decision(True, "R8", None, win,
                    send_time=pick_send_time(insight, win, farmer, history_hours, attention),
                    attention=attention)
```
`decide()` still returns the same `survey`/`rule`/`send_window`; `attention` only reaches `pick_send_time` and
is stored for downstream readers. No change to survey vs no-survey or the rule. Shared-shape change (agreed).

### 2b. Surge sends as soon as the window opens (`mel/timing/send_time.py`)
Add an optional `attention` arg and one rule, placed **first** (above `high_severity`/`advice_evening`), still
inside the window so it never sends before `not_before`:
```python
def pick_send_time(insight, window, farmer=None, history_hours=(), attention=None):
    if attention and attention.get("tier") == "surge":
        return _at(window, None, "attention_surge",
                   "Rising activity: send as soon as the window opens.")
    ...  # unchanged from here
```
`_at(window, None, …)` already clamps to the window opening (same mechanism `high_severity` uses), so R-5.2
(never before the window opens) holds.

**Effect, attention off:** `attention` is `None`, the new branch is skipped, send time is unchanged.

---

## P3 — `mel/schedule/handoff.py`

### 3a. `build_handoff` takes the tier and adjusts priority
```python
def build_handoff(insight, survey, attention=None):
    prio = priority(insight)                        # unchanged brief priority
    if attention is not None:
        prio = adjust_priority(prio, insight, attention)
    ...  # the rest uses `prio` exactly as today (exempt, waits, channel_order, frequency_cap)
```
```python
STEP_UP   = {"low": "normal", "normal": "high", "high": "high"}
STEP_DOWN = {"high": "high", "normal": "low", "low": "low"}   # never demote a brief-high survey

def adjust_priority(brief_prio: str, insight: dict, attention: dict) -> str:
    tier = attention.get("tier")
    if tier == "surge":
        up = STEP_UP[brief_prio]
        # 7-day high budget decided upstream in run_pipeline: if spent, stop at normal.
        if up == "high" and attention.get("high_budget") == "spent":
            return "normal"
        return up
    if tier == "steady_high":
        return STEP_DOWN[brief_prio]          # only normal->low; high stays high (R-6.1)
    return brief_prio                          # neutral
```
Because `channel_order`, `wait_hours_by_priority`, and `frequency_cap.exempt` all derive from the final `prio`,
a promoted surge automatically gets the voice fallback / 6-hour waits / cap exemption, and a demoted steady_high
loses the high-only extras. No change to the hand-off JSON shape; `priority` stays `high`/`normal`/`low`.

### 3b. The once-per-7-days cap on `activity_jump → high` is NOT in this file
Because `high` skips the weekly cap, promoting every surge to `high` would bypass the cap repeatedly. The limit
is decided **in `run_pipeline`** (P1), over the unfiltered, `created_at`-ordered insight set, **before**
`build_handoff` is called — not in a send/admit loop, because `mel.cli run` never uses `CapLedger`. `run_pipeline`
sets `attention["high_budget"] = "spent"` on the second `activity_jump→high` for a farmer within 7 days;
`adjust_priority` (3a) honours the flag. `quiet_then_high_weight` surges and brief-high surveys are never
budgeted. There is **no `HighPromotionBudget` class** and `handoff.py` holds no rolling-window state.

**Effect, attention off:** `build_handoff(insight, survey)` keeps its current two-arg call (P1 passes
`attention=None` only when the flag is on), `adjust_priority` is never reached.

---

## P4 — `mel/writer/compose.py`, `mel/writer/templates.py`, `mel/writer/history.py`

Goal: **surge** ⇒ H4 (light-user cap to 2) does not apply, up to 3 questions; **steady_high** ⇒ at most 2.
Must hold on the template and LLM paths, with history on or off, and never invent questions past the template's
real count or the schema's 1–3 cap.

### 4a. Thread the tier down (tier string is all that is needed)
- `write_surveys(insight, send_window, langs=LANGS, memory=None, attention=None)`
- `compose_survey(decision, insight, lang=BASELINE_LANG, memory=None, attention=None)`
- `template_items(insight, lang, style=None, memory=None, attention=None)` → pass into `personalize`
- `question_count(insight, attention=None)` and `_try_model(..., attention)` so the LLM item-count check matches
- `history_notes(insight, memory, attention=None)` → pass into `personalize`, so the H4 note is emitted **only
  when H4 was actually applied** (correction 2: a surge that skips H4 must not report H4)

### 4b. `question_count` respects steady_high (so it works with history OFF)
The steady_high cap of 2 **must** live here, not only in `personalize`: `template_items` calls `personalize`
only when `memory` is present, so with history off `personalize` never runs. `build_items` and the LLM
item-count check both go through `question_count`, so putting the cap here makes it hold on both paths with
history on or off (correction 2).
```python
def question_count(insight, attention=None):
    n = 2 if (insight['resolution_type'] != 'direct_action' or insight.get('severity') == 'low') else 3
    if attention and attention.get("tier") == "steady_high":
        n = min(n, 2)
    return n
```
`build_items(insight, style, attention=None)` passes `attention` to `question_count`; `template_items` truncates
to `question_count(insight, attention)` on the no-memory path too.

### 4c. `personalize` (H4 / H3) respects the tier (`mel/writer/history.py`)
```python
def personalize(items, i, mem, attention=None):
    ...
    # H3 fatigue: unchanged — still shortens, including for surge (R-6.4)
    ...
    tier = (attention or {}).get("tier")
    if ctx['activity_level'] == 'light' and tier != 'surge':   # H4 skipped for surge (R-5, R-6.6)
        if limit > 2: notes.append(('H4', 'light user'))
        limit = min(limit, 2)
    if tier == 'steady_high':
        limit = min(limit, 2)
    if len(items) > limit:
        items = items[:limit]
    return items, notes
```
"Up to 3" is still bounded by `build_items`' real item count and the schema's 1–3 cap, so surge never invents a
question (R-6.5). On the LLM path, `_try_model` already asserts `len(items) == question_count(...)`; passing the
same `attention` keeps it consistent (R-6.6).

**Effect, attention off:** `attention` is `None` everywhere, `question_count` and `personalize` behave exactly
as today (H4 still caps light users, no steady_high clamp).

---

## P5 — `app/streamlit_app.py` and `mel/evaluation/`

### 5a. App turns attention on
The app already runs `history=True`; add `attention=True` to its `run_pipeline(...)` call so Decisions carry a
tier.

### 5b. "Highlighted farmers" list — surge only
A panel (Overview, or its own expander) listing insights where **`tier == "surge"`** (never steady_high;
correction 3), sorted by `weight` desc then `created_at` desc, each showing `decision.attention["explanation"]`.
Data comes from the batch Decisions.

### 5c. Survey Studio: tier + reason, and a made-up-history demo
Show `tier` and `reason` for the picked insight. Add an attention demo selector next to the existing "pretend
survey history" picker (the pack's activity is flat with no designed surges), building a small synthetic history
in-app just as the pretend-answers demo builds a `FarmerMemory` — e.g. "quiet, then urgent" (⇒ surge /
quiet_then_high_weight), "steady heavy user" (⇒ steady_high), "went quiet" (⇒ neutral).

### 5d. Follow-up queue sorted by weight first
Sort the follow-up queue by `decision.attention["weight"]` desc first, then the current ordering.

### 5e. Evaluation tab: before/after block
Surface the before/after numbers P1's `scripts/activity_report.py` writes (tier/reason by `activity_level`,
priority & cap counts, avg questions by `activity_level`, golden decision/rule/channel/item similarity,
scorecard format/safety/timeliness — which must stay 100%). Name the representative's request as the reason, per
`CLAUDE.md`. P1 can supply the JSON the tab reads.

**Effect, scoring:** `mel/evaluation/` (golden, scorecard) keeps attention **off** by default (it calls
`run_insight`/`run_pipeline` without the flag), so all current scores are unchanged unless a run explicitly
turns it on for the comparison.

---

## If you'd rather P1 not touch your file at all
Each cross-owner edit above is small and additive. If any owner prefers, P1 can instead consume a thin helper
you expose (e.g. P3's `adjust_priority`/`HighPromotionBudget`, P4's `attention`-aware `question_count`), and P1
only calls it. Say which you prefer per file and P1 will wire to that.
