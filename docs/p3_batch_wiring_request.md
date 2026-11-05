# Request to P1: run the batch through P3's scheduler

From: P3 (Scheduler, Channels & Simulator)
To: P1 (owner of `mel/cli.py`)
Status: **proposed, not applied.** P3 has not edited `cli.py` or `pipeline.py`. Updated 5 Nov.

## Why
`python -m mel.cli run` writes and simulates every hand-off the pipeline makes. It does not apply
the weekly limit, opt-outs or the survey quality gate, so the CLI output breaks the brief:

| full pack (6,999 insights) | today's `run` | with `run_batch` (threshold 0.5 stand-in) |
|---|---|---|
| hand-offs written | 2,616 | 1,688 (1,372 sent + 316 moved) |
| merged into an earlier survey | 0 | 324 |
| skipped (weekly limit) | 0 | 52 |
| rejected by the quality gate | 0 | 552 (all relevance below 0.5) |
| non-high surveys under 7 days apart to one farmer | many | 0 (independent audit) |

P3's side is done and tested: `mel.schedule.run_batch` (opt-out → quality gate → cap, in send
order, simulated channel fallback, opt-outs fed back). Rule counts R1-R8 do not change; the
number of hand-off, survey and response files does, which `docs/TEAM.md` asks to explain in the PR.

## The change to `cmd_run` (replaces the loop over `result.outputs`)
```python
    from mel.schedule import run_batch, FrequencyScheduler
    from mel.channels import FarmerReachability
    result = run_pipeline(insights, limit=a.limit, farmer=a.farmer, farmers=farmers)
    by_handoff = {}
    for ins, out in zip(result.insights, result.outputs):
        if "no_survey" in out:
            _dump(OUT / "no_survey" / f"{ins.get('insight_id','unknown')}.json", out["no_survey"])
        else:
            by_handoff[out["handoff"]["handoff_id"]] = out
    batch = run_batch([o["handoff"] for o in by_handoff.values()],
                      relevance_threshold=RELEVANCE_THRESHOLD,   # P4's published value
                      simulate=a.simulate, reachability=FarmerReachability(farmers),
                      ranker=FrequencyScheduler.from_insights(insights))
    for h in batch.handoffs_to_send:                      # sent + moved; merged ride on the host
        ids = h["survey"]["source_insight_ids"]
        for lang, s in by_handoff[h["handoff_id"]]["surveys"].items():
            _dump(OUT / "surveys" / f"{s['survey_id']}.{lang}.json", {**clean(s), "source_insight_ids": ids,
                                                                      "send_window": h["send_window"]})
        _dump(OUT / "handoffs" / f"{h['handoff_id']}.json", h)
    for r in batch.responses:
        _dump(OUT / "responses" / f"{r['response_key']}.json", r)
```
and add to `summary` (before `_dump(OUT / "run_summary.json", summary)`):
```python
        "schedule": batch.counts,   # sent/moved/merged/skipped/opted_out/rejected/duplicates/prevented/cap_violations
```
Notes:
- `surveys` in `summary` stays "hand-offs the pipeline planned"; `schedule.sent + schedule.moved`
  is how many go out. P5's "cap violations" should read `schedule.cap_violations`
  (prevented surveys are `schedule.prevented`, not violations).
- A moved hand-off's survey files get the moved `send_window`, so survey and hand-off agree.
- `--simulate` now walks each hand-off's channels (fallback, waits, send hours) instead of one
  `completed` record on the first channel, so there can be several response files per hand-off.
- P3 checked this patch in a scratch copy of the repo: `run --simulate --clean` then `validate`
  gives 0 invalid files on the mock data and the full pack.

## Blocked on P4
`RELEVANCE_THRESHOLD` must be P4's published value. P4 has not published one; the app uses a
provisional 0.5 (`SEASON_THRESHOLD`). Until P4 does, P1 can pass the same provisional 0.5 and
label it as such in `run_summary.json`.
