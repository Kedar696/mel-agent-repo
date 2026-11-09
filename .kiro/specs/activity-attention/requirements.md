# Requirements: Activity attention

## Introduction

The beneficiary's representative asked us to focus survey attention on positive **change** in a farmer's
activity, not on high activity itself. Attention means more questions, faster sending and more weight.

- Low activity, then a sudden high-weight question or a jump in activity: highlight this farmer (**surge**).
- Constantly high activity: no longer top treatment by default (**steady_high**).
- High activity that drops or stops: not relevant. No boost, no penalty, no highlight (**neutral**).

This is a deliberate change to the brief's behaviour, so it is **off by default** in the CLI and in scoring,
**on** in the app (matching the team's 4 Nov decision for the history rules). With it off, every output is
byte-for-byte identical to today. The change and its effect on the numbers are reported with evidence and
named as the representative's request, per `CLAUDE.md` ("deliberate changes must be shown with numbers").

`activity_level` in `farmers.csv` is a static label and is not used to detect change.

## Requirements

### R-1 A pure, deterministic attention module (no leakage)
**User story:** As an integrator, I want attention computed in one pure, rule-based module so it is testable,
explainable and reproducible.
1. A new module `mel/data/activity.py` (P1-owned) SHALL compute, for each insight, an attention result from
   that farmer's history, using **only** data with `created_at` strictly before the insight's `created_at`
   (no future leakage).
2. It SHALL be rule-based and deterministic: the same inputs SHALL always give the same result. No model calls.
3. Settings (thresholds, windows, weights) SHALL live in `config/activity_attention.json`, **outside** the
   parity-checked folders (`config/rules/`, `config/schemas/`).
4. It SHALL count **distinct `conversation_id`s**, not insights. It SHALL exclude junk rows (per
   `mel.data.why_junk`) and exclude the current conversation from history.
5. The **dataset start** SHALL be computed from valid, non-junk rows only. Rows with an unparseable or missing
   `created_at`, or a missing `farmer_id`, SHALL NOT crash the run and SHALL NOT count as activity.

### R-2 The metrics each insight is scored on
For each insight the module SHALL compute, over the farmer's non-junk history before `created_at`:
1. `baseline_per_week`: conversations from 70 to 14 days before the insight, divided by the number of weeks of
   the 70→14-day window that fall at or after the **dataset start** (use whatever part of the period the data
   covers; measure the covered span only from the dataset start, never from the farmer's first chat, and never
   divide by a period longer than the data spans).
2. `recent_count`: conversations in the last 14 days before the insight, **including the current one**.
3. `high_weight`: the existing high-priority test (resolution `escalate_to_expert`, severity `high`/`critical`,
   or behavioural intent `emergency`). This SHALL **reuse** `mel.schedule.handoff.priority(...) == "high"`
   logic, not a copy of it.

### R-3 Tiering, first match wins
The module SHALL assign the first tier that matches, in this order:
1. **neutral**, reason `insufficient_history`: the insight is under 28 days after the **dataset start**
   (the earliest `created_at` across all insights given, not the farmer's first chat), so a new farmer late in
   the season can still surge.
2. **surge**, reason `quiet_then_high_weight`: `baseline_per_week <= 0.5` and `high_weight`.
3. **surge**, reason `activity_jump`: `recent_count >= 3` **and** the Poisson probability of at least
   `recent_count` events, with expected value `baseline_per_week * 2`, is below `0.001`.
4. **neutral**, reason `declining`: the recent rate is under half the baseline. Treated exactly as any neutral.
5. **steady_high**: `baseline_per_week >= 1.5`.
6. **neutral** (reason `none`): everyone else.

### R-4 The attention result goes on the Decision, not the hand-off
1. The result SHALL be exposed as a real `Decision.attention` field (a dataclass field, not a dynamic
   `setattr`), a dict with keys `tier`, `reason`, `baseline_per_week`, `recent_count`, `weight`, `explanation`,
   or `None` when attention is off. This follows the `send_time` pattern: the hand-off/survey schemas forbid
   extra fields, so new data rides on the Decision object only. Because `pick_send_time` runs inside `decide()`,
   the attention result SHALL be available to `decide()` so send time can read it (R-5.2); attention SHALL still
   never change survey vs no-survey, the rule, or the send window.
2. `weight` SHALL be `1.5` for surge, `1.0` for neutral, `0.5` for steady_high.
3. `explanation` SHALL be one plain-English sentence.
4. The hand-off JSON and the survey JSON SHALL stay schema-valid and gain **no** new fields. Hand-off
   `priority` SHALL remain one of `high`/`normal`/`low`.

### R-5 Effects on priority, questions and send time
When attention is on:

| | surge | neutral | steady_high |
|---|---|---|---|
| Priority | one step up: low→normal, normal→high | unchanged | one step down: normal→low |
| Questions | H4 does not apply; up to 3 | unchanged | at most 2 |
| Send time | as soon as the window opens | unchanged | unchanged |

1. Priority adjustment SHALL be applied to P3's `priority()` result, never below `low` or above `high`.
2. "Faster" (surge send time) SHALL mean the window's opening moment, and SHALL NOT send before the window
   opens (advice needs time to be acted on).
3. Attention SHALL change **only** priority, question count and the send moment. It SHALL NOT change survey vs
   no-survey, the rule (R1–R8), or the send window `[not_before, not_after]`.

### R-6 Safety rules
1. **Never demote a brief-high survey.** A survey the brief's rules make high priority (e.g. an urgent
   question from a steady heavy user) SHALL stay `high`, cap-exempt and fast, regardless of tier. steady_high's
   one-step-down SHALL only lower `normal`→`low`.
2. **Promotion to `high` from `activity_jump` at most once per farmer per rolling 7 days.** Because `high`
   skips the weekly cap, a surge (`activity_jump`) survey SHALL be promoted to `high` only if no earlier
   `activity_jump` promotion to `high` for that farmer falls within the prior 7 days; later ones in that window
   keep `normal`. (A survey already `high` by the brief's rules, and `quiet_then_high_weight` surges, are
   unaffected by this budget.) This limit SHALL be decided in `run_pipeline` — working through each farmer's
   insights from the **unfiltered** list in `created_at` order and deciding whether the promotion is allowed
   **before** `build_handoff`, so that `priority`, `channel_order`, `wait_hours` and `frequency_cap.exempt` all
   agree. `mel.cli run` does not use `CapLedger`, so the limit SHALL NOT live in a send or admit loop. Input
   order, `--farmer` and `--limit` SHALL NOT change the result.
3. **Opt-outs still block everything.** An opted-out farmer gets nothing, surge or not.
4. **H3 fatigue still shortens surveys**, including for surge farmers.
5. The **3-question schema limit** still applies: surge "up to 3" SHALL NOT invent questions the template does
   not have.
6. The surge and steady_high question limits SHALL work with history **on or off**, and on **both** the
   template and the model-written (LLM) paths. Because `template_items` only calls `personalize` when memory is
   present, the steady_high cap of 2 SHALL be applied in `question_count` (and the template/LLM item builders),
   not only inside `personalize`, so it still holds with history off. `attention` SHALL also be passed to
   `history_notes`, so a surge survey never reports an `H4` note when H4 was not applied.

### R-7 Off by default; identical output when off
1. `run_pipeline` SHALL gain `attention=False`; the CLI SHALL gain a `--attention` flag (default off).
   Scoring (`eval`, scorecard, golden) SHALL default attention **off**. The app SHALL default attention **on**.
2. WHEN attention is off THEN decisions, rules, channels, priorities, question counts, send times, hand-offs
   and all written files SHALL be identical to the current code, for all 6,999 insights. `by_tier` and
   `by_reason` SHALL be added to `run_summary.json` **only when attention is on**; with attention off the
   summary file SHALL stay identical to today (the keys are absent).

### R-8 Filtering must not change a farmer's result
WHEN `--farmer` or `--limit` narrows a run THEN each remaining farmer's attention result SHALL be identical to
its result in a full run. Attention history SHALL be computed from the **unfiltered** insight set (as send time
already is), not from the filtered subset.

### R-9 Visibility
1. The Streamlit app SHALL show a **"Highlighted farmers"** list of **surge insights only** (never
   steady_high), sorted by `weight` then recency, each with its `explanation` sentence.
2. Survey Studio SHALL show the `tier` and `reason` for the selected insight.
3. The app's **follow-up queue** SHALL sort by `weight` first.
4. `run_summary.json` SHALL gain counts by `tier` and by `reason` (present and zero when attention is off).
5. Survey Studio SHALL gain an attention demo that uses a made-up farmer history (like the existing "pretend
   survey history" demo), because the pack's activity is flat across the season and has no designed surges.

### R-10 Measure and report
1. Before/after (attention off vs on) on the full pack SHALL be reported:
   - tier and reason counts by `activity_level`;
   - priority counts, and sent/moved/merged/skipped under the cap;
   - average questions per survey by `activity_level`;
   - golden decision / rule / channel / item similarity;
   - the scorecard (format, safety, timeliness). **Format, safety and timeliness SHALL stay at 100%.**
2. The prototype counts (quiet_then_high_weight ≈ 109, activity_jump ≈ 63, steady_high ≈ 303 of which ≈ 292
   heavy, over ≈ 3,283 survey-type insights after day 28) are **starting values only**; they did not go through
   the real pipeline. The thresholds SHALL be re-measured through the pipeline and adjusted with evidence. A
   plain "activity doubled" ratio SHALL NOT be used (it over-flags heavy/regular users).
3. The report SHALL be written to `docs/results/` and surfaced in the app's **Evaluation** tab, naming the
   representative's request as the reason for the change.

### R-11 Parity and schemas unchanged
1. `python -m mel.cli parity` SHALL still pass. No file under `config/rules/`, `config/schemas/`,
   `data/mock/scenarios/`, `data/mock/outcomes/` or the participant pack SHALL be edited.
2. With attention on, every hand-off SHALL remain schema-valid.
3. The golden decision and rule SHALL be identical with attention on and off for all 6,999 insights (attention
   never changes survey vs no-survey or the rule).

### R-12 Tests
`tests/test_activity.py` SHALL cover, with hand-built farmers: quiet→high-weight = surge; same question from a
steady heavy farmer = steady_high with priority still high; a heavy farmer going quiet = neutral/unchanged/not
highlighted, and again when that farmer later returns; gradual growth ≠ surge; an insight in the first 28 days
= neutral and a new farmer late in the season = can surge; adding later insights never changes earlier results;
junk rows and extra insights in one conversation do not raise the counts; a burst promotes to `high` only once
in 7 days; a surge farmer who is opted out or fatigued is still blocked or shortened; filtered and full runs
agree for the same farmer. On the full pack: decision and rule identical on/off for all 6,999; outputs
identical with attention off; all hand-offs schema-valid.

### R-13 Cross-owner changes go through a request
Changes to files owned by P2 (`mel/timing/`), P3 (`mel/schedule/`), P4 (`mel/writer/`) and P5
(`mel/evaluation/`, `app/`) SHALL be written up as a request in `docs/activity_attention_request.md`, listing
the exact small change per file, per the file-ownership steering. P1-owned files
(`mel/data/activity.py`, `mel/pipeline.py`, `mel/cli.py`, `config/activity_attention.json`, `docs/`,
`CLAUDE.md`, `.github/CODEOWNERS`) may be changed directly.
