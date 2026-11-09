# Slide draft: Fasal Pulse - MEL Survey Agent (judges' deck)

Owner: P5. A text draft for the team to review before we build the real deck. The deck supports the live
3-minute demo (`docs/demo_script.md`); it doesn't replace it.

**Numbers rule (team contract):** every number here comes from the README results block, which
`python scripts/readme_numbers.py --write` regenerates. Rerun it and re-check every number before the demo.
Numbers below are from 4 Nov.

---

## 1. Title
**Fasal Pulse - MEL Survey Agent**: short follow-up surveys about the advice each farmer actually got.
Team names · Digital Green × hackathon · Nov 2026

## 2. The problem
- FarmerChat gives advice to 2.2 million farmers. Did they use it? Did it work?
- Today's answer: field surveys on small samples (expensive, slow) or one generic survey for everyone.
- Our agent turns each conversation into a 1–3 tap survey about *that farmer's* advice, at the right time.

*Speaker note:* one sentence each. Then switch to the live demo (Survey Studio).

## 3. How it works (one diagram)
Conversation summary → **survey or not?** (8 rules) → **questions** in Hindi + English → **safety checks**
→ **when and how to send** (send window, channel order, weekly limit) → farmer answers → **trouble answers
become follow-up tickets**.

*Speaker note:* "A missed survey is better than an irrelevant one", which is Digital Green's own principle.
Most conversations get no survey, and each "no" has a written reason.

## 4. Results: graded on Digital Green's five dimensions
| | Result |
|---|---|
| Decision vs the 150-case answer key | **99.3%** right |
| Format (valid, 1–3 tap questions, right language) | **100%** of 5,232 files |
| Safety (no new advice, no personal info) | **100%** |
| Timeliness (after the farmer could act, daytime, in season) | **100%** |
| Relevance | P4 score 0.81 · AI judge (Gemma 3 12B on Bedrock) 4.48 / 5; within 1 point of a person 97% (people with each other 83%) |
| Speed | ~2 ms per survey · 6,999 conversations in ~6 s |

*Speaker note:* everything here is checked on all 6,999 conversations, not a sample.

## 5. Rule we changed #1: stored crops still get a survey
- **Before:** 96.0% right. All 6 mistakes were the same case: potatoes (and one cauliflower) already dug
  up and in storage. Our rule said "harvested, nothing to ask".
- **Why we changed it:** stored produce can still rot, so the advice still needs checking.
- **After:** **99.3%** right, 6 mistakes → 1. Nothing else got worse (all other checks still 100%).
- The last mistake (G-0145): the answer key accepts a one-day window on 31 March; the brief requires two days.

## 6. Rule we changed #2: when to send (a trade-off we chose on purpose)
| Send-time rule | Matches answer key | Timeliness |
|---|---|---|
| Brief rules (**our default**) | 0% | **100%** |
| Answer-key setting | **100%** | 26.5% |

- Digital Green's written brief and their answer key disagree on *when* to send.
- We built both. The answer-key rule would ask **3 in 4 farmers before they could have acted** on the advice.
- So the brief stays the default, the answer-key rule is one setting, and we've asked Digital Green to confirm.

*Speaker note:* this is the most important slide for "quality over volume". Show the toggle on the
Evaluation tab live if time allows.

## 6b. It remembers the farmer (P4's history rules)
- Same crop and problem again → "Is this the same problem you told us about before?" (H1)
- Said the input wasn't available or was too costly → ask about that directly next time (H2)
- Ignored recent surveys → shorter survey (H3) · light user → at most 2 questions (H4)
- Changes 1,343 of 2,616 surveys. Trade-off, shown with numbers: P4's relevance score 0.69 → 0.73, answer-key
  wording match 0.99 → 0.93. On in the app, off for the headline scores. Only earlier data is used.

## 7. When the answer is bad, a person follows up
- "It didn't work", "my animal is worse", "couldn't reach the vet" → a ticket for FarmerChat staff, with a
  suggested next step.
- Digital Green listed this as a stretch goal. It works today (Follow-up queue tab).

## 8. How this runs on AWS
| Piece | Status |
|---|---|
| Amazon Bedrock AgentCore: the agent (Evidence → Analyst → Verifier → Synthesizer) | **Live** in us-west-2 (`fasal_pulse`); 1 survey in 2 languages ≈ 4 s, $0.004 |
| Amazon Bedrock: Claude Haiku 4.5 writes, Gemma 3 12B judges, Guardrails block personal questions | **Built**: full run 2,616 surveys, $2.61 with the compact writer (P4's safety checks on every draft, no guardrail on that account; the first run, guardrail on, cost $11.06), 97% model-written, judge 4.9/5, 0 broken files |
| S3 (results) + CloudWatch (dashboard `fasal-pulse-agent`) | From `infra/terraform/agent.tf` (Terraform) |
| REST API in a container, so it can move to Digital Green's EKS (P1) | **Built**: `POST /surveys`, `GET /surveys/due`, `/healthz` (FastAPI); Dockerfile runs it, built and smoke-tested in CI |
| ECS Express Mode: a web link to this demo | **Live** (`infra/terraform/ui.tf`) |
| EventBridge (send at 07:00, retry later), RDS PostgreSQL (weekly limit, opt-outs), Amazon Connect (voice calls) | **Not built**, production design only |

## 9. Close
- Asks only when there's something worth asking, in the farmer's language, at a sensible time.
- Every bad answer reaches a person.
- Open source: code, evaluation harness, README (repo link).

---

## Still to fill in before the deck is final
- [ ] Team names, repo link (slide 1, 9)
- [x] AI judge score and agreement with the 20 hand-scored surveys (slide 4)
- [x] REST API status at freeze (slide 8): built (container + infra/, not deployed). Bedrock + AgentCore: live (5 Nov full run).
- [ ] Any new rule changes: one slide each, numbers from the "Rules we changed" table
- [ ] Hindi review status (P4): say "pending native review" on slide 3 if not signed off
- [ ] Screenshots of each app tab for the backup (in case the live demo fails)
