# P5 plan: Evaluation & Demo

Source of truth: the signed Team Contracts (P5 section). This file also folds in what Digital Green's
**Technical** and **Vision** documents say judges will look for. Updated 3 Nov 2026.

## What Digital Green's documents add
- "Evaluation is the center of this project, not an afterthought." Quality and timing beat infrastructure.
- **Hill-climb:** run, score, change something, rerun, show the trend. Their "done" list needs at least one
  improvement round shown.
- **Five things to score:** relevance, timeliness, format, safety, speed (time per survey and per batch).
- **Their three user stories** (farmer gets a follow-up · MEL team checks quality · bad answer gets followed
  up) are the three parts of our 3-minute demo.

## Where the contract and Digital Green's documents differ
| Topic | Contract | Digital Green | What we do |
|---|---|---|---|
| Bedrock / AWS | Optional, first thing to cut | Bedrock "required" for AI models | Templates stay the core; **P1 + P4 decide**, not P5 |
| Scorecard fields | decision, rule, window, item similarity, confusion | relevance, timeliness, format, safety, speed | P5 owns the fields: add format, safety, speed (done) |
| Improvement shown | "Rules we changed" list, before → after | Trend across runs | Run history feeds both (done) |
| AI judge for relevance | Not in contract; relevance score is P4's | Suggested | Extra only, after core targets, with P4 |

**Correction for P2:** the contract says R7 misses are "R7 says survey when the key says no". It's the other
way round. We say *no survey* (crop harvested) and the key says *survey*. All 6 are potato or cauliflower in
post-harvest storage, so the fix makes R7 let stored crops through.

## Tasks
**H+4**
- [ ] Post Scorecard fields (contract fields + format pass, safety pass, failing-but-scheduled, ms per insight)
- [ ] Settle `score_golden` signature (`docs/h4_interface_decisions.md`; recommendation: keep)
- [ ] Agree the 3-part storyline with the team (`docs/demo_script.md`)

**H+12**
- [x] Per-rule confusion matrix and item similarity in `score_golden`
- [x] Scorecard in the app: format, safety, gate, relevance, speed over all 6,999 insights (`mel/evaluation/scorecard.py`)
- [x] Run history + trend chart (`mel/evaluation/history.py`, `docs/results/eval_history.jsonl`); run 1 = baseline
- [ ] "Rules we changed" entries as P2/P3 changes land: record a run per change

**H+24**
- [x] Follow-up queue page
- [ ] Switch the queue to P3's `simulate(handoff, persona, seed)` outcomes, late answers included, when they land
- [x] README numbers written by script, never typed (`python scripts/readme_numbers.py --write`)
- [x] Offline scorecard for stage failures (`docs/results/scorecard.md`)

**H+36**
- [x] 3-minute script in 3 parts (`docs/demo_script.md`)
- [ ] Slides: one per changed rule with its numbers; "How this would run on AWS" marked not built
- [ ] Two rehearsals from a clean checkout following only the README; backup video
- [ ] Optional, last: App Runner hosting with P1

## Inputs P5 is waiting on
| From | What | For |
|---|---|---|
| P1 | `run_pipeline()`; the 3 Digital Green answers | eval entry point; window story |
| P2 | R7 storage fix; 09:00 setting; final table | run history entries; changed-rule slides |
| P3 | cap / opt-out / skip-move-merge counts; outcomes with `late` | follow-up queue; scorecard |
| P4 | templates-vs-Claude table; better relevance score; Hindi sign-off | relevance number; "pending review" label |

## How to record an improvement
```
python scripts/readme_numbers.py --write --record "R7 storage exception"
```
Commit the README, `docs/results/scorecard.md` and `docs/results/eval_history.jsonl` together with the change.
