# Demo script: Fasal Pulse - MEL Survey Agent (3 minutes, 3 parts)

Owner: P5 (Evaluation & Demo). The **Say** lines are written for judges, most of whom aren't engineers.
Speak them in your own words; don't read them out.

The three parts follow Digital Green's own three user stories (vision document, "MVP User Journeys"):
1. A farmer gets a follow-up about her own advice → **Survey Studio**
2. The MEL team checks quality before trusting the agent → **Evaluation** (the main part)
3. A negative answer triggers follow-up → **Follow-up queue**

Overview and Simulate answers are **backup screens** for questions only.

Numbers below were last generated on **4 Nov 2026**. Before every rehearsal, run the check below; the
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
- The app loads all 6,999 conversations (about 25 seconds the first time). In **Survey Studio**, the
  "Demo picks" list starts on **Goat → vet** (I-001253); the stored-potato and critical-cow cases are in the same list.
- Have the slides open in another window, and the backup video ready.
- **Hindi:** if P4's native-speaker review hasn't signed off, say "Hindi pending native review" once in part 1.

---

## Opening (15 seconds)

**Say:**
> FarmerChat gives farmers advice. Digital Green wants to know: did the farmer act on it, and did it work?
> Our agent reads each conversation, decides whether a short follow-up is worth sending, writes it in
> Hindi and English, and plans when and how to send it. Three quick stories.

## Part 1. A farmer gets a follow-up about her own advice (50 seconds)

**Screen:** Survey Studio, demo pick "Goat → vet" (I-001253).

**Say, pointing left to right:**
> A farmer asked about her goat; FarmerChat told her to call the vet. So we ask exactly that:
> *"Did an expert see your goat?"* and *"How is your goat now?"*, one tap each, in Hindi and English.
> **[ticks]** Before anything goes out, automatic checks confirm: no new advice, no personal questions,
> short buttons. **[point at "What the agent remembers"]** It also remembers this farmer: the same problem came
> up before, so it adds "Is this the same problem you told us about before?" **[click App → WhatsApp → Voice]** The same survey as the app, WhatsApp, or a phone call.
> **[hand-off strip]** It's urgent, so it goes first: 28 to 30 November, between 7 am and 7 pm, app first,
> then WhatsApp, then a call.
> **[optional, if time: "Answer as the farmer" → tap "Worse"]** And if the farmer says it got worse, it
> goes straight to the Follow-up queue.

## Part 2. The MEL team checks quality (80 seconds)

**Screen:** Evaluation, with "Brief rules (default)" selected.

**Say, top to bottom:**
> **[Answer key]** Digital Green gave us an answer key of 150 cases. We agree on *whether* to survey
> **99.3%** of the time, and pick the right first channel **every** time.
>
> **[Every survey we write]** Then we ran all **6,999** conversations: about 2,600 surveys, over 5,000 files
> in two languages. **100%** are in the right format, **100%** pass the safety checks, **100%** go out at
> a sensible time, and it takes about 2 milliseconds per survey: 6 seconds for the whole season.
>
> **[Run history → Rules we changed]** This is how we got here. We started at 96%. All 6 mistakes were
> potatoes already dug up and in storage: we said "harvested, nothing to ask", but stored potatoes can
> still rot. We fixed that one rule and went to **99.3%**.
>
> **[Brief rules vs answer-key setting]** One real disagreement in Digital Green's own material: *when*
> to send. Their brief says after the farmer's deadline to act; their answer key often says earlier.
> We built both. The answer-key setting matches the key **100%**, but it would ask **3 out of 4**
> farmers before they could have acted on the advice. So we keep the brief as the default and have asked
> Digital Green to confirm.

**Rules we changed on purpose** (contract: every one shown with its numbers, one slide each).
Generated from the run history; the same table is in the README and the Evaluation tab. As of 4 Nov:

| Run | Change (owner) | Decision | Window match | Timeliness | Misses |
|---|---|---|---|---|---|
| 2 | R7 storage exception: stored crops still get a survey (P2) | 96.0% → 99.3% | 0% | 100% | 6 → 1 |
| 3 | Answer-key send-time setting, off by default (P2) | 99.3% → 100% | 0% → 100% | 100% → 26.5% | 1 → 0 |

The last miss under the brief rules is G-0145: the answer key accepts a one-day window on 31 March; the
brief needs two days. Record each new change with
`python scripts/readme_numbers.py --write --record "what changed"` and add a row here.

## Part 3. A bad answer gets followed up (30 seconds)

**Screen:** Follow-up queue. Open one ticket.

**Say:**
> When a farmer answers "it didn't work" or "my animal is worse", that doesn't just sit in a spreadsheet.
> It becomes a ticket for FarmerChat staff: who, what they were told, what they said, and a suggested next
> step. Digital Green listed this as a stretch goal; it works today.

## Close (10 seconds)

> We only ask when there's something worth asking, in the farmer's language, at the right time, and every
> bad answer gets a person's attention. Thank you.

(AWS slide: Bedrock (Amazon's AI service) is **built** and required by Digital Green; App Runner,
EventBridge, RDS and Amazon Connect are marked **not built**. Don't open any console on stage.)

---

## Likely questions (short answers)

- **Is this real farmer data?** No. It's synthetic data from Digital Green's pack. Nothing is actually sent.
- **Does it use AI to write the questions?** By default it uses checked templates: safe, free and
  repeatable. An AI option on Amazon Bedrock (P4) is being added; every AI-written survey goes through the
  same safety checks and falls back to a template if it fails. *(Update once P4's Bedrock path lands.)*
- **How do you stop it giving bad advice?** It never gives advice, only asks what happened. Checks block
  surveys that sound like advice or ask for personal information, and the scorecard proves 0 slipped through.
- **How do you know the checks work?** Tests feed in a survey that gives advice ("You should spray…") and one
  that asks for a phone number; both are caught.
- **What about farmers who don't want surveys?** STOP, /stop, pressing 9 or "do not ask me again" opts them
  out for good. Non-urgent surveys are capped at one per farmer per week. *(Show Simulate answers →
  `farmer_opted_out` if asked.)*
- **How many get a survey?** *(Show Overview.)* Of 6,999 conversations, about 2,600 get a survey; the rest
  don't, each with a written reason: broken record, general information, still asking for details, or a
  critical case where a person should call instead *(demo pick "Critical cow case")*.
- **Do farmers get bombarded?** *(Overview, weekly-limit number.)* At most one non-urgent survey per farmer per
  week: about 1,000 surveys are moved to a later date, merged into the farmer's other survey, or skipped.
- **Why 0% window match by default?** The brief and the answer key disagree on send times. The answer-key
  setting scores 100% but asks 3 in 4 farmers before they could act, so the brief stays the default until
  Digital Green confirms. *(Switch the Evaluation tab's send-time rule to show both.)*
- **How fast is it?** About 2 ms per survey; all 6,999 conversations in about 6 seconds.
- **Can the season be fast-forwarded?** *(Once P3's simulated clock lands: Season tab.)* Placeholder until then.

## If something breaks

- **App shows an ImportError after a `git pull`:** a Streamlit server started before the pull still has the
  old code loaded. Stop it (`Ctrl+C`, or `pkill -f "streamlit run"`) and start it again.
- **App won't start:** open `docs/results/scorecard.md` (offline scorecard, same numbers), then play the
  backup video.
- **Evaluation says "Full pack not found":** the folder `mel-survey-agent-participant-pack/participant-pack/`
  is missing. Use the offline scorecard.
- **A number differs from this script:** trust the screen; it's computed live.
- **Anything after the freeze:** roll back to the freeze tag. Don't debug on stage.
