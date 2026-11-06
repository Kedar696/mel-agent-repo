# Frequency-aware survey scheduling (P3)

Owner: P3 (Scheduler, Channels & Simulator). Code: `mel/schedule/frequency.py`,
config `mel/schedule/frequency_config.json`, tests `tests/test_frequency.py`.

## What it does
Watches how often farmers ask questions, compares that with a survey's **existing** priority
and eligibility, and ranks/times eligible survey hand-offs so that surveys on topics a farmer
is actively asking about surface first — without weakening any existing protection.

It stays inside P3's lane: it schedules, it does not write surveys (P4), does not change the
decision/timing rules (P2), and does not alter the pipeline (P1). It reads only existing
insight fields (ids, timestamps, crop, concern) and the existing crop calendar.

## Pieces
| Class | Role |
|---|---|
| `FrequencyMonitor` | groups question history by `(farmer_id, topic)`, computes that pair's own baseline over a rolling window, flags a `FrequencyPeak` when recent volume runs above baseline |
| `SeasonStageContext` | reads P2's crop calendar (read-only) to label a crop's growth stage for a date |
| `ClimateContext` | pluggable regional-climate signal; **neutral fallback** because no climate data ships here |
| `FrequencyScheduler` | ranks **eligible** hand-offs from the peak + existing priority + season stage + (optional) climate, and explains each result |

## How a peak is defined (transparent, configurable)
Per `(farmer, topic)`, where topic = crop (`asset.name`) or, if unnamed, `concern`:
- Count questions in the last `window.rolling_days` (default 14).
- Baseline = that pair's own mean questions per window across its history (self-relative).
- A **peak** needs the window count ≥ `baseline × baseline.peak_ratio` (default 1.5) **and**
  ≥ `baseline.min_peak_count` (default 3), with ≥ `window.min_history` (default 2) questions.

Unrelated topics and other farmers never share a bucket, so one farmer's wheat surge cannot
flag their livestock, and vice versa. Duplicate `insight_id`s are counted once; out-of-order
timestamps are sorted; sparse history yields no peak. No free text is read or logged — only
ids, timestamps, crop and concern.

## How ranking combines signals (no buried constants)
Score for an **already-eligible** hand-off (`ranking` block in the config):
```
score = priority_base[priority]                      # existing priority, unchanged
      + frequency_weight  * peak.strength            # only when a peak is detected
      + season_stage_weight (if crop is in a stage)
      + climate_weight    * climate_factor           # only when real/synthetic climate supplied
```
Every weight and the priority base live in `frequency_config.json` with a `_doc` note; none
are hard-coded. Each `RankedHandoff.signals` explains its score: the peak details, the
priority used, the season stage, and the climate state (available / synthetic / missing).

## Protections are never bypassed
A frequency peak only reorders surveys that are **already allowed**. `FrequencyScheduler.rank`
accepts eligible hand-offs only; `filter_eligible()` enforces, by calling the existing code
(it does not re-implement it):
- **opt-out** (`OptOutList.blocks`) — always wins;
- **quality gate** (`broadcast.quality_failures`) — invalid/low-relevance survey dropped;
- **send window / expiry** — dropped if the clock is before `not_before` or after `expires_at`;
- **frequency cap** (`CapLedger.admit`) — a capped survey stays `skipped`/`opted_out`; a peak
  cannot force it through. When the cap `moves`/`merges`, the cap's resulting hand-off is what
  gets ranked, so the cap stays authoritative.

Tested in `tests/test_frequency.py`: `test_peak_does_not_bypass_opt_out`,
`..._quality_gate`, `..._window_or_expiry`, `..._frequency_cap`.

## Climate: what is and is not here
This repo ships **no climate/weather dataset or loader** (confirmed: the only `weather`/
`climate` references are the `weather_climate` *concern* label and survey text). So:
- Default `ClimateContext` is **unavailable**: `factor()` returns `None`, the climate
  component is `0.0`, and every result carries `climate_context_missing: true`.
- A **demo** may inject a constant via `ClimateContext(synthetic_factor=…)` or
  `frequency_config.json → climate.synthetic_demo_factor`; results then report
  `climate_synthetic: true` so it is never mistaken for real data.
- No weather is invented and no real-time climate awareness is claimed.

### Input contract to add real regional climate (needed from P1/P2)
To make climate a real signal, provide a loader/provider:
```
provider(state: str, district: str, on: datetime.date) -> float | None
```
returning a **stress factor in [0,1]** (higher = more climate stress, so timely follow-up is
more useful), or `None` when there is no reading for that place/date. Wire it in with
`ClimateContext(provider=...)`. Suggested source shape (for P1 to supply as project data): a
CSV/table keyed by `state, district, date` with a normalised stress column. Until that exists,
the neutral fallback above applies.

## Data this feature needs from other owners
- **P1 (data):** question history is just the existing insights (`load_insights`) — already
  available; the monitor reads `farmer_id`, `created_at`, `asset.name`, `concern`. For climate,
  P1 would add the provider/table in the contract above. No schema change is required for the
  monitor itself.
- **P2 (timing/calendar):** the season-stage signal reuses `load_crop_calendar` read-only; no
  change to P2's R7 / window rules. If P2 later exposes a direct "stage for crop+date" helper,
  `SeasonStageContext` can delegate to it.
- **P4 (writer):** the quality gate reads the `self_eval` block P4 already writes; no change.

## Assumptions
- "Question frequency" = insights per `(farmer, topic)` over a rolling fortnight; this matches
  the available data (one insight per summarised conversation) and the project's weekly cadence.
- Baseline is self-relative (per farmer+topic), so a naturally chatty farmer is not falsely
  flagged; a peak means a change against that pair's own normal.
- `as_of` defaults to the latest event in the supplied history (data-driven, never the wall
  clock), keeping results deterministic and reproducible.
