# Product: MEL Survey Agent

Hackathon project for Digital Green (MEL = monitoring, evaluation, learning). Synthetic data only. No real delivery.

## What it does
1. Reads FarmerChat **insights** (one summarised farmer conversation each).
2. Decides **survey / no survey** with rules R1 to R8 (R1 junk, R2 critical needs a human call, R3 general information,
   R4 waiting for details, R5 no verification needed, R6 no usable window, R7 past harvest, R8 survey).
3. Writes 1 to 3 tap questions in hi-IN and en-IN.
4. Builds the scheduler **hand-off** (send window, channel order, priority, cap, expiry).
5. Renders per channel (app, web, WhatsApp, Telegram, voice) and simulates farmer answers.
6. Scored against a 150-row golden set (the answer key).

## Rules of the product
- Surveys never give new advice and never ask for personal information.
- Option labels are 20 characters or fewer. Hindi stays unescaped (`ensure_ascii=False`).
- A farmer gets at most one non-urgent survey per 7 days. STOP / opt-out means nothing after that.
- Survey decisions must not change by accident: the golden-set scores and the run counts are the regression check.

## Team (5 people)
P1 Data, Contracts & Integration · P2 Decision & Timing · P3 Scheduler, Channels & Simulator ·
P4 Survey Writing & Safety · P5 Evaluation & Demo. `docs/TEAM.md` is the source of truth.

## Open questions for Digital Green (P1 sends them)
09:00 vs 07:00 windows, critical cases as survey or human call, whether a new golden set is coming.
Draft: `docs/questions_for_digital_green.md`.
