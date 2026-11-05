# Demo script: Fasal Pulse - MEL Survey Agent (3 minutes, 3 parts)

Owner: P5 (Evaluation & Demo). The **Say** lines are written for judges, most of whom aren't engineers.
Speak them in your own words; don't read them out.

The three parts follow Digital Green's own three user stories (vision document, "MVP User Journeys"). The app
opens on **Dashboard**; the demo starts on the second tab:
1. A farmer gets a follow-up about her own advice → **Survey demo** (second tab)
2. The MEL team checks quality before trusting the agent → **Dashboard** (first tab), Evaluation section
   (the main part)
3. A negative answer triggers follow-up → **Follow-up queue** (fourth tab)

Optional, if there is time or a judge asks: the **Season** tab (third tab) runs the simulated clock from
November to March (Part 2b).

The Overview section at the top of the Dashboard is a **backup screen** for questions only. Its numbers count up
the first time they come into view, so open the Dashboard once before you start.

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
- The app loads all 6,999 conversations (about 25 seconds the first time). Click through all three tabs
  once, so the Evaluation section (it checks all 6,999 insights) is already loaded.
- Then open **Survey demo**. The "Demo picks" list starts on **High — Goat veterinary follow-up**
  (I-001253); Medium (lentil), Low (stored mustard) and the no-survey edge case (critical cow) are in the same list,
  above Browse all conversations. The phone in the centre must be on its first
  question: if a rehearsal left it part-way, press the **restart icon** (↻, tooltip "Restart survey") in the settings bar (it keeps the
  case, channel and language) or reload the page.
- **Add your own insight** (the green button at the top right of Survey demo) opens the editor: type a
  farmer's question and the advice, open Details to change the crop, problem, severity, advice type, timing,
  channel, language (English unless changed) or district, and press **Preview the survey**. The editor folds
  away and the report below is titled **Your insight**; **Edit insight** reopens it with everything kept,
  **Hide editor** folds it again, and **Back to the demos** returns to the goat case while **Your insight**
  brings the report back. No model reads the text (the local demo runs without one), nothing typed joins the
  numbers in the Dashboard. Leave the advice empty to show the no-survey rule. The line beside the
  button says which crop, problem, severity and advice type the survey is built for. Dates use the real clock
  on the rabi 2026-27 calendar (send windows before 03/31/2027 India time); the screen shows every time in
  Eastern Time (EST/EDT), MM/DD/YYYY, 12-hour.
- Have the slides open in another window, and the backup video ready.
- **Hindi:** if P4's native-speaker review hasn't signed off, say "Hindi pending native review" once in part 1.

---

## Opening (15 seconds)

**Say:**
> FarmerChat gives farmers advice. Digital Green wants to know: did the farmer act on it, and did it work?
> Our agent reads each conversation, decides whether a short follow-up is worth sending, writes it in
> Hindi and English, and plans when and how to send it. Three quick stories.

## Part 1. A farmer gets a follow-up about her own advice (50 seconds)

**Screen:** Survey demo, demo pick "High — Goat veterinary follow-up" (I-001253). The settings bar starts on Channel **App**
(her first channel) and Language **English**, so the judges can read along; switch Language to **Hindi** to
show her own copy (each language keeps its own taps; the **restart icon** in the settings bar clears the current one).

**Say, pointing left to right:**
> **[green card, left]** A farmer asked about her goat; FarmerChat told her to call the vet.
> **[What the agent remembers]** The agent remembers her: the same problem came up before.
> **[phone, centre]** So this is what she gets, one question at a time: *"Did you meet the veterinary
> doctor?"* **[tap "Could not reach" / मिल नहीं पाए]** Her answer appears, then the next question:
> *"Did their advice help?"* **[tap "Not met yet" / अभी मिले नहीं]** And because it remembers her:
> *"Is this the same problem you told us about before?"* **[tap "Yes, same problem" / हाँ, वही समस्या]**
> Three taps, no typing.
> **[right column, Survey checks]** Before anything goes out, automatic checks confirm: no new advice, no
> personal questions, short buttons. **[Scheduler hand-off]** It's urgent, so it goes first: 28 to 30
> November, between 7 am and 7 pm India time (the screen shows those moments in Eastern Time), app first,
> then WhatsApp, then a call.
> **[Answer record, "Requires follow-up"]** She couldn't reach the vet and it's the same problem, so this
> answer needs a person. That's part 3.
> **[optional, if time: Channel → WhatsApp]** The same survey on WhatsApp opens with an approved
> invitation: she taps Start, then answers with buttons.

## Part 2. The MEL team checks quality (80 seconds)

**Screen:** Dashboard, scrolled down to **Evaluation**, with Send-time rule "Brief rules
(default)" selected.

**Say, top to bottom:**
> **[Answer key]** Digital Green gave us an answer key of 150 cases. We agree on *whether* to survey
> **99.3%** of the time, and pick the right first channel **every** time.
>
> **[Every survey we write]** Then we ran all **6,999** conversations: about 2,600 surveys, over 5,000 files
> in two languages. **100%** are in the right format, **100%** pass the safety checks, **100%** go out at
> a sensible time, and it takes under 4 milliseconds per survey: about 10 seconds for the whole season.
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
Generated from the run history; the same table is in the README and in the Evaluation section (Run
history → Rules we changed). As of 4 Nov:

| Run | Change (owner) | Decision | Window match | Timeliness | Misses |
|---|---|---|---|---|---|
| 2 | R7 storage exception: stored crops still get a survey (P2) | 96.0% → 99.3% | 0% | 100% | 6 → 1 |
| 3 | Answer-key send-time setting, off by default (P2) | 99.3% → 100% | 0% → 100% | 100% → 26.5% | 1 → 0 |

The last miss under the brief rules is G-0145: the answer key accepts a one-day window on 31 March; the
brief needs two days. Record each new change with
`python scripts/readme_numbers.py --write --record "what changed"` and add a row here.

## Part 2b (optional). The season on a simulated clock (20 seconds)

**Screen:** Season (third tab). Leave "How farmers respond" on *Responsive* and press **+1 week** once, then
**To end of March**. To show failures, pick *Never answers* or *Opts out on the first message* and press
**To end of March** again (changing it restarts the season).

**Say:**
> Digital Green asked to see the scheduler run on a simulated clock. One clock drives both the scheduler and
> the broadcaster: a week at a time, or the whole season in a few seconds. The weekly limit, opt-outs and the
> quality check all apply: surveys below the relevance bar are blocked, never sent.

## Part 3. A bad answer gets followed up (30 seconds)

**Screen:** Follow-up queue (fourth tab). Pick a reason at the top if you like (each shows its count), then
pick a farmer with the circle at the start of a row: the ticket beside the list shows the next step and the
conversation log (what she asked, the advice, then each survey question and her answer, the flagged one
marked). The tickets are simulated from each survey's trouble answer; the taps from part 1 are not added
here, so don't look for her ticket.

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
  out for good. Non-urgent surveys are capped at one per farmer per week. *(Show it in the phone: on App
  or Web tap "Do not ask me again"; on WhatsApp or Telegram type STOP or /stop in the message bar; on Voice
  tap "9 · No more calls" during the greeting. The answer record shows Declined and `farmer_opted_out`.
  the restart icon in the settings bar resets it.)*
- **How many get a survey?** *(Dashboard, Overview section.)* Of 6,999 conversations, about 2,600 get a survey; the rest
  don't, each with a written reason: broken record, general information, still asking for details, or a
  critical case where a person should call instead *(demo pick "Edge case — No survey (critical cow)")*.
- **Do farmers get bombarded?** *(Dashboard, "Weekly limit" number.)* At most one non-urgent survey per farmer per
  week: about 1,000 surveys are moved to a later date, merged into the farmer's other survey, or skipped.
- **Why 0% window match by default?** The brief and the answer key disagree on send times. The answer-key
  setting scores 100% but asks 3 in 4 farmers before they could act, so the brief stays the default until
  Digital Green confirms. *(Switch Send-time rule in the Evaluation section to show both.)*
- **How fast is it?** Under 4 ms per survey; all 6,999 conversations in about 10 seconds.
- **Can the season be fast-forwarded?** Yes: the Season tab. One shared simulated clock (P3's
  `SeasonScheduler`) moves a day, a week or to 31 March; "Send next step" is the manual trigger, one channel
  attempt at a time. The relevance bar there (0.5) is provisional until P4 and P5 agree it.

## If something breaks

- **App shows an ImportError after a `git pull`:** a Streamlit server started before the pull still has the
  old code loaded. Stop it (`Ctrl+C`, or `pkill -f "streamlit run"`) and start it again.
- **App won't start:** open `docs/results/scorecard.md` (offline scorecard, same numbers), then play the
  backup video.
- **The phone is stuck part-way from a rehearsal:** press the **restart icon** in the settings bar, or reload the page.
- **The Answer key caption says "Mock subset" instead of "Full pack":** the folder
  `mel-survey-agent-participant-pack/participant-pack/` is missing, so the app fell back to the mock sample.
  Use the offline scorecard.
- **A number differs from this script:** trust the screen; it's computed live.
- **Anything after the freeze:** roll back to the freeze tag. Don't debug on stage.
