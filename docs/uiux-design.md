# Fasal Pulse UI: visual design

Owner: UI/UX design (C). Files: `app/theme.py` (global CSS, `apply_theme()`), `.streamlit/config.toml`
(Streamlit's own theme options), this note. Layout belongs to `app/streamlit_app.py`; the interactive
channel preview belongs to `app/channel_preview.py`. Streamlit stays the real UI.

## Direction

The app is a field tool for a Bihar rabi season: wheat-straw ivory for the page, one strong surface in deep
leaf green (the selected insight), marigold only where attention is earned, clay only for warnings. It is
simple on purpose: flat surfaces separated by a sandstone line, no drop shadows, no uppercase micro-labels,
no middle-dot metadata strings as content, one typeface for Hindi and English. Hierarchy comes from size,
weight and the three surface steps (ivory page, sandstone, paper card).

What it is not: a dark dashboard, a card kit with shadows on everything, or a rewrite outside Streamlit.

## Theme "Rabi Season" (theme-factory format)

Rabi is Bihar's winter crop season: mustard in flower, wheat straw, green fields, lime-washed walls.

Color palette

- Ivory `#F7F3E8`: page background (wheat straw, not pink cream)
- Sandstone `#EEE7D7`: secondary surface, code, table headers, hover
- Paper `#FFFDF8`: cards and metrics
- Line `#DED6C3`: every border
- Ink `#1E2A22`, Muted `#5F6B62`: text
- Leaf green `#2A6B4A`: primary (buttons, links, active tab); Deep green `#1E5A3F`: the insight card;
  Green ink `#174A33` on Green soft `#E3EFE4`: green badges
- Marigold `#E3A51F` on shapes; Marigold pale `#F6D37C` as text on deep green; Marigold ink `#8A5A0C` on
  Marigold soft `#FBEFD0` for amber badges and follow-up pills
- Clay `#A4422E` on Clay soft `#F7E4DE`: warnings, red badges

Typography

- One family: Mukta (Ek Type, Mumbai), weights 400 / 500 / 600 / 700, loaded from Google Fonts by
  `config.toml`. Mukta was drawn for Devanagari and Latin together, so Hindi and English questions sit on
  the same line without a visible font switch.
- Fallbacks, in order: Kohinoor Devanagari (macOS/iOS), Devanagari Sangam MN (macOS), Nirmala UI (Windows),
  Noto Sans Devanagari (Android/Linux), then the system sans. If Google Fonts is unreachable the page still
  renders Hindi correctly with these.
- Headings use the same family at weight 600; no serif display face.

Best used for: this app and its slides. Not a general-purpose theme.

## Tokens (CSS variables, all prefixed `--mel-`)

| Variable | Value | Use |
|---|---|---|
| `--mel-ivory` / `--mel-sand` / `--mel-paper` | `#F7F3E8` / `#EEE7D7` / `#FFFDF8` | page / secondary / card |
| `--mel-line`, `--mel-line-strong` | `#DED6C3`, `#C9BFA6` | borders, button borders |
| `--mel-ink`, `--mel-ink-soft`, `--mel-muted` | `#1E2A22`, `#44524A`, `#5F6B62` | text levels |
| `--mel-green`, `--mel-green-deep`, `--mel-green-ink`, `--mel-green-soft`, `--mel-green-pale` | see palette | primary, insight card, badge text, badge bg, labels on deep green |
| `--mel-marigold`, `--mel-marigold-pale`, `--mel-marigold-soft`, `--mel-marigold-ink` | see palette | accent |
| `--mel-clay`, `--mel-clay-soft` | `#A4422E`, `#F7E4DE` | warnings |
| `--mel-wa`, `--mel-wa-bar`, `--mel-wa-bg`, `--mel-wa-in`, `--mel-wa-out`, `--mel-wa-link` | `#075E54`, `#008069`, `#ECE5DD`, `#FFFFFF`, `#DCF8C6`, `#027EB5` | WhatsApp colours, kept for reuse; the preview sets its own close values (see below) |
| `--mel-tg`, `--mel-tg-bar`, `--mel-tg-bg`, `--mel-tg-in`, `--mel-tg-out`, `--mel-tg-link` | `#2AABEE`, `#517DA2`, `#E6EBEE`, `#FFFFFF`, `#EFFDDE`, `#168ACD` | Telegram colours, kept for reuse; the preview sets its own (see below) |
| `--mel-font`, `--mel-mono` | stacks above | text, ids |
| `--mel-fs-body` 17px, `--mel-fs-small` 14px, `--mel-fs-label` 13px, `--mel-fs-lead` 19px | | type scale |
| `--mel-lh` 1.55, `--mel-lh-hi` 1.65 | | line height; Hindi gets the taller one (matras need room) |
| `--mel-r-card` 14px, `--mel-r-ctl` 10px, `--mel-r-pill` | | radius scale: cards, controls, badges |
| `--mel-t-fast` 140ms, `--mel-t-base` 220ms, `--mel-ease` | | motion |

`app.theme.PALETTE` has the same hex values for Python callers (chart colours).

Contrast: the app-theme text/background pairs (ink, muted, green, marigold and clay families on ivory,
sandstone, paper and deep green) were computed with the WCAG formula and are at or above 4.5:1; lowest are
muted on sandstone 4.5, clay on clay soft 5.0, green pale on deep green 5.5, marigold pale on deep green 5.6.
The WhatsApp and Telegram colours were not measured: they follow the products.

## Type scale and Hindi

- Body 17px (`baseFontSize = 17`), captions and notes 14px, labels 13px. Nothing smaller.
- h1 32px / h2 25px / h3 20px, all weight 600, no letter-spacing.
- Insight card: title 24px, the farmer's question and the advice 18px at line-height 1.6, metadata 15px with
  13px labels, the "why" line 15px marigold with a 16px explanation.
- Hindi: never `text-transform` or `letter-spacing`; line-height 1.6 or more; keep Devanagari labels at the
  same size as English (Devanagari x-height is smaller, so 15px Hindi reads like 14px Latin).
- Language controls are labelled Hindi / English for the user; `hi-IN` / `en-IN` stay in the data.

## Read the call aloud (ElevenLabs)

On the Voice channel a speaker button beside Restart (Apple style: tap the speaker to read the call aloud or
mute it, tap its chevron for the volume) plays what the farmer would hear: the
greeting, then each question as it comes up, then the closing line, through ElevenLabs text to speech
(`app/tts.py`, multilingual model, standard library HTTP, one call per distinct line cached by Streamlit).
It needs `ELEVENLABS_API_KEY` in the environment or the repo's `.env` (a key with Text to Speech access is
enough; see `.env.example`); without it, turning the speaker on shows how to enable it. Nothing is sent to a farmer.

## Dates and times

Every human-facing date or time in the app goes through `app/display_time.py` (B's helper): Eastern Time
(America/New_York, EST or EDT by date), MM/DD/YYYY and h:mm AM/PM. The Scheduler card shows the send time with
its zone (e.g. EST); its "Stops trying" time, the report line, custom "Submitted" time,
follow-up "Answered" column and ticket caption, run-history times and generated history or rationale text all
use it. Tables are formatted on a display copy; the source frames and every stored ISO/IST timestamp, JSON
contract and raw developer JSON stay as the organisers' schema wants. Policy copy keeps naming India
explicitly with US formatting ("before 03/31/2027, between 7:00 AM and 7:00 PM India time") rather than a
fixed Eastern clock, because daylight saving shifts the offset. Durations stay durations, and the farmer's
quoted question and advice are never reformatted.

## Surfaces and spacing

- Page ivory; widgets sandstone (Streamlit `secondaryBackgroundColor`); cards paper with a 1px line and
  14px radius; no shadows in the app theme. Inside the phone preview, bubbles and sheets keep the
  product-like shadows of the real apps.
- The deep-green insight card is the only saturated block on the screen. Keep it on the left, keep its
  text large, do not add a second dark block beside it.
- Metrics are quiet paper cards of equal height (14px label, 29px value).
- Spacing rhythm: 12px between cards (the insight card included), 18px between a tab bar and its content,
  20px card padding.
- Buttons: 44px minimum height (touch target), 600 weight, paper with a strong line; hover turns green soft;
  primary is leaf green. Focus ring is a 3px marigold outline on every button, tab and expander; the preview
  uses its own 2px green ring inside the phone.

## Motion

- One entry motion: `mel-rise` (opacity 0 to 1, 5px up, 220ms, ease-out) on cards, the insight card and the
  tab panel. Streamlit keeps unchanged elements, so only what changed rises; it shows the change rather
  than decorating the page.
- Interaction motion: tab colour and underline 140ms, button hover and press (scale .985), rule bars width.
  The preview adds its own short bubble and sheet entrances.
- `prefers-reduced-motion: reduce` removes all of it, in the theme and in the preview. Nothing autoplays.

## What `config.toml` does and what `apply_theme()` does

`config.toml` sets what CSS cannot reach reliably: palette colours for Streamlit's own widgets and alerts,
font (with the Google Fonts URL and the Devanagari fallbacks), base size 17px, heading sizes and weights,
metric value size, radii (`baseRadius 0.75rem`, `buttonRadius 0.6rem`), border colour, top and bottom
padding, chart colours. `apply_theme()` adds the CSS variables, the page surfaces, tabs, metrics,
expanders, light button rules, every `mel-*` class, motion and the narrow-screen rules. The app calls it
once after `st.set_page_config`.

Selector policy (Streamlit 1.66, which renders tabs, button groups and selects with React Aria, not
BaseWeb): Streamlit parts are addressed only through `data-testid` attributes and the roles they carry,
never through generated `st-emotion-cache-*` class names.

- Tabs: `[data-testid="stTabs"] [role="tablist"]` holds `[data-testid="stTab"]` items with
  `aria-selected`; panels are `[data-testid="stTabPanel"]`.
- Metrics: `stMetric`, `stMetricLabel`, `stMetricValue`, `stMetricDelta`. Expanders:
  `[data-testid="stExpander"] details`. Alerts: `stAlert`.
- Buttons: `stBaseButton-secondary`, `stBaseButton-primary`. Segmented controls:
  `[data-testid="stButtonGroup"] button[data-variant="segmented_control"]`.
- Text: `stMarkdownContainer`, `stCaptionContainer`, `stWidgetLabel`, `stHeading`. Layout:
  `stAppViewContainer`, `stHeader`, `stMainBlockContainer`. Toggles sit in `stCheckbox`, selects in
  `stSelectbox`.

Button rules are deliberately light (border, weight, height, focus). The preview scopes everything under
its keyed containers (`.st-key-<slug>` for the phone, plus `-act`, `-pick`, `-pickx`, `-hang` and `-foot`)
and its `mel-pv-*` classes, so its rules beat the global ones by specificity with no `!important`. The
theme uses `!important` only to neutralise inline styles in the insight eyebrow and hand-off values.

## Layout (`app/streamlit_app.py`), as integrated

- No CSS lives in the app file; it imports `apply_theme` and `PALETTE` (the bar chart uses `PALETTE["green"]`).
- Classes in use: `mel-card`, `mel-k`, `mel-badge`, `mel-rule`, `mel-id`, `mel-track`/`mel-fill`,
  `mel-insight` with `mel-eyebrow`, `.f`, `.mel-meta`, `.mel-why`, `mel-note`, `mel-chk`, `mel-strip`,
  `mel-tl`, `mel-tlab`, `mel-ch`. The old static phone and bilingual question classes (`mel-phone`
  family, `mel-q`, `mel-pill`) were removed on November 4, 2026 once nothing referenced them.
- Helpers defined but unused so far: `mel-lead` (19px intro line), `mel-hi` (Hindi line-height),
  `mel-plan` (a card whose `mel-sub` sections are separated by a hairline, 14px above and below) and
  `mel-insight-top` (a flex band with a divider when inside `mel-insight`).
- Settings bar above the columns: Channel, Language, a restart icon, pretend history. Language defaults
  to English so judges can read along, Hindi is one tap away, and the widget keeps a manual choice across
  the reruns each tap on the phone causes. The restart control is icon-only (Material `restart_alt`, about
  40px, tooltip and accessible name "Restart survey"; the label is clipped off screen by a rule keyed to
  `st-key-studio_restart` in the theme). It resets only the phone; case, channel, language and pretend
  history keep their values. History rules H1 to H4 are always on in the app (off for scoring and the CLI).
- Masthead instead of the big title: "Fasal Pulse" wordmark in green ink with "MEL Survey Agent" beside it and
  a one-line descriptor on the right, a hairline under it, then the three tabs. Top padding is 1rem.
  Streamlit's Deploy button is hidden; the menu stays.
- Studio toolbar (one row): in demo mode the Demo picks dropdown on the left (four demos, then Browse) and
  the user's own insight on the right, never inside the dropdown. On first load the right side is the primary
  "Add your own insight" button. Once an own insight exists it is joined by "Your insight", the stable way
  back to the last own report. In own-insight mode the dropdown is replaced by a source label ("Source:
  Your insight, Cow: livestock health", or "draft, no report yet"), and the right side becomes "Edit insight" /
  "Hide editor" (one toggle that shows or hides the whole editor) and "Back to the demos", which brings the
  dropdown back on the demo it last showed (kept in a plain session key, since a hidden widget loses its own).
- Editor (`own_insight_editor`): a bordered panel with the two text boxes, the collapsed Details expander and
  "Preview the survey", shown only while open. Draft retention: every editor value is mirrored into
  `custom_draft` in session state and the widgets are re-seeded from it, because Streamlit drops a widget's key
  once it is not rendered; hiding the editor, switching to a demo and coming back keep both the draft and the
  generated result. The pipeline runs only on a valid submit (then the editor collapses and the report appears);
  reopening never regenerates; a new submit gets new ids and a fresh phone; invalid input keeps the editor open
  with the error and closes any earlier report.
- Report title line (`report_strip`): a kicker ("Your insight" in marigold ink, "Demo insight" or "Browsed
  insight" in green ink), a title such as "Cow: livestock health" or the demo's name, and a one-sentence summary
  taken from the real pipeline output (survey planned with question count, severity, priority, first channel
  and send time, or "No survey: R4 Waiting for details"), plus the submission time for own insights. The green
  card's eyebrow reads "Your insight" for own insights. Each column carries a small label: Conversation, What
  the farmer sees, Plan and checks.
- Your own insight (`app/custom_context.py`): two text boxes (what the farmer asked, the advice given) and the
  Details expander (crop or animal, problem, severity, advice type, act within N days, check back later, the
  farmer's usual channel, the farmer's language with English as the default, district). The text is carried as
  typed, the details become the fields, four fields no rule reads are schema fillers. Ids are `I-9000NN` per
  submission, outside the pack's range; `created_at` is the real IST time frozen at submission. No model reads
  the text; an empty advice box becomes "No advice given yet." and R4; a whitespace-only question is refused.
  A live line beside Preview the survey always states the crop, problem, severity and advice type the survey
  will be built for. Details states the date assumption (rabi 2026-27 calendar, send windows before
  31 March 2027). Submissions never touch the batch or the Overview and Evaluation numbers.
- Survey Studio columns are 1.05 : 1.6 : 1 (insight, preview, hand-off). Below 760px Streamlit stacks
  them; the theme reduces paddings, makes the hand-off strip one column and lets the timeline labels wrap.
- Copy rules: sentence case, no uppercase labels, labels at least 13px, prefer a short sentence to a
  middle-dot string.

## Channel preview (`app/channel_preview.py`), as implemented

Scope and styling

- The phone is the keyed container: 378px wide and 700px tall for every channel (`--mel-pv-h`), 9px dark
  bezel, 34px radius, so switching channel never changes the page height. The chat or sheet body scrolls
  inside the frame with the newest message at the bottom; the frame plays a short enter animation on a
  channel or language switch (the keyframe name carries the phone's key), off under reduced motion. Per-channel CSS is generated under `.st-key-<slug>`; the HTML the
  preview writes sits in `<div class="mel-pv mel-pv-wa|tg|app|web|voice">`. Nothing targets the rest of the app.
- Inside the phone the font stack is the system one (`-apple-system`, Segoe UI, Roboto, Noto Sans, Noto Sans
  Devanagari), as on a real handset; Mukta applies outside it. The preview reads `--mel-green` and
  `--mel-muted` from the theme and sets its own product colours otherwise (WhatsApp header `#008069`,
  wallpaper `#efeae2`, outgoing `#d9fdd3`, link blue `#027eb5`; Telegram header `#517da2`, a soft gradient
  wallpaper, outgoing `#effdde`, inline buttons `rgba(66,89,107,.62)` with white text). These were taken
  from the current apps by eye, are not brand-published and were not contrast-measured.
- "WhatsApp" and "Telegram" appear only as words; no logos (Meta's brand rules: official assets only, no
  modified logos, no implied endorsement; https://www.meta.com/brand/resources/whatsapp/whatsapp-brand/).
  The header shows "FarmerChat" with an "F" avatar and a "Business account" / "bot" subtitle.

Ground truth in the repo

- Payloads: `mel.channels.render(survey, channel)`; strings in `mel.channels.render.UI`; how each channel
  arrives in `HOW_IT_ARRIVES`; `choices(item)` gives (label, value) pairs, scale values are ints.
- Reference renders: `data/mock/scenarios/*/render/{hi-IN,en-IN}/whatsapp.json` and `telegram.json`.
- The brief: answer labels are at most 20 characters "so a WhatsApp button shows them whole"
  (`mel-survey-agent-participant-pack/participant-pack/index.html`).

WhatsApp

- Opening: the approved template (invite body, quick replies Start / Not now as live white buttons with
  blue text under the bubble), because the survey goes out days after the chat, outside the 24-hour reply
  window. Start appears as the farmer's outgoing bubble and question 1 arrives; Not now ends the attempt.
- Up to three choices: reply buttons. Meta: "Supports up to 3 buttons", button title max 20 characters,
  body max 1024 (https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons-messages).
  The tap becomes an outgoing bubble (green, double tick) with the button title. Answered questions keep a
  static, dimmed copy of the buttons they showed, as in the real app where old buttons stay visible but inert.
- More than three choices: a list message. Meta: up to 10 sections and 10 rows in total, button text max
  20, row title max 24, and "when a user taps the button in the message, WhatsApp displays a modal that
  lists the available options" (https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages).
  The question shows one "☰ Choose" button; it opens a bottom sheet (handle, "Choose" title, "Choose one"
  section) with one radio-style row per option and an ✕ to close. Deliberate simplification: tapping a row
  selects and sends in one step, whereas the native sheet selects a radio and then needs a separate Send
  button. Answered list questions keep a dimmed "☰ Choose".
- Typing: a real chat input stays at the bottom while the attempt is open. "STOP" (any case) opts out; any
  other text ends the attempt as free text (the record says the question goes out again with its buttons).
  Typed text appears as an outgoing bubble. After the last answer the thank-you line (or its follow-up
  variant) arrives.
- Chrome: status bar with the clock, green header, incoming bubbles white with a tail, outgoing green with a
  tail and blue ticks, a white date chip, the "secure service from Meta" notice, 15px message text, buttons
  about 43px tall; times 12-hour with lowercase am/pm.

Telegram

- Opening: the invite as a plain message, then each question with inline buttons under the bubble, one per
  row, scale numbers sharing one row (`_telegram` in `mel/channels/render.py`).
- Inline keyboards are shown "directly below their relevant messages", and "pressing buttons on inline
  keyboards doesn't send messages to the chat"; Telegram recommends editing the keyboard rather than
  sending a new message (https://core.telegram.org/bots/features#inline-keyboards; structure in
  https://core.telegram.org/bots/api#inlinekeyboardmarkup). So a tap creates no farmer bubble: the
  question is edited to show "✓ <label>" with an "edited" marker and its keyboard is gone. A question the
  farmer answered by typing keeps a dimmed copy of its keyboard.
- Typing "/stop" opts out; other text ends the attempt as free text and shows as an outgoing bubble.
- Chrome: blue-grey header, gradient wallpaper, 16px-radius bubbles, translucent date chip, times in
  uppercase AM/PM, the date as "November 4, 2026" in English and "4 नवंबर 2026" in Hindi.

App, web and voice

- App and web: the bottom sheet from `render()`'s `sheet` (title, step bars, "1 of 3" labels, the answers
  given so far listed above the current question, Close and "Do not ask me again"). No Skip, because P3's
  submit-once sheet drops later answers after a skipped step. The app shows the push notification first;
  web shows browser chrome instead of a status bar.
- Voice: a call screen with the IVR lines as captions, keypad buttons ("1 · label", scale digits), 2 for
  Not now, 9 for no more calls, and End call (hang-up keeps the answers so far).

Timestamps and transcript rules

- The send time is P2's `send_at` for the first channel, otherwise the window opening plus the channel's
  fixed offset, the same rule P3's simulator uses, so screen and record agree. The farmer opens a few
  minutes later and the answers are spread over the following minutes so the last one lands on P3's
  `answered` stamp. All times are derived from the survey and the taps, so a rerender never moves them.
- Only taps and typed text appear as farmer messages; no answer is invented. Historic buttons stay in the
  transcript, dimmed and inert; only the current question has live controls, so no future question is shown.
- Under the phone: one line of status (live, finished, closed, declined, opted out, typed, call cut off).
  The preview's own Start over is hidden (`show_restart=False`); the Studio's settings bar has the single
  restart icon, which passes `restart=True` for that run and puts the phone back to its first screen.

## Validation record (November 4, 2026)

- `app/theme.py` imports cleanly; `streamlit config show` accepts every option in `.streamlit/config.toml`
  and the server log shows no "invalid config" warning.
- Theme-stage baseline, before adding the preview tests: 512 passed in 19 s with `MEL_USE_LLM=0`.
- Final integrated suite: 526 tests passed with `MEL_USE_LLM=0 MEL_JUDGE=0`. Independent browser checks
  covered the full WhatsApp conversation in the team app, Hindi Telegram, App/Web partial completion,
  restart, list and scale choices, and voice start/keypad/hang-up with matching clock and record times.
  A separate 220-case check across the reference surveys verified schema validity, exact submitted
  answers and chronological response timestamps. CLI batch output validated with 105 files and zero
  invalid files; participant-pack parity reported zero differences.
- Headless Chrome (Playwright, fresh context) against the integrated app at 1400px and 390px: Mukta is
  loaded (`document.fonts.check`), body 17px on the ivory page, insight quotes 18px / 1.6 (17px at phone
  width), labels 13px with no uppercase, active tab 17px / 600 in green ink with the green underline,
  segmented-control buttons 40px tall with 15px text, hand-off values 16px, all six Overview metric cards
  the same height, no horizontal page scroll at 390px. With `prefers-reduced-motion: reduce` the card and
  tab-panel animations resolve to `none`.
- Contrast pairs listed under Tokens (app theme only) were computed with the WCAG formula; all at or
  above 4.5:1.
- Second pass (A's requests): the insight card carries a 12px bottom margin (measured at 1400px and
  390px); at 390px the hand-off strip is one column (316px) and the timeline labels Opens / Closes / Expires
  sit about 70px apart instead of touching; still no horizontal scroll. Unused phone and question CSS removed
  after a repo-wide check found no references outside the theme.
- Docs pass: this note was re-read against the final `app/channel_preview.py`, `app/preview_state.py` and
  `app/streamlit_app.py`; no further tests or browser runs. Root reviews the integrated app on port 8510.
- English default and Restart wiring (later on November 4): `app/streamlit_app.py` compiled with
  `py_compile` after each edit; the phone-frame facts above come from the preview's CSS at that time and
  B's own status note is the reference if they differ.
