# Request to P1: wire OptOutList + CapLedger into the batch run

From: P3 (Scheduler, Channels & Simulator)
To: P1 (owner of `mel/cli.py` and `mel/pipeline.py`)
Status: **proposed, not applied.** P3 has not edited `cli.py` or `pipeline.py`.

## Why
The brief requires that an opted-out farmer receives no future surveys and that the 1-per-7-day
cap is enforced across the batch. `OptOutList` and `CapLedger.admit()` now implement both
(P3-owned, in `mel/schedule/handoff.py`), but the batch loop that actually sends/simulates lives
in P1's `cli.py`, so P3 cannot enable it there without coordination.

The pieces P3 provides and that this change calls are all public and tested:
- `mel.schedule.OptOutList` — `.record(response)`, `.blocks(handoff_or_farmer_id)`
- `mel.schedule.CapLedger` — `.admit(handoff, opt_out=None) -> Admit` (sent/moved/merged/skipped/opted_out)
- `mel.simulator.simulate(survey, channel, case, seed)` — unchanged signature

## Proposed change to `mel/cli.py` `cmd_run` (drop-in)
Process hand-offs in send order, gate each through the opt-out list and the cap, and only
simulate the ones actually sent/moved/merged. Opt-outs discovered during simulation feed back
into the list so later surveys to that farmer are blocked.

```python
def cmd_run(a):
    from mel.simulator import simulate
    from mel.schedule import CapLedger, OptOutList
    stats, admit_stats = Counter(), Counter()
    ledger, opt_out = CapLedger(), OptOutList()

    runs = [run_insight(ins) for ins in load_insights(Path(a.insights) if a.insights else None)]
    for out in runs:
        stats[out["decision"].rule] += 1
        if "no_survey" in out:
            _dump(OUT / "no_survey" / f"{out['no_survey']['insight_id']}.json", out["no_survey"])

    # Send order = by window open time, so the cap sees surveys in the order they'd go out.
    handoffs = sorted((o["handoff"] for o in runs if "handoff" in o),
                      key=lambda h: h["send_window"]["not_before"])
    for h in handoffs:
        admit = ledger.admit(h, opt_out=opt_out)
        admit_stats[admit.decision] += 1
        if admit.decision in ("opted_out", "skipped"):
            continue
        h = admit.handoff  # may be moved/merged
        for lang, s in {h["survey"]["language"]: h["survey"]}.items():
            _dump(OUT / "surveys" / f"{s['survey_id']}.{lang}.json", clean(s))
        _dump(OUT / "handoffs" / f"{h['handoff_id']}.json", h)
        if a.simulate:
            ch = h["channel_order"][0]["channel"]
            r = simulate(h["survey"], ch, "completed")
            opt_out.record(r)  # feed opt-outs back so later surveys are blocked
            _dump(OUT / "responses" / f"{r['response_key']}.json", r)
    print("decisions by rule:", dict(sorted(stats.items())),
          "| cap:", dict(sorted(admit_stats.items())), "->", OUT)
```

Notes:
- The survey files still come from `run_insight` (unchanged). The snippet above writes the
  farmer-language copy; if you prefer to keep writing both languages, loop `out["surveys"]`
  as today and only gate the hand-off/simulate through the ledger.
- No behaviour changes for P1's other commands (`eval`, `validate`).

## Alternative: a thin P3 helper, no cli.py edit
If you would rather not touch `cmd_run`, P3 can expose `mel.schedule.run_batch(handoffs,
simulate=False)` that returns the admit decisions and (optionally) records, and `cli.py`
calls that one function. Say which you prefer and P3 will land the helper on the P3 side.
