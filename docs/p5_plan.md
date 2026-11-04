# P5 plan: Evaluation & Demo

Source of truth: the FINAL Team Contracts (4 Nov), which now include Digital Green's Vision and Technical
documents. Updated 4 Nov 2026 (evening).

## What P5 must deliver (FINAL contract)
- A scorecard covering Digital Green's five dimensions (relevance, timeliness, format, safety, speed), next
  to our decision and rule accuracy.
- Relevance scored by an **AI judge on Amazon Bedrock**, checked against 20 surveys the team scores by hand.
- A **run history**: every eval run saved, with a chart per dimension. At least one improvement shown.
- The 3-minute demo, including the simulated clock moving through the season. Slides, two clean-checkout
  rehearsals, a backup video.
- Bedrock is **required** for every model call (no longer optional). App Runner hosting stays optional.

## Where things stand (4 Nov, evening): FINAL contract checklist, P5 items
| Checklist item | Status | What finishes it |
|---|---|---|
| Overview + Survey Studio with phone preview | ✅ ticked | |
| H+4: post Scorecard fields; agree 3-part storyline | ⬜ drafted | **You:** post both in team chat, get an OK |
| H+12: confusion matrix + item similarity; scorecard in app; "Rules we changed" list | ✅ tick | |
| H+12: run history; chart per dimension; format/safety/speed defined | 🟡 | **P1:** call `mel.evaluation.run_eval()` from `mel.cli eval` |
| H+12 checkpoint: P5 → all: run history + five-dimension scorecard in the app | ✅ tick once `p5-full-data` merges | **You:** open the PR, P1 reviews |
| H+24: follow-up queue page; README numbers by script | 🟡 page ✅, README ✅ | **P3:** a persona that reports failure; **P1:** `late` in the response schema; then P5 switches the queue |
| H+24: AI judge on Bedrock vs 20 hand-scored surveys | ⬜ built + tested with a stand-in | **Team:** fill `docs/results/hand_scores.csv`; **P1:** Bedrock region/model/access + `boto3`; **you:** `--run`, `--calibrate` |
| H+36: every rule changed on purpose shown with its numbers | 🟡 README/app/script ✅ | **You:** one slide per change (R7 storage fix; send-time rule; P4 templates) |
| H+36: 3-minute script + slides; 2 clean-checkout rehearsals; backup video | 🟡 script ✅, slide text ✅ | **You:** build the deck, rehearse twice from a fresh clone, record the video |
| Done when: demo runs from a clean checkout following only the README | ⬜ | Rehearsal finds the gaps (note: `validate` needs `run --simulate` first) |
| Optional: hosted link | 🟡 P4's demo is live | **You + P4:** host our app next to theirs on Streamlit Cloud (backup link, not AWS) |

**Findings worth showing:**
- The answer-key send-time setting matches the key 100%, but only 26.5% of its send windows pass timeliness
  (1,982 would open before the farmer's action window ends). The brief rules pass 100%: keep the brief.
- Item similarity 0.99 comes from P4 copying the answer key's wording on purpose. It is an in-sample match, not
  independent proof of quality; the AI judge is the independent check.
- On the full data, the weekly limit holds back 1,002 of 2,616 surveys (moved, merged or skipped).

## Next steps, in order
1. Open the PR for `p5-full-data`; ask P1 to review. Restart Streamlit after it merges.
2. Post the Scorecard fields and the 3-part storyline in team chat (ticks H+4).
3. Send `docs/results/hand_scores.csv` + `hand_scoring_guide.md` to the team (unblocks the judge box).
4. Chase P1: Bedrock access (region, model id), `boto3`, `run_eval` in `mel.cli eval`, `late` in the schema,
   weekly limit in `mel.cli run`.
5. ✅ Decided 4 Nov: one demo (P4's folded into the team app), name "Fasal Pulse - MEL Survey Agent", H1–H4 moved into
   `mel/writer/history.py` (on in the app, off for scoring; run 6–7 shows the trade-off). P4 reviews the PR.
6. Host our app on Streamlit Cloud next to P4's; add links between the two.
7. When Bedrock works: switch the judge to P4's `ModelClient`, run `--run` and `--calibrate`, record a run.
8. Build the slide deck from `docs/slides_draft.md` (one slide per changed rule).
9. Clean-checkout rehearsal ×2 following only the README; record the backup video.
10. Freeze with P1 (H+36): tag the release; only bug fixes after.

## How to record an improvement
```
python scripts/readme_numbers.py --write --record "what changed"
```
Add `--basis brief` or `--basis answer_key` to record only one send-time rule. Commit the README,
`docs/results/scorecard.md` and `docs/results/eval_history.jsonl` together with the change.
