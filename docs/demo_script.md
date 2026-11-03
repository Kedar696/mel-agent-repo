# Demo script: MEL Survey Agent (judges' walkthrough)

Owner: P5 (Evaluation & Demo). Length: about 7 minutes plus questions.
Who it's for: the presenter. The **Say** lines are written for judges, most of whom aren't engineers.
Speak them in your own words; don't read them out.

Numbers last checked: **3 Nov 2026** (16 tests pass, 0 invalid files). Before the demo, run the check below
and update any number that has changed. Every number on screen comes from the pipeline, so if the script and
the screen disagree, **trust the screen** and fix this file afterwards.

---

## Before you start (5 minutes before)

```
source .venv/bin/activate
pytest -q
python -m mel.cli validate
python scripts/readme_numbers.py
streamlit run app/streamlit_app.py
```

- Expect: `16 passed`, `invalid files: 0`, then the Mock and Full lines from the table below.
- Open the app in the browser, zoom to about 110%, and click through all 5 tabs once. The first load of the
  Evaluation and Follow-up tabs takes a few seconds; doing it now means it's instant during the demo.
- In **Survey Studio**, pre-select insight **I-001253** (goat, sent to an expert) so you start on it.
- Have the slides open in a second window (for the AWS slide and the backup screenshots).

| Golden set | Rows | Decision | Rule | Channel | Window | Item similarity | Misses |
|---|---|---|---|---|---|---|---|
| Full pack (the real answer key) | 150 | 96.0% | 96.0% | 100% | 0% | 0.50 | 6 |
| Mock subset (what the app runs on) | 35 | 97.1% | 97.1% | 100% | 0% | 0.62 | 1 |

---

## 0. Opening, with the result first (45 seconds)

**Show:** the slide with the full-pack table above (or jump straight to the Evaluation tab).

**Say:**
> FarmerChat gives farmers advice. Digital Green wants to know: did the farmer act on it, and did it work?
> Our agent reads each conversation, decides whether a short follow-up survey is worth sending, writes it in
> Hindi and English, and plans when and how to send it.
>
> Digital Green gave us an answer key of 150 real-looking cases. On the yes-or-no question "should we
> survey this farmer?" we agree with the answer key **96% of the time**. We pick the right first channel
> (WhatsApp, app, phone call and so on) **every time**. I'll show you where we're wrong too, and why.

Keep it to that. Don't mention the window score yet; you'll explain it properly in section 5.

---

## 1. Overview tab: the whole batch at a glance (1 minute)

**Click:** Overview.

**Point at:** the row of six numbers, then the "Decisions by rule" bars.

**Say:**
> This is one run over 57 farmer conversations. **16 get a survey, 41 don't.** Saying no is a feature:
> we don't want to bother farmers when there's nothing useful to ask.
>
> The bars show *why*. The biggest "no" reason is broken or empty records (17). Others: the chat was just
> general information, FarmerChat was still asking for details, or the advice didn't need checking.
> One case was critical, a cow with cold stress, and there we say *don't send a survey, a person should call*.
>
> Every file we produce is checked against Digital Green's required format: 100% pass. 5 surveys are high
> priority, so they go out first. And we respect the rule of at most one survey per farmer per week.

**If asked "why only 16?":** the other 41 have a written reason each; open any of them in Survey Studio.

---

## 2. Survey Studio: one farmer, end to end (2 minutes)

This is the heart of the demo. Spend the most time here.

**Click:** Survey Studio. Insight **I-001253** (goat · escalate_to_expert · survey).

**Point at, left to right:**

1. **The green card (the conversation).**
   > A farmer asked about deworming their goat. FarmerChat said: call the nearest vet.
   > So the obvious question is: *did they reach the vet, and is the goat better?*
2. **The question cards (Hindi and English side by side).**
   > Two questions, one tap each: "Did an expert see your goat?" and "How is your goat now?"
   > Same questions in Hindi, written for the farmer's own language. The flag ⚑ marks answers that
   > mean trouble: "No" or "Worse". Those go to a person (you'll see that in the Follow-up tab).
3. **The ticks under the questions (safety checks).**
   > Before anything is sent, automatic checks confirm: right format, **no new advice slipped in**,
   > **no personal information asked**, and button labels short enough for a phone.
4. **The phone preview.** Click the channel buttons: App, then WhatsApp, then Voice.
   > The same survey, shaped for each channel. On WhatsApp it's buttons; on a phone call it's
   > "press 1 for yes". These match Digital Green's own reference examples exactly; we test that.
5. **The hand-off strip at the bottom.**
   > This is what we'd hand to the sending system: **high priority** because a vet was involved,
   > send between 7 am and 7 pm on 28–30 November, try the app first, then WhatsApp after 6 hours,
   > then a phone call. It's exempt from the weekly limit because it's urgent.

**Optional (15 seconds):** pick a "no survey" insight from the dropdown (any one ending in `no survey R1`
or `R3`) to show the "Why no survey?" box. Pick **I-000291** (cow, critical) to show the human-call case.

---

## 3. Simulate answers: what comes back (1 minute)

**Click:** Simulate answers. (It uses the insight you left Survey Studio on.)

**Do:** Channel = WhatsApp, Case = `completed`. Then change Case to `negative_outcome`. Then pick
`window_expired` (no reply in time) and `farmer_opted_out` (replied STOP).

**Say:**
> We can't send real messages in a hackathon, so we simulate the farmer's reply. Same seed, same answer,
> so it's repeatable. "Completed" is a normal answer. "Negative outcome" is a farmer saying the goat got
> worse: see `follow_up` light up. And here a farmer who never answered, or who said STOP; after STOP,
> that farmer gets nothing more from us.
>
> Every answer record is also checked against Digital Green's format (the green "schema=ok").

---

## 4. Follow-up queue: turning answers into action (1 minute)

**Click:** Follow-up queue.

**Point at:** the counts across the top, then the table, then open one ticket.

**Say:**
> This is why the survey matters. When a farmer says "it didn't work" or "my animal is worse", that answer
> shouldn't just sit in a spreadsheet. It becomes a ticket for FarmerChat staff.
>
> Here every survey's "trouble answer" is simulated so you can see the full queue: 16 tickets across all five
> channels. 8 are "advice didn't work", 5 "crop or animal damaged", 3 "couldn't reach the expert".
>
> Open one, and you see the farmer, what they were told, what they answered, and a suggested next step,
> like "book a call with the nearest agriculture expert".

**Be honest if asked:** in real use only the farmers who actually give a trouble answer appear here. The
16 is "what the system can produce", not a prediction.

---

## 5. Evaluation: how good is it, and where is it wrong (1.5 minutes)

**Click:** Evaluation. Point at the **Full pack (150 rows)** numbers on the right.

**Say (the scores):**
> Against Digital Green's 150-case answer key: 96% right on survey or no survey, 96% on the exact reason,
> 100% on the first channel.

**Point at:** the confusion matrix, then the Misses table.

**Say (the misses):**
> The grid shows every case: expected reason down the side, our reason across the top. Almost everything
> is on the diagonal, which means we agreed. All 6 misses are the same story: potatoes (and one
> cauliflower) that were already dug up and sitting in storage. Our rule said "crop already harvested,
> nothing to ask". The answer key says: the potatoes are still in the store and can still rot, so ask.
> That's a fair point, and it's one specific rule we can fix.

**Say (the window score, said plainly, not hidden):**
> One number is 0%: the send window. That's a disagreement in Digital Green's own material, not a bug.
> Their written brief and their five worked examples say "send from 7 am, after the action window ends".
> The answer key opens at 9 am and on earlier days. We followed the brief, and we've asked Digital Green
> which one they want. Switching is a setting, not a rewrite.

**Point at:** Item similarity (0.50 on the full pack).
> This compares the words in our questions with the answer key's example questions. 0.50 means about half
> the key words overlap: our questions ask the same things in slightly different words. It's a rough
> measure, not a grade.

### Rules we changed on purpose

The brief asks us to show any deliberate rule change with the numbers behind it. **As of 3 Nov we have not
changed any rule**: the code follows the brief, and every number above is that baseline. Two changes are in
progress with P2. Once each one lands, fill in the "after" column, rerun `python scripts/readme_numbers.py`,
and add one sentence to the demo for it.

| Change (owner) | Why | Before (full pack) | After |
|---|---|---|---|
| Storage exception to "already harvested": still survey crops in post-harvest storage (P2) | All 6 misses are this case | decision 96.0%, rule 96.0%, 6 misses | _fill in_ |
| Answer-key window (09:00, earlier start) behind a setting; brief rule stays the default (P2) | Brief and answer key disagree; waiting on Digital Green | window 0% | _fill in (with the setting on)_ |

If neither has landed by demo time, say: *"We kept the brief's rules on purpose and showed you exactly where
the answer key disagrees. Each one is a one-line setting once Digital Green confirms."* That's a strength.
Don't apologise for it.

---

## 6. Close and AWS (30 seconds, slide only)

**Show:** the AWS slide. **Don't** open the AWS console or claim anything runs there.

**Say:**
> Everything you saw runs on a laptop with synthetic data. In production the same pieces map onto
> standard cloud services: a timer that sends at 7 am and retries on WhatsApp after a day, a shared table
> for the weekly limit and opt-outs, and automated phone calls for voice surveys. That's the next step, not
> something we're claiming today.
>
> To sum up: we only ask when there's something worth asking, we ask in the farmer's language and on
> their channel, and every trouble answer becomes a follow-up. We agree with the answer key 96% of the time,
> and we've shown you exactly where and why we don't.

(Slide content: see the "AWS, in plain English" table in [TEAM.md](TEAM.md). Only list services as
"in production this would be…".)

---

## Likely questions (short answers)

- **Is this real farmer data?** No. It's synthetic, from Digital Green's pack. Nothing is actually sent.
- **Does it use AI to write the questions?** By default it uses checked templates: safe, free and
  repeatable. A Claude-written option exists but is off by default; the same safety checks apply to it.
- **How do you stop it giving bad advice?** It never gives advice; it only asks what happened. A check
  blocks any survey that sounds like new advice or asks for personal information.
- **What about farmers who don't want surveys?** STOP, /stop, pressing 9 or "do not ask me again" opts
  them out for good. Non-urgent surveys are capped at one per farmer per week.
- **Is the Hindi any good?** The templates were written in Hindi, not machine-translated word for word.
  A native-speaker review is on our list (P4); say so if asked.
- **Why 0% on windows?** See section 5: the brief and the answer key disagree; we followed the brief.

## If something breaks

- **App won't start:** run `python -m mel.cli eval` in the terminal and show the numbers there, then use
  the backup screenshots in the slides.
- **Full-pack numbers missing** (Evaluation says "Full pack not found"): the pack folder
  `mel-survey-agent-participant-pack/participant-pack/` isn't there. Present the mock numbers and say the
  full-pack results are on the slide.
- **A number differs from this script:** trust the screen; it's computed live.
