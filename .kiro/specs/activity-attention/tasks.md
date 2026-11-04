# Tasks: Activity attention

Phase 2 only (Phase 1 is these three spec files + `docs/activity_attention_request.md`). P1-owned tasks are
done directly; cross-owner tasks (marked ⇒owner) are the exact changes written up in
`docs/activity_attention_request.md` and are applied only with that owner's OK.

## P1 — the module, wiring, CLI, config (owned)
- [ ] 1. `config/activity_attention.json` with the thresholds/windows/weights from the design (R-1.3). Confirm
      it sits outside `config/rules/` and `config/schemas/` so `parity` ignores it (R-11.1).
- [ ] 2. `mel/data/activity.py`: `Attention` dataclass + `ActivityHistory` (distinct-conversation counts,
      junk filter via `why_junk`, dataset_start, no-leakage cutoff) and `attention_for(insight)` (R-1, R-2).
- [ ] 3. Metrics: `baseline_per_week` over 70→14 days using only the covered span; `recent_count` over the last
      14 days including the current conversation; `high_weight` by **reusing** `handoff.priority()` (R-2).
- [ ] 4. Poisson tail helper and the six-tier first-match cascade with reasons and the one-sentence
      explanation; `weight` 1.5 / 1.0 / 0.5 (R-3, R-4.2, R-4.3).
- [ ] 5. `run_pipeline(..., attention=False)` builds one `ActivityHistory` from the **unfiltered** insights and
      passes `attention_for(insight)` into `run_insight`; `run_insight(..., attention=None)` attaches it to the
      Decision (R-7.1, R-8). Default path byte-for-byte unchanged (R-7.2).
- [ ] 6. CLI `run --attention` (default off) → `run_pipeline(attention=...)`; `run_summary.json` gains
      `by_tier` and `by_reason` (always present, zero when off) (R-7.1, R-9.4).
- [ ] 7. The once-per-7-days `activity_jump→high` budget (`HighPromotionBudget`) applied in send order where the
      cap is admitted, downgrading a second `activity_jump→high` within 7 days to `normal`; `quiet_then_high_weight`
      and brief-high are exempt (R-6.2).
- [ ] 8. `scripts/activity_report.py`: full-pack run off vs on + scorecard + golden, writing
      `docs/results/activity_attention.md` and a JSON for the Evaluation tab (R-10).

## P2 — Decision & timing ⇒P2 (request doc)
- [ ] 9. Add `attention: dict | None = None` to the `Decision` dataclass (R-4.1). (Interim: P1 sets it
      dynamically; this makes it first-class.)
- [ ] 10. `pick_send_time(..., attention=None)`: `surge` ⇒ window opening, rule `attention_surge`, above
      `advice_evening`/`usual_time`, never before `not_before`; others unchanged (R-5.2, R-5.3).

## P3 — scheduler ⇒P3 (request doc)
- [ ] 11. `build_handoff(insight, survey, attention=None)` + `adjust_priority(brief_prio, insight, attention)`:
      surge one step up, steady_high `normal→low` only (never demote brief-high), neutral unchanged; `exempt`,
      waits and channel order follow the final priority (R-5.1, R-6.1).

## P4 — survey writing ⇒P4 (request doc)
- [ ] 12. Thread `attention` (tier) into `write_surveys → compose_survey → template_items/_try_model` and
      `history.personalize`: surge skips the H4 light-user clamp (up to 3); steady_high clamps to ≤2;
      `question_count(..., attention)` applies the steady_high cap on the LLM path too; the 1–3 schema cap and
      real item count still bound "up to 3" (R-5, R-6.4, R-6.5, R-6.6).

## P5 — app & evaluation ⇒P5 (request doc)
- [ ] 13. App runs `run_pipeline(attention=True)`; "Highlighted farmers" list sorted by weight then recency
      with the explanation sentence (R-9.1).
- [ ] 14. Survey Studio shows tier + reason; add a made-up-history attention demo beside the "pretend survey
      history" demo (R-9.2, R-9.5).
- [ ] 15. Follow-up queue sorted by weight first (R-9.3); Evaluation tab shows the before/after block naming the
      representative's request (R-10.3).

## Tests & proof
- [ ] 16. `tests/test_activity.py` (hand-built farmers) covering every case in R-12, including the once-in-7-days
      high budget, opted-out/fatigued surge still blocked/shortened, and filtered-vs-full agreement.
- [ ] 17. Full-pack proof: decision & rule identical on/off for all 6,999 (R-11.3); outputs identical with
      attention off (R-7.2); all hand-offs schema-valid with attention on (R-11.2).
- [ ] 18. Run and record: `pytest -q`, `python -m mel.cli run --simulate --clean`, `validate`, `eval`, `parity`
      (set `MEL_OUT_DIR` outside OneDrive on Windows). Regenerate the report and the Evaluation JSON.
- [ ] 19. Docs/admin: update `CLAUDE.md` status; add `mel/data/activity.py`, `config/activity_attention.json`,
      `scripts/activity_report.py`, `tests/test_activity.py`, `docs/results/activity_attention.md` to
      `.github/CODEOWNERS` and `docs/TEAM.md`.
