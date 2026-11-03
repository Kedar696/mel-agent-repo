# Demo script: MEL Survey Agent (3 minutes, 3 parts)

Owner: P5 (Evaluation & Demo). The **Say** lines are written for judges, most of whom aren't engineers.
Speak them in your own words; don't read them out.

The three parts follow Digital Green's own three user stories (vision document, "MVP User Journeys"):
1. A farmer gets a follow-up about her own advice → **Survey Studio**
2. The MEL team checks quality before trusting the agent → **Evaluation** (the main part)
3. A negative answer triggers follow-up → **Follow-up queue**

Overview and Simulate answers are **backup screens** for questions only.

Numbers below were last generated on **3 Nov 2026**. Before every rehearsal, run the check below; the
README results section and `docs/results/scorecard.md` are regenerated from the same run. If the screen and
this script disagree, **trust the screen** and fix this file afterwards.

---

## Before you start (5 minutes before)

```
source .venv/bin/activate
pytest -q
python -m mel.cli validate
python scripts/readme_numbers.py --write
streamlit run app/streamlit_app.py
```

- Expect `pytest` all green and `invalid files: 0`. Then the Mock, Full and Batch lines print.
- Click through every tab once, so Evaluation (it checks all 6,999 insights) is already loaded.
- In **Survey Studio**, pre-select insight **I-001253** (goat · escalate_to_expert · survey).
- Have the slides open in another window, and the backup video ready.
- **Hindi:** if P4's native-speaker review hasn't signed off, say "Hindi pending native review" once in part 1.

---

## Opening (15 seconds)

**Say:**
> FarmerChat gives farmers advice. Digital Green wants to know: did the farmer act on it, and did it work?
> Our agent reads each conversation, decides whether a short follow-up is worth sending, writes it in
> Hindi and English, and plans when and how to send it. Three quick stories.

## Part 1. A farmer gets a follow-up about her own advice (50 seconds)

**Screen:** Survey Studio, insight I-001253.

**Say, pointing left to right:**
> A farmer asked about her goat; FarmerChat told her to call the vet. So we ask exactly that:
> *"Did an expert see your goat?"* and *"How is your goat now?"*, one tap each, in Hindi and English.
> **[ticks]** Before anything goes out, automatic checks confirm: no new advice, no personal questions,
> short buttons. **[click App → WhatsApp → Voice]** The same survey as the app, WhatsApp, or a phone call.
> **[hand-off strip]** It's urgent, so it goes first: 28 to 30 November, between 7 am and 7 pm, app first,
> then WhatsApp, then a call.

## Part 2. The MEL team checks quality (80 seconds)

**Screen:** Evaluation.

**Say, top to bottom:**
> **[golden scores, full pack]** Digital Green gave us an answer key of 150 cases. We agree on
> *whether* to survey **96%** of the time, and pick the right first channel **every** time.
>
> **[Every survey we write]** Then we ran all **6,999** conversations: 2,551 surveys, over 5,000 files in two
> languages. **100%** are in the right format, **100%** pass the safety checks, and it takes under a
> millisecond per farmer, so about 6 seconds for the whole season.
>
> **[Misses]** Where we disagree with the answer key, all 6 misses are the same case: potatoes already
> dug up and sitting in storage. We said "harvested, nothing to ask"; the key says "they can still rot,
> ask." **[Run history]** That's one specific rule, and this table tracks each fix and its score.
>
> **[Window 0%]** One honest zero: send timing. Digital Green's brief says 7 am; their answer key says
> 9 am. We followed the brief and asked them. It's a setting, not a rewrite.

**Rules we changed on purpose** (contract: every one shown with its numbers, one slide each).
As of 3 Nov **none**: the code follows the brief, and run 1 in the history is that baseline. When P2's
changes land, record a run for each (`--record "what changed"`) and fill in:

| Change (owner) | Why | Before (full pack) | After |
|---|---|---|---|
| Storage exception to R7 "already harvested" (P2) | All 6 misses are post-harvest storage | decision 96.0%, rule 96.0%, 6 misses | _fill in_ |
| Answer-key window (09:00) behind a setting; brief rule stays default (P2) | Brief and answer key disagree | window 0% | _fill in, setting on_ |

If neither has landed: *"We kept the brief's rules on purpose and showed exactly where the answer key
disagrees. Each one is a setting once Digital Green confirms."*

## Part 3. A bad answer gets followed up (30 seconds)

**Screen:** Follow-up queue. Open one ticket.

**Say:**
> When a farmer answers "it didn't work" or "my animal is worse", that doesn't just sit in a spreadsheet.
> It becomes a ticket for FarmerChat staff: who, what they were told, what they said, and a suggested next
> step. Digital Green listed this as a stretch goal; it works today.

## Close (10 seconds)

> We only ask when there's something worth asking, in the farmer's language, at the right time, and every
> bad answer gets a person's attention. Thank you.

(AWS: one slide only, "How this would run on AWS", marked **not built**. Don't open any console.)

---

## Likely questions (short answers)

- **Is this real farmer data?** No. It's synthetic data from Digital Green's pack. Nothing is actually sent.
- **Does it use AI to write the questions?** By default it uses checked templates: safe, free and
  repeatable. A Claude option exists, off by default; the same safety checks apply.
- **How do you stop it giving bad advice?** It never gives advice, only asks what happened. Checks block
  surveys that sound like advice or ask for personal information, and the scorecard proves 0 slipped through.
- **How do you know the checks work?** Tests feed in a survey that gives advice ("You should spray…") and one
  that asks for a phone number; both are caught.
- **What about farmers who don't want surveys?** STOP, /stop, pressing 9 or "do not ask me again" opts them
  out for good. Non-urgent surveys are capped at one per farmer per week. *(Show Simulate answers →
  `farmer_opted_out` if asked.)*
- **How many get a survey?** *(Show Overview.)* In the 57-conversation sample, 16 do; 41 don't, each with a
  written reason: broken record, general information, still asking for details, or a critical case where a
  person should call instead.
- **Why 0% on windows?** The brief and the answer key disagree; we followed the brief and asked Digital Green.

## If something breaks

- **App won't start:** open `docs/results/scorecard.md` (offline scorecard, same numbers), then play the
  backup video.
- **Evaluation says "Full pack not found":** the folder `mel-survey-agent-participant-pack/participant-pack/`
  is missing. Use the offline scorecard.
- **A number differs from this script:** trust the screen; it's computed live.
- **Anything after the freeze:** roll back to the freeze tag. Don't debug on stage.
