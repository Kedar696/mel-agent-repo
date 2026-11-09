# Prompt: v0 sketch of the finished frontend

Paste everything below the line into v0.dev. It produces a clickable mock-up (Next.js + shadcn/ui)
of the finished demo with hard-coded sample data. It is a **design reference only**: the real app
stays in Streamlit (`app/streamlit_app.py`, owner P8). Use the sketch to agree on screens and layout,
then rebuild the parts you like in Streamlit.

---

Design a desktop-first web dashboard called **MEL Survey Agent** for a hackathon demo with Digital Green.
Use Next.js, Tailwind and shadcn/ui. Hard-code all data as realistic sample JSON in one `data.ts` file;
there is no backend. Clean, calm, agricultural feel (off-white background, deep green primary, amber for
warnings, red for failures), light and dark mode, Noto Sans + Noto Sans Devanagari so Hindi renders well.

## What the product does
FarmerChat is an AI assistant that gives smallholder farmers in Bihar, India, crop and livestock advice.
This tool looks at each past conversation ("insight"), decides whether to send the farmer a short
follow-up survey ("did you follow the advice, did it work?"), writes 1–3 tap-to-answer questions in
Hindi and English, picks when and on which channel to send it (app, web, WhatsApp, Telegram, voice call),
and then shows how farmers answered, including failures. Audience: judges and programme staff, not farmers.

## Layout
Left sidebar nav: **Overview · Insights · Survey Studio · Delivery Simulator · Follow-up Queue · Evaluation**.
Top bar: data source switch ("Mock sample · 57 insights" / "Full pack · 6,999"), language toggle for
previews (हिन्दी / English), "Run pipeline" button with last-run time.

## Screens

**1. Overview**
KPI cards: insights processed, surveys planned, no-survey (with %), schema-valid files (100%),
response rate, follow-ups needed. A horizontal bar chart "Decisions by rule" with R1 junk, R2 critical →
human call, R3 nothing to verify, R4 waiting for details, R5 no check needed, R6 after season,
R7 already harvested, R8 survey. A stacked bar "Outcomes by channel" (completed / partial / failed).
A mini pipeline diagram: Insight → Decision → Timing → Questions → Hand-off → Channel → Answer.

**2. Insights** (table + detail drawer)
Columns: insight id, farmer id, crop/animal, concern, resolution type, severity badge, quality flag,
decision badge (Survey / No survey + rule id). Filters for each. Clicking a row opens a drawer with
"Farmer asked", "Advice given", and a vertical **decision trace**: each rule R1→R8 shown as a checklist
row, green tick if passed, the first rule that stopped it highlighted with its plain-English reason
(e.g. "General information only. No action was advised, so there is nothing to check.").

**3. Survey Studio** (the hero screen)
Three columns:
- Left: the insight card (asked / advised / crop + growth stage / severity).
- Middle: the survey, Hindi and English side by side, each question as a card with type chip
  (confirm / single-select / 1–5 scale), options as pill buttons, a ⚑ flag on options that trigger a
  follow-up, a source chip ("Template" or "Claude"), and guard checks as small green ticks:
  "No new advice", "No personal info", "Labels ≤ 20 chars", "Schema valid". A short rationale line.
- Right: a **phone preview** with tabs App / Web / WhatsApp / Telegram / Voice:
  App & Web = bottom sheet sliding up with question, pill options, "Skip"; WhatsApp = green chat bubble
  with up to 3 reply buttons (list picker if more); Telegram = message with inline keyboard;
  Voice = IVR script as a call transcript ("For Yes, press 1…") with a play-style waveform.
Below: **Scheduler hand-off** card: priority badge (high / normal / low), send window as a timeline bar
(not before → not after, IST), expiry date, channel order as numbered chips with wait hours between
them, frequency cap "1 per farmer per 7 days" with status (ok / capped → deferred), and a collapsible
raw JSON view.

**4. Delivery Simulator**
Pick channel + case (completed, partial, negative outcome, farmer declined, opted out, undelivered,
WhatsApp 24h session closed, free text instead of choice, duplicate answer, identity mismatch,
window expired, survey closed, sheet closed partway) + persona (responsive / busy / unreachable).
Show an animated attempt timeline: attempt 1 on App → no answer after 24h → fallback to WhatsApp →
answered. Result card: status, failure code, answers given, follow-up reasons, "schema ok" badge.
A "Run whole batch" button that fills a results grid (channels × cases) with coloured cells.

**5. Follow-up Queue**
Farmers whose answers mean trouble ("advice did not work", "crop or animal damaged", "could not get
input", "could not reach expert"). Table with farmer id, crop, reason chip, answer that triggered it,
days since, assigned field agent, and a status (new / called / resolved). Critical cases from R2 appear
here too with a "Call now" badge.

**6. Evaluation**
Score cards vs the golden set: decision accuracy 97.1%, rule accuracy 97.1%, channel 100%,
send window 0% (red, with note "Open question: golden vs worked-scenario timing rule").
A rule confusion matrix (expected R1–R8 × predicted R1–R8). A misses table (golden id, insight id,
expected, got, reason). A "Templates vs Claude" comparison table (relevance score, guard failures,
avg question length, cost). A "Regenerate README numbers" button.

## Sample data to use (keep it realistic)
Insight I-004512, farmer F-000123, mustard (flowering), pest_disease, direct_action, severity medium.
Asked: "Small green insects on mustard flowers and stems."
Advised: "These are aphids. Spray the recommended insecticide within 2 days if no rain is forecast.
Spray in the evening when bees are not active."
Survey (hi-IN):
1. क्या आपने सरसों पर माहू (छोटे हरे कीड़े) के लिए छिड़काव किया? — हाँ / नहीं ⚑
2. क्या छिड़काव की दवा आसानी से मिल गई? — हाँ, आसानी से / हाँ, मुश्किल से / नहीं मिली ⚑
3. अब पौधों पर ये कीड़े कितने हैं? — लगभग नहीं / पहले से कम / पहले जितने ⚑ / पहले से ज़्यादा ⚑
Survey (en-IN):
1. Did you spray your mustard for the aphids (small green insects)? — Yes / No ⚑
2. Was it easy to get the spray? — Yes, easily / Yes, with difficulty / Could not get it ⚑
3. How many of these insects are on the plants now? — Almost none / Fewer than before / Same as before ⚑ / More than before ⚑
Hand-off: priority normal, window 6 Dec 2026 07:00 → 9 Dec 2026 19:00 IST, channels App → WhatsApp,
expires 11 Dec 2026 19:00.
Other example insights: wheat irrigation timing (direct action), potato late blight (wait and monitor),
cow with fever escalated to a vet (escalate to expert, high priority), wheat variety plan (plan created,
1–5 usefulness scale), zero-tillage general info (no survey, R3).
Farmer ids look like F-000123, insight ids I-004512, survey ids S-04512. All data is synthetic.

## Constraints
- Hindi text must never be truncated; labels are short (≤ 20 characters) by design.
- Every screen works with keyboard and has readable contrast; status uses icon + colour, not colour alone.
- No real names, phone numbers or locations below district level.
- Keep components simple enough to recreate later in Streamlit (cards, tabs, tables, charts, a phone frame).
