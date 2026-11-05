# Questions for Digital Green

Draft from P1. **P1 sends these; nobody else contacts the organisers.** This is ready to send: each
question is short, has a real example from the pack, and is flagged ⚙ when the answer would change our
code (so we know which replies to act on). Every number below was measured on the committed pack
(`mel-survey-agent-participant-pack/participant-pack/`) by running our code at commit `343742f` (5 Nov),
under the brief's rule (`MEL_TIMING_BASIS=brief`), which is our default. Where "ours" differs from the
answer key, it is because we follow the brief, not the key.

The ask in one line: the brief and the answer key disagree in a few places; we have built to the brief and
want to know which wins for scoring, plus a handful of questions about relevance, late answers, reachability,
licensing and the AWS deployment so we can finish the integration without guessing.

---

## 1. Do survey windows open at 09:00 or at 07:00? ⚙

The brief and the five worked scenarios open the window at **07:00** on a later day. The golden set (the
answer key) opens it at **09:00**, often on an earlier day. Against the key our window match is **0%** under
the brief rule and **100%** under an answer-key setting we built as an option (`MEL_TIMING_BASIS=answer_key`),
so this is purely a question of which convention you score.

What the brief says (`rules.json` `window_rules`): earliest start day 1, never before the action window ends,
`not_before_time` 07:00, `not_after_time` 19:00. Two golden rows show the clash (measured today):

| Golden id | Insight created | Action window | Answer-key window | Our window (brief rule) |
|---|---|---|---|---|
| G-0002 (wheat, plan created) | 2026-11-06 06:06 | 8 days | 2026-11-13 **09:00** → 2026-11-20 19:00 | 2026-11-14 **07:00** → 2026-11-20 19:00 |
| G-0003 (cabbage, do not act yet) | 2026-11-12 09:40 | 10 days | 2026-11-15 **09:00** → 2026-11-22 19:00 | 2026-11-22 **07:00** → 2026-11-24 19:00 |

In G-0002 the key opens the window 7 days after the insight, which is *before* the 8-day action window ends;
the brief says a survey must not go out before the action window closes. So the two documents disagree on both
the time (09:00 vs 07:00) and the day.

Questions:
- Is 07:00 (brief) or 09:00 (answer key) the correct opening time?
- May a survey open before the action window ends, as the key does in G-0002/G-0003? Or does the brief win?
- Which convention will you score us against in the final judging?

## 2. Critical cases: a survey, or a human call? ⚙

The golden set has **6** rows with `severity: critical` (G-0016, G-0030, G-0076, G-0078, G-0108, G-0138). All
six expect **no survey**: rule R2, reason `critical_needs_human_call`. But `rules.json` lists `critical` under
`priority.high_if_resolution`/`high_if_severity`, which reads as "send a high-priority survey". We follow the
golden set (no survey) and score 99.3% decision/rule, so this is about intent, not our output.

Examples from the answer key:
- G-0030: buffalo not eating, feels hot; advice was to call the nearest vet today. Expected: no survey.
- G-0016: pea leaves with white winding lines; advice was to remove leaves and spray neem oil. Expected: no survey.
- G-0076: aphids on wheat; advice asked for more details first. Expected: no survey.

Questions:
- For `critical` insights, do you want (a) a high-priority survey, or (b) no survey plus a person calling the farmer?
- If (b), where should we record the call request? Today we only write a no-survey record with the reason text.
- G-0016 and G-0076 are not obvious emergencies. Is the `severity` label the only trigger, as we assume?

## 3. Is a new golden set coming?

Our scores are measured on the 150 rows we have: today, under the brief rule, **decision 99.3%, rule 99.3%,
channel 100%, window 0%** (one decision miss, G-0145, a one-day 31-March window); under the answer-key setting,
100% on all four. (The older 96.0% figure was the base code at commit 5763855; P2's R7 storage fix lifted it to
99.3%.) We have `scripts/compare_golden.py` to diff an old and a new golden file and a checklist to re-run
everything.

Questions:
- Will there be a second version of the golden set (v2)? If so, when, and in the same format?
- If the windows change in v2 (question 1), should we expect other columns to change too?
- Are the rule ids R1–R8 final? They are not named in the brief; we inferred them from the golden rows.

## 4. Is there an MEL relevance rubric? ⚙

We score each survey's relevance two ways: a deterministic keyword score (0–1) and an AI judge on Bedrock that
rates 1–5 against a rubric we wrote ourselves (in `README.md`), because the pack ships none. Example: for
G-0002 (wheat plan) our survey asks whether the farmer did the plan's first step and whether it is working.

Questions:
- Do you have an official MEL rubric for judging survey relevance? If so, may we use it?
- If not, is our 1–5 rubric (one farmer, one context; ask about the advice given; never give new advice; short
  and tappable) acceptable for the demo? ⚙ (we would replace ours with yours).

## 5. Does our survey JSON match your agent-to-UI format? ⚙

We emit one survey JSON per language, validated against the pack's `survey.schema.json`, plus a
`schedule_handoff.json` for the sender. Example (G-0002, en-IN): a 1–3 item tap survey with `survey_id`,
`farmer_id`, `source_insight_ids`, `language`, `items` (prompt + ≤20-char option labels), `self_eval` and a
`send_window`.

Questions:
- Is `survey.schema.json` the same shape FarmerChat's agent hands to the app's UI, or is there a different
  agent-to-UI contract we should match? ⚙
- If different, can you share that schema so we render to it directly?

## 6. Which Bedrock models and region are enabled? ⚙

Our AI writer (P4) and AI relevance judge (P5) call Amazon Bedrock through the account's IAM role (no model
key). We have been testing against `us-east-1` with a Claude Haiku inference profile and a Gemma judge, but we
do not know what the event account actually allows.

Questions:
- Which Bedrock models (ids / inference profiles) are enabled, and in which region? ⚙
- Is model access on the account's IAM role, as we assume, so there is no key to manage?

## 7. Late answers: kept or dropped, and a `late` field? ⚙

The brief (`schedule_handoff.schema.json` → `expires_at`) says late answers are **kept but marked late**. But
the pack's reference outcome `survey_closed` shows a chat tap *after* expiry recorded as dropped (`answers {}`).
These conflict for chat channels. Today we keep late answers for the app/web sheet and follow the pack's
`survey_closed` behaviour for chat; we can only mark a record `late` if the response schema gains the field
(see `docs/h4_schema_change_request_late.md`).

Questions:
- For WhatsApp and Telegram, which wins — "late answers are kept" (brief) or "dropped after expiry"
  (`survey_closed`)? ⚙
- Will you add an optional boolean `late` to `response.schema.json` in the pack? If yes, we turn it on; if no,
  we keep lateness as a count in our run summary and note a parity exception. ⚙

## 8. Will you supply channel-reachability data? ⚙

`farmers.csv` has only `preferred_channel` (columns: `farmer_id, country, state, district, language,
preferred_channel, crops, land_size_band, livestock, activity_level`). Our channel fallback would like to know
which channels a farmer can actually be reached on; right now we treat every channel as reachable, so we never
skip one. Example: a farmer whose `preferred_channel` is `app` — can we also reach them on WhatsApp and voice?

Questions:
- Will you add a `reachable_channels` column (pipe-separated, like `crops`)? ⚙ (we would use it to skip
  unreachable channels).
- Or is "every channel is reachable" the agreed default? (We will write that down and move on.)

## 9. Do you require a specific open-source licence? ⚙

We have added Apache-2.0 to the repo, with a NOTICE that the licence does not cover your participant pack or
data derived from it.

Question:
- Is Apache-2.0 fine, or do you require a specific licence for the submission? ⚙ (we would swap the LICENSE
  file).

## 10. Weather-dependent advice: should the window move? ⚙

Your Vision doc asks how the send window should be set when advice depends on the weather. The brief's mustard
example says "spray within 2 days if no rain is forecast". The pack has no weather data and no field for this;
only the advice text says it (1,169 of 6,999 advice summaries mention rain, fog, frost, the forecast or the
weather). Today we plan these windows like any other advice.

Questions:
- Will insights carry a structured weather condition (for example `weather_condition: "no_rain"`), and can we
  read the district forecast through AgMCP? ⚙ (we would count only suitable days toward the action window; see
  "Weather-dependent advice" in `mel/timing/README.md`).
- Or should the window ignore the weather, as it does now?

---

## AWS design

We have defined (not deployed) a container REST API with a Dockerfile and `infra/` (an ECR repository, an App
Runner service, and an EKS Deployment/Service), with an IAM role limited to Bedrock inference. We want to
confirm the deployment shape before building anything live.

- Is **EKS** the intended deployment target, or should we plan for something else? ⚙
- Do you want the container image pushed to a specific registry (your ECR), or is ours fine for the demo?
- Are the **IAM role and Bedrock access** provided by the event account, or ours to set up?
- Are the REST endpoint shapes acceptable? We expose `POST /surveys` (run one insight → survey or no-survey)
  and `GET /surveys/due` (what is due to send at a given time); state is in memory, one replica. ⚙
- In production, would you run **EventBridge** (scheduling/retries), **RDS** (the weekly limit and opt-outs) and
  **Amazon Connect** (voice) as our design assumes? (These are slide-only for the hackathon.)
- Is **App Runner** acceptable for the demo link, or should the demo run only on EKS? ⚙

---

_Flagged ⚙ questions can change our code; the rest are confirmations. See
`docs/h4_schema_change_request_late.md` for the late-answer schema options and `docs/cap_policy.md` for the
weekly-limit rules._
