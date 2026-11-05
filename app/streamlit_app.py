"""Fasal Pulse - MEL Survey Agent: the team demo. Owner: P5.  Run: streamlit run app/streamlit_app.py
P4's standalone survey demo (demo/p4_standalone) is folded in: Survey demo shows what the agent remembers
about the farmer and how history rules H1-H4 adapt the survey (on in the app, off for scoring).
Tabs: Dashboard (default: overview + evaluation), Survey demo (insight | interactive channel preview | hand-off),
Follow-up queue. Look and feel: app/theme.py. Interactive preview: app/channel_preview.py.
Every number on screen comes from the real pipeline; nothing is hard-coded."""
import copy
import os
import re
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st


def _reload_mel_if_changed():
    """Streamlit reruns this file when code changes (local `git pull`, or Streamlit Cloud pulling a merge),
    but keeps already-imported packages in memory, so new mel/ code would not be used and calls fail with
    'unexpected keyword argument'. If any mel/*.py file changed since the last run, drop the old modules
    and cached results so everything below is imported and computed fresh."""
    stamp = max(p.stat().st_mtime for p in (Path(__file__).resolve().parents[1] / "mel").rglob("*.py"))
    if getattr(sys, "_mel_code_stamp", stamp) != stamp:
        for name in [m for m in sys.modules if m == "mel" or m.startswith("mel.")]:
            del sys.modules[name]
        st.cache_data.clear()
        st.cache_resource.clear()
    sys._mel_code_stamp = stamp


_reload_mel_if_changed()

from mel.channels import render
from mel.config import CHANNELS, PACK_DATA
from mel.data import load_insights, load_farmers, errors
from mel.evaluation import evaluate, load_history, rules_changed
from mel.pipeline import run_pipeline, run_insight, clean
from mel.schedule import build_handoff
from mel.schedule.handoff import CapLedger
from mel.simulator import simulate
from mel.writer import (check_survey, write_surveys, FarmerMemory, build_context, summary_lines,
                        history_notes)

from app import custom_context as cc
from app import tts
from app.display_time import ZONE_LABEL, format_clock, format_date, format_datetime, format_dates_in_text
from app.channel_preview import render_channel_preview
from app.theme import PALETTE, apply_theme

APP_NAME = "Fasal Pulse - MEL Survey Agent"
st.set_page_config(page_title=APP_NAME, layout="wide")
apply_theme()

RULE_LABEL = {"R1": "Junk / unclear", "R2": "Critical → human call", "R3": "Nothing to verify",
              "R4": "Waiting for details", "R5": "No check needed", "R6": "After season",
              "R7": "Already harvested", "R8": "Survey planned"}
RULE_TONE = {"R2": "red", "R4": "amber", "R6": "amber", "R8": "green"}
CH_NAME = {"app": "App", "web": "Web", "whatsapp": "WhatsApp", "telegram": "Telegram", "voice": "Voice"}
LANG_NAME = {"hi-IN": "Hindi", "en-IN": "English"}


def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def badge(text, tone="green"):
    return f'<span class="mel-badge {tone}">{escape(str(text))}</span>'


ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?")
ISO_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}")


# Every human-facing date or time goes through app/display_time.py (Eastern Time, MM/DD/YYYY, h:mm AM/PM).
# Stored timestamps, JSON contracts and the raw developer JSON stay in the organisers' ISO / IST format.
def short(ts: str) -> str:
    """Compact display without the zone; the label beside it names the zone."""
    return f"{format_date(ts)} {format_clock(ts)}"


def long(ts: str) -> str:
    """Full display with the zone, e.g. 11/27/2026 8:30 PM EST."""
    return format_datetime(ts)


def us_text(text):
    """Generated explanatory text (history notes, rationales, send-time reasons) with its ISO dates shown the US
    way. Never applied to the farmer's quoted question or advice."""
    return format_dates_in_text(text) if isinstance(text, str) and ISO_TOKEN.search(text) else text


def us_display(df):
    """A display copy of a table with ISO dates and timestamps in US form; the source frame is left as is."""
    def cell(v):
        if isinstance(v, str) and ISO_TS.fullmatch(v):
            try:
                return format_datetime(v)
            except (ValueError, TypeError):
                return v
        return us_text(v)
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):  # pandas 3 uses a str dtype
            out[col] = out[col].map(cell)
    return out


def table(df, **kw):
    return st.dataframe(us_display(df), **kw)  # returns the row selection when on_select is set


# The full participant pack (6,999 conversations) when it is in the repo; the 57-row mock sample otherwise.
# An explicit MEL_DATA_DIR always wins.
DATA_DIR = None if os.environ.get("MEL_DATA_DIR") else (PACK_DATA if (PACK_DATA / "insights.jsonl").exists() else None)


@st.cache_resource(show_spinner="Running the pipeline on every conversation…")
def batch():
    """Run the whole pipeline once, replay the weekly limit in send order (P3's CapLedger.admit), and count
    schema-valid files once, so later clicks stay fast even on the full dataset."""
    res = run_pipeline(load_insights(DATA_DIR / "insights.jsonl" if DATA_DIR else None),
                       farmers=load_farmers(DATA_DIR / "farmers.csv" if DATA_DIR else None),  # farmers feed send time
                       history=True)  # P4's history rules: on in the app, off for scoring (team decision 4 Nov)
    rows = list(zip(res.insights, res.outputs))
    # Contract order: send-window start, then created time, then farmer. Copies, because admit() edits the
    # hand-off it merges into, and Survey demo must keep showing the original survey.
    hs = sorted((copy.deepcopy(o["handoff"]) for _, o in rows if "handoff" in o),
                key=lambda h: (h["send_window"]["not_before"], h["created_at"], h["frequency_cap"]["key"]))
    led = CapLedger()
    admits = {}
    for h in hs:
        a = led.admit(h)
        admits[h["handoff_id"]] = (a.decision, a.reason)
    surveyed = [o for _, o in rows if o["decision"].survey]
    files = [clean(s) for o in surveyed for s in o["surveys"].values()] + [o["handoff"] for o in surveyed]
    kinds = ["survey"] * (len(files) - len(surveyed)) + ["schedule_handoff"] * len(surveyed)
    valid = sum(not errors(k, f) for k, f in zip(kinds, files))
    return rows, admits, valid, len(files)


@st.cache_resource(show_spinner=False)
def memory():
    """What the agent knows about each farmer (P4's FarmerMemory): earlier conversations + farmer profile."""
    return FarmerMemory(load_insights(DATA_DIR / "insights.jsonl" if DATA_DIR else None),
                        load_farmers(DATA_DIR / "farmers.csv" if DATA_DIR else None))


rows, admits, n_valid, n_files = batch()
html('<div class="mel-mast"><div class="mel-brand">Fasal Pulse <span>MEL Survey Agent</span></div>'
     '<div class="mel-tag">Follow-up surveys for FarmerChat advice, Digital Green track. Synthetic data; nothing is sent.</div></div>')
tab_over, tab_studio, tab_follow = st.tabs(["Dashboard", "Survey demo", "Follow-up queue"])

# Dashboard motion, ported from the Success Metrics site (TSWhackUMBC site/page.html): each metric counts up from 0
# with an ease-out cubic over 1.1 s the first time it scrolls into view and always lands on Streamlit's exact text;
# the rule bars grow in with the same timing (Web Animations, so Streamlit's DOM is never restyled). A count stops
# if Streamlit rewrites the value mid-way. Nothing moves under prefers-reduced-motion. Installed once per page.
COUNT_UP_JS = """
(() => {
  if (window.__melCountUp || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  window.__melCountUp = true;
  const MS = 1100, ease = p => 1 - (1 - p) ** 3, NUM = /^(\\D*?)(-?[\\d,]*\\.?\\d+)(.*)$/s;
  const textOf = el => { const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) if (n.nodeValue.trim()) return n; return null; };
  const count = el => {
    const tn = textOf(el), final = tn && tn.nodeValue, m = final && final.match(NUM);
    if (!m) return;
    const end = parseFloat(m[2].replace(/,/g, '')), dec = (m[2].split('.')[1] || '').length;
    if (!isFinite(end) || end === 0) return;
    const fmt = v => m[1] + (m[2].includes(',') ? v.toLocaleString('en-US', {minimumFractionDigits: dec,
      maximumFractionDigits: dec}) : v.toFixed(dec)) + m[3];
    const t0 = performance.now(); let last = null;
    const step = t => {
      if (last !== null && tn.nodeValue !== last) return;  // Streamlit changed the value: keep its text
      const p = Math.min((t - t0) / MS, 1);
      tn.nodeValue = last = p < 1 ? fmt(end * ease(p)) : final;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  const grow = el => el.animate([{width: '0%'}, {width: el.style.width}], {duration: MS, easing: 'cubic-bezier(.2,.7,.2,1)'});
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    io.unobserve(e.target);
    e.target.matches('.mel-fill') ? grow(e.target) : count(e.target);
  }), {threshold: 0.4});
  const seen = new WeakSet();
  const scan = () => document.querySelectorAll('[data-testid="stMetricValue"], .mel-fill').forEach(el => {
    if (!seen.has(el)) { seen.add(el); io.observe(el); } });
  let queued = false;
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; scan(); }); } })
    .observe(document.body, {childList: true, subtree: true});
  scan();
})();
"""

# ---------------------------------------------------------------- Overview (first half of "Dashboard")
with tab_over:
    st.html(f"<script>{COUNT_UP_JS}</script>", unsafe_allow_javascript=True)
    st.header("Overview")
    n = len(rows)
    rules = Counter(o["decision"].rule for _, o in rows)
    surveyed = [o for _, o in rows if o["decision"].survey]
    limit = Counter(d for d, _ in admits.values())
    held = len(admits) - limit["sent"]
    high = sum(o["handoff"]["priority"] == "high" for o in surveyed)
    llm = sum(s.get("_source") == "llm" for o in surveyed for s in o["surveys"].values())
    c = st.columns(6)
    c[0].metric("Insights processed", n)
    c[1].metric("Surveys planned", len(surveyed), f"{len(surveyed) / n:.0%} of insights", delta_color="off", delta_arrow="off")
    c[2].metric("No survey", n - len(surveyed), f"{(n - len(surveyed)) / n:.0%} of insights", delta_color="off", delta_arrow="off")
    c[3].metric("Schema-valid files", f"{n_valid / max(n_files, 1):.0%}", f"{n_valid:,} / {n_files:,}", delta_color="off", delta_arrow="off")
    c[4].metric("High priority", high, "sent first", delta_color="off", delta_arrow="off")
    c[5].metric("Weekly limit (1 per 7 days)", held, "moved, merged or skipped", delta_color="off", delta_arrow="off")

    left, right = st.columns([1.1, 0.9])
    with left:
        top = max(rules.values() or [1])
        bars = "".join(
            f'<div class="mel-rule"><span class="mel-id">{r}</span><span>{RULE_LABEL[r]}</span>'
            f'<div class="mel-track"><div class="mel-fill {RULE_TONE.get(r, "")}" style="width:{rules.get(r, 0) / top * 100:.0f}%"></div></div>'
            f'<b>{rules.get(r, 0)}</b></div>' for r in RULE_LABEL)
        html(f'<div class="mel-card"><b>Decisions by rule</b><div class="mel-note">'
             f'Why an insight was or wasn\'t surveyed</div>{bars}</div>')
    with right:
        st.markdown("**First channel planned**")
        first_counts = Counter(CH_NAME[o["handoff"]["channel_order"][0]["channel"]] for o in surveyed)
        st.bar_chart({"surveys": first_counts}, horizontal=True, color=PALETTE["green"], height=170)
        st.markdown("**Survey source**")
        st.caption(f"Template: {len(surveyed) * 2 - llm:,}. Claude: {llm:,}."
                   + ("  (LLM writer off: set MEL_USE_LLM=1)" if not llm else ""))
    with st.expander("How it fits FarmerChat"):
        st.markdown("""
1. The farmer chats with FarmerChat (app, web, WhatsApp, Telegram or voice).
2. FarmerChat's insight extractor sums up the chat: crop or animal, problem, advice, whether to check back.
   *(Digital Green gave us 6,999 synthetic ones.)*
3. **This agent:** decides survey or not (rules R1–R8), remembers the farmer's earlier conversations
   (history rules H1–H4), writes 1–3 tap questions in Hindi and English, checks them, and sets the send window.
4. **Scheduler hand-off:** send window, channel order, weekly limit, priority, expiry.
5. The farmer answers on their channel. Answers that mean trouble go back to FarmerChat staff (Follow-up queue).

Out of scope: real delivery and real farmers. Everything here is simulated.""")
    st.caption(f"Weekly limit (P3): {limit['sent']:,} sent as planned, {limit['moved']:,} moved to a later date, "
               f"{limit['merged']:,} merged into the farmer's other survey and {limit['skipped']:,} skipped. "
               f"High-priority surveys are exempt.")

# ---------------------------------------------------------------- Survey demo
labels = {f"{i.get('insight_id')} · {(i.get('asset') or {}).get('name')} · {i.get('resolution_type')} · "
          f"{'survey' if o['decision'].survey else 'no survey ' + o['decision'].rule}": (i, o) for i, o in rows}


def guard_ticks(surveys):
    probs = [p for s in surveys.values() for p in check_survey(clean(s))]
    checks = [("Schema valid", "schema"), ("No new advice", "advice"), ("No personal info", "personal"),
              ("Labels ≤ 20 chars", "label")]
    return "".join(f'<div class="mel-chk {"bad" if any(k in p for p in probs) else ""}">'
                   f'{"✕" if any(k in p for p in probs) else "✓"} {t}</div>' for t, k in checks)


def handoff_card(h, send_time):
    """The scheduler hand-off, stacked for the narrow right column of Survey demo."""
    nb, na = (datetime.fromisoformat(h["send_window"][k]) for k in ("not_before", "not_after"))
    ex = datetime.fromisoformat(h["expires_at"])
    span = (ex - nb).total_seconds() or 1
    w = (na - nb).total_seconds() / span * 100
    tone = {"high": "red", "normal": "slate", "low": "slate"}[h["priority"]]
    chans = "".join(f'<div><b>{i}</b>{CH_NAME[c["channel"]]}'
                    + (f'<small>then wait {c["wait_hours"]} h</small>' if c.get("wait_hours") else "") + "</div>"
                    for i, c in enumerate(h["channel_order"], 1))
    cap = h["frequency_cap"]
    decision, reason = admits.get(h["handoff_id"], ("sent", ""))
    cap_state = ("Exempt (high priority)" if cap["exempt"] else {
        "sent": "✓ Within the limit", "moved": f"↷ Moved: {reason}", "merged": f"⊕ Merged: {reason}",
        "skipped": "⚠ Skipped: this farmer already has a survey that week", "opted_out": "Farmer opted out"}[decision])
    status = {"sent": badge("Ready to send"), "moved": badge("Moved by weekly limit", "amber"),
              "merged": badge("Merged by weekly limit", "amber"), "skipped": badge("Skipped by weekly limit", "red"),
              "opted_out": badge("Opted out", "red")}[decision]
    html(f'''<div class="mel-card"><div><b>Scheduler hand-off</b> {status}</div><br><div class="mel-strip">
<div><div class="mel-k">Recommended send</div><b>{long(send_time["send_at"])}</b>
<div class="mel-note">{escape(us_text(send_time["reason"]))}</div></div>
<div><div class="mel-k">Send window ({ZONE_LABEL})</div><b>{short(h["send_window"]["not_before"])} → {short(h["send_window"]["not_after"])}</b>
<div class="mel-tl"><i class="w" style="left:0;width:{w:.0f}%"></i><i class="x" style="left:{w:.0f}%;width:{100 - w:.0f}%;opacity:.45"></i></div>
<div class="mel-tlab"><span>Opens</span><span>Closes</span><span>Expires {short(h["expires_at"])}</span></div></div>
<div class="mel-ch"><div class="mel-k">Channel order</div>{chans}</div>
<div><div class="mel-k">Priority</div>{badge(h["priority"].title(), tone)}</div>
<div><div class="mel-k">Weekly limit</div><b>{cap["max_surveys"]} per farmer in {cap["window_days"]} days</b>
<div class="mel-note">{escape(cap_state)}</div></div>
<div><div class="mel-k">Hand-off ID</div><span class="mel-id">{h["handoff_id"]}</span></div></div></div>''')


SOURCE_NAME = {"template": "Template", "llm": "Claude"}
FU_LABEL = {"advice_did_not_work": "advice didn't work", "crop_or_animal_damaged": "crop / animal damaged",
            "could_not_get_input": "couldn't get inputs", "could_not_reach_expert": "couldn't reach expert"}
STATUS_TONE = {"completed": "green", "partial": "amber", "negative_outcome": "red"}


def record_card(rec):
    """What the preview's real taps produced (P3's simulator builds the record; no answer is invented).
    The record is shown, not stored: the Follow-up queue tab is built separately from the batch."""
    html(f'''<div class="mel-card"><div><b>Answer record</b>
{badge(rec["status"].replace("_", " ").capitalize(), STATUS_TONE.get(rec["status"], "slate"))}</div><br><div class="mel-strip">
<div><div class="mel-k">Counts toward weekly limit</div><b>{"Yes" if rec["counts_toward_cap"] else "No"}</b></div>
<div><div class="mel-k">Next step</div><b>{escape(str(rec["retry_decision"]).replace("_", " ").capitalize())}</b></div></div></div>''')
    if rec["needs_follow_up"]:
        st.error("Requires follow-up: " + ", ".join(FU_LABEL.get(r, r) for r in rec["follow_up_reasons"]))
    if rec["failure_code"]:
        st.warning(f"Failure: {rec['failure_code']}")


# One pick per insight severity (high / medium / low) plus the no-survey edge case; first one is the default.
DEMO_PICKS = {"I-001253": "High — Goat veterinary follow-up", "I-001645": "Medium — Lentil nutrient care",
              "I-005625": "Low — Stored mustard monitoring", "I-000291": "Edge case — No survey (critical cow)"}
BROWSE = "Browse all conversations"
PRETEND = ["none", "said the input was not available nearby", "said it was too costly", "ignored the last 3 surveys"]



EDITOR_KEYS = {"question": "cc_question", "advice": "cc_advice", "asset": "cc_asset", "concern": "cc_concern",
               "severity": "cc_severity", "resolution": "cc_resolution", "days": "cc_days", "check": "cc_check",
               "channel": "cc_channel", "language": "cc_language", "district": "cc_district"}


def _sync_draft() -> dict:
    """Editor widgets -> draft. Streamlit drops a widget's key once it is not rendered (editor hidden, demo shown),
    so the draft in session state is what survives; the widgets are re-seeded from it when the editor reopens."""
    draft = st.session_state.setdefault("custom_draft", dict(cc.DEFAULTS))
    for field, wkey in EDITOR_KEYS.items():
        if wkey in st.session_state:
            draft[field] = st.session_state[wkey]
    return draft


def _open_own():
    st.session_state.update(studio_source="own", editor_open=True)


def _show_own():
    st.session_state.update(studio_source="own", editor_open=False)


def _toggle_editor():
    st.session_state["editor_open"] = not st.session_state.get("editor_open", False)


def _back_to_demos():
    st.session_state.update(studio_source="demo", editor_open=False)


def own_insight_editor(draft: dict) -> bool:
    """The editor for the user's own insight (app/custom_context.py does the mapping). Drawn only while open.
    Returns True right after a valid submission; the pipeline runs only then, never on reopen or rerender."""
    for field, wkey in EDITOR_KEYS.items():
        st.session_state.setdefault(wkey, draft[field])  # re-seed from the draft (keys are gone after hiding)
    with st.container(border=True, key="own_editor"):
        st.caption("Type a FarmerChat conversation, then check the Details: those values decide the survey, not the "
                   "text. The same rules, writer and checks run on it, and nothing you type joins the numbers.")
        t = st.columns(2)
        t[0].text_area("What the farmer asked", key="cc_question", height=96,
                       placeholder="Small green insects on the mustard flowers, what should I do?",
                       help="Shown on the green card as typed.")
        t[1].text_area("Advice FarmerChat gave", key="cc_advice", height=96,
                       placeholder="Spray neem oil in the evening and check the plants after three days.",
                       help="Leave empty if no advice was given yet: there is nothing to check, so no survey. No model "
                            "reads the text in this demo; the questions follow the Details, plus a few keywords in the advice.")
        with st.expander("Details: crop, problem, severity, advice type, timing, channel, language, district"):
            d = st.columns([1.1, 1.3, 1, 1.7])
            d[0].selectbox("Crop or animal", list(cc.ASSETS), key="cc_asset", format_func=str.title)
            d[1].selectbox("Problem", list(cc.CONCERNS), key="cc_concern", format_func=cc.CONCERNS.get)
            d[2].selectbox("Severity", list(cc.SEVERITY), key="cc_severity", format_func=cc.SEVERITY.get)
            d[3].selectbox("Advice type", list(cc.ADVICE_TYPES), key="cc_resolution", format_func=cc.ADVICE_TYPES.get)
            e = st.columns([1, 1.3, 1.3, 1, 1.2])
            e[0].number_input("Act within (days)", 0, 60, key="cc_days")
            e[1].selectbox("Check back later?", list(cc.CHECK_BACK), key="cc_check", format_func=cc.CHECK_BACK.get)
            e[2].selectbox("Farmer's usual channel", CHANNELS, key="cc_channel", format_func=CH_NAME.get)
            e[3].selectbox("Farmer's language", list(cc.LANGUAGES), key="cc_language", format_func=cc.LANGUAGES.get)
            e[4].text_input("District (Bihar)", key="cc_district")
            st.caption(f"Dates show in {ZONE_LABEL}. The conversation is stamped with the real current time; the rules "
                       "use Digital Green's rabi 2026-27 calendar for India, so send windows must fall before 03/31/2027, "
                       "between 7:00 AM and 7:00 PM India time.")
        fields = _sync_draft()  # the widgets exist now: read them back into the draft
        resolution, note = cc.effective_resolution(fields)
        b = st.columns([3, 1], vertical_alignment="center")
        b[0].caption(f"Survey will be built for: {fields['asset'].title()}, {cc.CONCERNS[fields['concern']].lower()}, "
                     f"{cc.SEVERITY[fields['severity']].lower()} severity, "
                     f"{'no advice given yet' if note else cc.ADVICE_TYPES[resolution].lower()}.")
        submitted = b[1].button("Preview the survey", key="custom_submit", type="primary", width="stretch")
    if not submitted:
        return False
    problems = cc.validate(fields)
    if problems:  # the editor stays open with the errors; an earlier report must not pose as this submission
        for problem in problems:
            st.error(problem)
        if st.session_state.pop("custom_submission", None):
            st.info("The earlier report was closed because the form no longer matches it. Fix the fields and press "
                    "Preview the survey again.")
        return False
    n = st.session_state.get("custom_count", 0) + 1  # new ids (so the phone starts fresh), the time frozen now,
    st.session_state["custom_count"] = n  # and the pipeline run once
    sub = cc.submission(fields, n)
    sub["out"] = run_insight(sub["insight"], memory=memory())
    st.session_state["custom_submission"] = sub
    st.session_state["editor_open"] = False
    return True


@st.cache_data(show_spinner=False)
def _tts(text: str) -> bytes | None:
    """One ElevenLabs call per distinct line; reruns and repeated taps replay the cached audio."""
    return tts.speak(text)


def voice_readout(sv: dict, preview_key: str, rec):
    """Read aloud what the farmer hears on the call: the greeting, then each question as it comes up, then the
    closing line. ElevenLabs text to speech, multilingual; nothing is sent to a farmer."""
    if not st.toggle("Read the call aloud", key="tts_on", help="ElevenLabs text to speech (Hindi and English). "
                                                                 "Needs ELEVENLABS_API_KEY; see .env.example."):
        return
    if not tts.api_key():
        st.caption("Add ELEVENLABS_API_KEY to the repo's .env (copy .env.example) and rerun to hear the call.")
        return
    state, vo = st.session_state.get(f"mel_preview|{preview_key}"), render(sv, "voice")
    if state is None or state.stage == "invite":
        line = vo["opening"]
    elif state.done:
        line = (vo["closing_if_follow_up"] if rec and rec["needs_follow_up"] else vo["closing"]) if state.ending == "finished" else ""
    else:
        line = vo["items"][state.step]["say"]
    if not line:
        return  # the farmer ended the call; nothing more is spoken
    try:
        audio = _tts(line)
    except tts.TTSError as e:
        st.caption(f"ElevenLabs did not answer: {e}")
        return
    if audio:
        st.audio(audio, format="audio/mpeg", autoplay=True)


def report_strip(kicker: str, title: str, note: str = ""):
    """The report's title line: what this insight is, plus the submission time for an own insight."""
    html(f'<div class="mel-report"><div><div class="mel-kicker{" own" if kicker == "Your insight" else ""}">{escape(kicker)}'
         f'</div><h2>{escape(title)}</h2></div>' + (f'<div class="mel-sum">{escape(note)}</div>' if note else "") + '</div>')


with tab_studio:
    by_id = {i.get("insight_id"): (i, o) for i, o in rows}
    picks = {k: v for k, v in DEMO_PICKS.items() if k in by_id}
    st.session_state.setdefault("studio_source", "demo")
    st.session_state.setdefault("editor_open", False)
    draft = _sync_draft()
    sub = st.session_state.get("custom_submission")
    own = st.session_state["studio_source"] == "own"
    # Toolbar: the source on the left (demo picker, or the own-insight label while own mode is on), the user's
    # own insight on the right, never inside the dropdown.
    bar = st.columns([2.4, 1, 1], vertical_alignment="bottom")
    if own:
        pick = None
        a0 = (sub["insight"].get("asset") or {}) if sub else {}
        what = (f"{str(a0.get('name') or '').title()}: {str(sub['insight'].get('concern') or '').replace('_', ' ')}"
                if sub else "draft, no report yet")
        bar[0].markdown(f'<div class="mel-source"><div class="mel-k">Source</div><b>Your insight</b>'
                        f'<span>{escape(what)}</span></div>', unsafe_allow_html=True)
        bar[1].button("Hide editor" if st.session_state["editor_open"] else "Edit insight", key="own_toggle",
                      icon=":material/edit:", on_click=_toggle_editor, width="stretch")
        bar[2].button("Back to the demos", key="own_back", on_click=_back_to_demos, width="stretch")
    else:
        # The picker's widget key is dropped while own mode hides it; last_pick (plain state) brings it back.
        st.session_state.setdefault("studio_pick", st.session_state.get("last_pick", next(iter(picks), BROWSE)))
        pick = bar[0].selectbox("Demo picks", [*picks, BROWSE], key="studio_pick", format_func=lambda k: picks.get(k, k))
        st.session_state["last_pick"] = pick
        if sub:
            bar[1].button("Your insight", key="own_show", icon=":material/person:", on_click=_show_own, width="stretch")
        bar[2].button("Add your own insight", key="own_add", type="primary", icon=":material/add:", on_click=_open_own,
                      width="stretch")
    kicker, title, note = "Selected insight", "", ""
    if own:
        if st.session_state["editor_open"] and own_insight_editor(draft):
            st.rerun()  # redraw with the editor collapsed and the new report below the toolbar
        sub = st.session_state.get("custom_submission")
        ins, out = (sub["insight"], sub["out"]) if sub else (None, None)
        if sub:
            a0 = sub["insight"].get("asset") or {}
            kicker, title = "Your insight", f"{str(a0.get('name') or '').title()}: {str(sub['insight'].get('concern') or '').replace('_', ' ')}"
            note = f"Submitted {long(sub['insight']['created_at'])}." + (f" {sub['note']}" if sub["note"] else "")
        elif not st.session_state["editor_open"]:  # hidden before any report exists: say what to do next
            st.info("Your insight has no report yet. Press Edit insight to finish it, or pick a demo above.")
    elif pick != BROWSE:
        ins, out = by_id[pick]
        kicker, title = "Demo insight", picks[pick]
    else:
        f = st.columns(4)
        f_dec = f[0].selectbox("Decision", ["All", "Survey", "No survey"])
        f_rule = f[1].selectbox("Rule", ["All", *RULE_LABEL], format_func=lambda r: r if r == "All" else f"{r} {RULE_LABEL[r]}")
        f_res = f[2].selectbox("Advice type", ["All", *sorted({str(i.get("resolution_type")) for i, _ in rows})])
        f_asset = f[3].selectbox("Crop / animal", ["All", *sorted({str((i.get("asset") or {}).get("name")) for i, _ in rows})])
        shown = [k for k, (i, o) in labels.items()
                 if (f_dec == "All" or (f_dec == "Survey") == o["decision"].survey)
                 and (f_rule == "All" or o["decision"].rule == f_rule)
                 and (f_res == "All" or str(i.get("resolution_type")) == f_res)
                 and (f_asset == "All" or str((i.get("asset") or {}).get("name")) == f_asset)]
        if not shown:  # never st.stop() here: it would also stop the tabs after this one
            st.warning("No conversations match these filters; showing all.")
            shown = list(labels)
        key = st.selectbox(f"Conversation ({len(shown):,} match; type to search)", shown)
        ins, out = labels[key]
        a0 = ins.get("asset") or {}
        kicker, title = "Browsed insight", f"{str(a0.get('name') or '').title()}: {str(ins.get('concern') or '').replace('_', ' ')} ({ins.get('insight_id')})"
    if ins is not None:
        report_strip(kicker, title, note)
        d = out["decision"]
        a = ins.get("asset") or {}
        mem, pretend, restart = None, "none", False
        if d.survey:
            # One settings bar for everything that changes what the farmer sees in the preview. History rules
            # H1-H4 are always on here (team decision 4 Nov); scoring and the CLI keep them off.
            bar = st.columns([2.3, 1, 0.5, 2.7], vertical_alignment="bottom")
            # Icon-only: the label is the accessible name, hidden visually by app/theme.py (.st-key-studio_restart).
            restart = bar[2].button("Restart survey", key="studio_restart", icon=":material/restart_alt:",
                                    width="content", help="Restart survey")
            pretend = bar[3].selectbox("Pretend this farmer's survey history (demo)", PRETEND)
            mem = copy.copy(memory())
            mem.responses = __import__("collections").defaultdict(list)
            when = lambda days: (datetime.fromisoformat(ins["created_at"]) - __import__("datetime").timedelta(days=days)).isoformat()
            fake = lambda status, ans, days=2: {"farmer_id": ins["farmer_id"], "status": status, "answers": ans,
                                                "recorded_at": when(days), "counts_toward_cap": True}
            if pretend.startswith("said the input"):
                mem.record_response(fake("completed", {"q1": "no", "q3": "not_nearby"}))
            elif pretend.startswith("said it was too"):
                mem.record_response(fake("completed", {"q1": "no", "q3": "too_costly"}))
            elif pretend.startswith("ignored"):
                for days in (6, 4, 2):
                    mem.record_response(fake("expired", {}, days))
            if pretend != "none":  # the batch was built with history on and no answers yet
                surveys_now = write_surveys(ins, d.send_window, memory=mem)
                farmer_copy = clean(surveys_now.get(ins["conversation_language"]) or surveys_now["hi-IN"])
                out = {**out, "surveys": surveys_now, "handoff": build_handoff(ins, farmer_copy)}
            h = out["handoff"]
            first_ch = h["channel_order"][0]["channel"]  # P2's recommended send time is for this channel
            ch = bar[0].segmented_control("Channel", CHANNELS, default=first_ch, required=True, format_func=CH_NAME.get,
                                          wrap=True)  # wrap instead of a sideways scroll on narrow screens
            # English by default so judges can read along; Hindi is one tap away. A widget keeps the choice across
            # the reruns that every tap on the phone causes.
            langs = list(out["surveys"])
            lang = bar[1].segmented_control("Language", langs, default="en-IN" if "en-IN" in langs else langs[0],
                                            required=True, format_func=lambda l: LANG_NAME.get(l, l))
        sev_tone = {"critical": "red", "high": "red", "medium": "amber"}.get(ins.get("severity"), "slate")
        why = us_text(out["surveys"][ins["conversation_language"]]["rationale"] if d.survey
                      else re.sub(r"^\[[^\]]*\]\s*", "", out["no_survey"]["reason"]))  # drop the "[R5 code]" prefix
        col_i, col_p, col_m = st.columns([1, 1.6, 0.8], gap="medium")
        col_i.markdown('<div class="mel-sec">Conversation</div>', unsafe_allow_html=True)
        col_p.markdown('<div class="mel-sec">What the farmer sees</div>', unsafe_allow_html=True)
        col_m.markdown('<div class="mel-sec">Plan and checks</div>', unsafe_allow_html=True)
        with col_i:
            html(f'''<div class="mel-insight"><div class="mel-eyebrow">{"Your insight" if kicker == "Your insight" else "Selected insight"}
    {badge((ins.get("severity") or "n/a").title() + " severity", sev_tone)}</div>
    <h3>{escape(str(a.get("name") or "—").title())} · {escape(str(ins.get("concern") or "").replace("_", " "))}</h3>
    <div class="f"><span>Farmer asked</span>“{escape(ins.get("query_summary") or "—")}”</div>
    <div class="f"><span>Advice given</span>“{escape(ins.get("advice_summary") or "—")}”</div>
    <div class="mel-meta"><div><span>Farmer</span>{ins.get("farmer_id")}</div><div><span>Insight</span>{ins.get("insight_id")}</div>
    <div><span>Growth stage</span>{escape(str(a.get("growth_stage") or "—").replace("_", " "))}</div>
    <div><span>Resolution</span>{escape(str(ins.get("resolution_type") or "—").replace("_", " "))}</div></div>
    <div class="mel-why">{"Why this survey?" if d.survey else f"Why no survey? ({d.rule})"}<p>{escape(why)}</p></div></div>''')
            if mem is not None:
                notes = [(r, us_text(w)) for r, w in history_notes(ins, mem)]
                lines = [us_text(x) for x in summary_lines(build_context(ins, mem))]
                html('<div class="mel-card"><b>What the agent remembers</b><ul>'
                     + "".join(f"<li>{escape(x)}</li>" for x in lines) + "</ul>"
                     + ("".join(f'<p>{badge(r, "amber")} {escape(w)}</p>' for r, w in notes)
                        if notes else '<p class="mel-note">Nothing in the history changes this survey, so the generic '
                                      'questions are used.</p>') + "</div>")
        if not d.survey:
            with col_p:
                st.info(f"No survey for this conversation: {d.rule} {RULE_LABEL[d.rule]}. Pick a demo, or browse with "
                        "Decision set to Survey, to try the channel preview.")
                with st.expander("Developer details: no-survey record (JSON)"):
                    st.json(out["no_survey"])
        else:
            surveys = out["surveys"]
            sv = clean(surveys[lang])
            with col_p:
                # restart=True resets the phone before it is drawn; show_restart=False hides the phone's own
                # "Start over", so the settings bar's Restart is the only reset control.
                pkey = f"preview|{ins['insight_id']}|{ch}|{lang}|{pretend}|{mem is not None}"
                rec = render_channel_preview(sv, ch, key=pkey, send_at=d.send_time["send_at"] if ch == first_ch else None,
                                             restart=restart, show_restart=False)
                if ch == "voice":
                    voice_readout(sv, pkey, rec)
            with col_m:
                handoff_card(h, d.send_time)
                tags = [badge(SOURCE_NAME.get(x, x), "amber") for x in sorted({s.get("_source") for s in surveys.values()})]
                if surveys[lang].get("_history"):
                    tags.append(badge("Personalised by " + ", ".join(r for r, _ in surveys[lang]["_history"])))
                n_q = len(sv["items"])
                html(f'<div class="mel-card"><div><b>Survey checks</b> {" ".join(tags)}</div>'
                     f'<div class="mel-note">{n_q} tap question{"s" if n_q != 1 else ""}, written in Hindi and English</div>'
                     f'{guard_ticks(surveys)}</div>')
                if rec is None:
                    st.caption("Your submitted answers appear here when the conversation ends.")
                else:
                    record_card(rec)
            if surveys[lang].get("_history"):
                generic = write_surveys(ins, d.send_window)[lang]["items"]
                with st.expander(f"Generic vs adapted questions ({LANG_NAME.get(lang, lang)})"):
                    n_rows = max(len(generic), len(sv["items"]))
                    table(pd.DataFrame([{
                        "#": k + 1,
                        "Generic (no history)": generic[k]["prompt"] if k < len(generic) else "(none)",
                        "Adapted to this farmer": sv["items"][k]["prompt"] if k < len(sv["items"]) else "(none)"}
                        for k in range(n_rows)]), hide_index=True, width="stretch")
            with st.expander("Developer details: survey, channel payload, hand-off and answer record (JSON)"):
                st.caption(f"Survey ({LANG_NAME.get(lang, lang)})")
                st.json(sv, expanded=False)
                st.caption(f"{CH_NAME[ch]} payload (mel.channels.render)")
                st.json(render(sv, ch), expanded=False)
                st.caption("Scheduler hand-off")
                st.json(h, expanded=False)
                if rec is None:
                    st.caption("Answer record: not yet (the preview is still open)")
                else:
                    bad = errors("response", rec)
                    st.caption("Answer record " + ("passes the response schema ✓" if not bad else f"FAILS the response schema: {bad[:2]}"))
                    st.json(rec, expanded=False)

# ---------------------------------------------------------------- Follow-up queue
# A ⚑ answer means the advice failed, harm happened, or the farmer couldn't act on it. Those answers
# don't just get recorded — they route back to FarmerChat so staff can follow up with the farmer.
# Owner: P5. Mock data only flags q1 on a few surveys, so each survey is simulated with its first ⚑
# answer forced (other questions held to a safe answer) to show the full queue the system can produce.
FU_REASON = {
    "advice_did_not_work": "Advice didn't work",
    "crop_or_animal_damaged": "Crop / animal damaged",
    "could_not_get_input": "Couldn't get inputs",
    "could_not_reach_expert": "Couldn't reach expert",
}
FU_ACTION = {
    "advice_did_not_work": "Re-check the advice and send a corrected recommendation.",
    "crop_or_animal_damaged": "Assess the damage; connect the farmer to a vet or extension worker.",
    "could_not_get_input": "Share the nearest input supplier or an available subsidy.",
    "could_not_reach_expert": "Book a call with the nearest agriculture expert.",
}


def _answer_label(item_def, value):
    if item_def["type"] == "survey-scale":
        return f"{value}/{item_def.get('scale_max', '?')}"
    return next((o["label"] for o in item_def.get("options", []) if o["value"] == value), str(value))


def _safe_value(item_def):
    """A non-follow-up answer, so a ticket stays focused on the one flagged answer."""
    if item_def["type"] == "survey-scale":
        return item_def.get("scale_max", 5)
    for o in item_def.get("options", []):
        if not o.get("follow_up"):
            return o["value"]
    return item_def.get("options", [{}])[0].get("value")


def _first_trigger(survey):
    """First (item_id, value, reason) that flags follow-up, scanning questions in order."""
    for it in survey["items"]:
        if it["type"] == "survey-scale":
            lim = it.get("follow_up_at_or_below")
            if lim is not None:
                return it["item_id"], lim, it.get("follow_up_reason")
        else:
            for o in it.get("options", []):
                if o.get("follow_up"):
                    return it["item_id"], o["value"], o["follow_up"]
    return None


@st.cache_data(show_spinner="Building follow-up queue…")
def _follow_queue():
    """One follow-up ticket per survey: force the survey's first ⚑ answer (others kept safe), so the
    queue shows every trouble answer the system routes back to FarmerChat. Deterministic: seed 0."""
    tickets = []
    for ins, out in rows:
        if not (out["decision"].survey and "handoff" in out):
            continue
        h, survey = out["handoff"], out["handoff"]["survey"]
        ch = h["channel_order"][0]["channel"]
        trig = _first_trigger(survey)
        if not trig:
            continue
        t_item, t_val, t_reason = trig
        answers = {it["item_id"]: t_val if it["item_id"] == t_item else _safe_value(it)
                   for it in survey["items"]}
        rec = simulate(survey, ch, "completed", seed=0, answers=answers, send_at=out["decision"].send_time["send_at"])
        if not rec["needs_follow_up"]:
            continue
        t_def = next(it for it in survey["items"] if it["item_id"] == t_item)
        a = ins.get("asset") or {}
        tickets.append({
            "response_key": rec["response_key"], "farmer_id": rec["farmer_id"],
            "asset": a.get("name"), "concern": ins.get("concern"),
            "survey_id": rec["survey_id"], "channel": ch, "recorded_at": rec["recorded_at"],
            "reason": t_reason, "item_id": t_item, "prompt": t_def.get("prompt", ""),
            "answer": _answer_label(t_def, t_val), "rec": rec, "insight": ins, "survey": survey,
        })
    return tickets


def ticket_card(t):
    """One farmer's follow-up: the next step, then the conversation log it came from (the insight's summaries,
    then the survey questions and the answers in the record; the flagged answer is marked)."""
    ins, a, rec = t["insight"], t["insight"].get("asset") or {}, t["rec"]
    what = f'{str(a.get("name") or "—").title()}, {str(ins.get("concern") or "").replace("_", " ")}'
    html(f'''<div class="mel-card"><p>{badge("⚑ " + FU_REASON[t["reason"]], "red")}</p>
<div class="mel-k">Next step</div><div class="mel-lead">{escape(FU_ACTION[t["reason"]])}</div>
<div class="mel-note">Farmer {escape(t["farmer_id"])}, {escape(what)}. Survey <span class="mel-id">{t["survey_id"]}</span>
on {CH_NAME.get(t["channel"], t["channel"])}.</div></div>''')
    st.markdown(f"**Conversation log** ({ZONE_LABEL})")
    got = {e["item_id"]: e["value"] for e in rec["items"] if e["result"] == "answered"}
    with st.chat_message("user"):
        st.caption(f"{short(ins['created_at'])}. The farmer asked (summary):")
        st.write(ins.get("query_summary") or "—")
    with st.chat_message("assistant"):
        st.caption("FarmerChat advised (summary):")
        st.write(ins.get("advice_summary") or "—")
        st.caption(f"Survey sent {short(rec['timestamps']['sent'])} on {CH_NAME.get(t['channel'], t['channel'])}.")
    for it in t["survey"]["items"]:
        with st.chat_message("assistant"):
            st.write(it["prompt"])
        if it["item_id"] in got:
            with st.chat_message("user"):
                flag = f" ⚑ {FU_REASON[t['reason']]}" if it["item_id"] == t["item_id"] else ""
                st.markdown(f"**{_answer_label(it, got[it['item_id']])}**{flag}")
    st.caption(f"Answer recorded {short(t['recorded_at'])}.")
    with st.expander("Full answer record (JSON)"):
        st.json(rec)


with tab_follow:
    tickets = sorted(_follow_queue(), key=lambda t: t["recorded_at"])  # a queue: oldest answer first
    st.caption("Farmers whose answer says the advice failed, the crop or animal was harmed, or they could not act "
               "on it. Pick one with the circle at the start of its row to see the next step and the conversation. "
               "Simulated: one trouble answer per survey.")
    if not tickets:
        st.info("No survey in this run can produce a follow-up flag.")
    else:
        rc = Counter(t["reason"] for t in tickets)
        present = {t["channel"] for t in tickets}
        f1, f2 = st.columns([3, 2])
        reason = f1.segmented_control(
            "Why they need a follow-up", ["all", *[k for k in FU_REASON if rc.get(k)]], default="all", required=True, wrap=True,
            format_func=lambda k: f"All ({len(tickets):,})" if k == "all" else f"{FU_REASON[k]} ({rc.get(k, 0):,})")
        chan = f2.segmented_control("Channel", ["all", *[c for c in CHANNELS if c in present]], default="all",
                                    required=True, wrap=True, format_func=lambda c: CH_NAME.get(c, "All"))
        view = [t for t in tickets if reason in ("all", t["reason"]) and chan in ("all", t["channel"])]
        if not view:
            st.warning("No farmer has this reason on this channel. Pick All on one of the filters.")
        else:
            left, right = st.columns([1.35, 1], gap="medium")
            with left:
                ev = table(pd.DataFrame([{
                    "Farmer": t["farmer_id"],
                    "Crop / animal": str(t["asset"] or "—").title(),
                    "Why": FU_REASON.get(t["reason"], t["reason"]),
                    "Answer": t["answer"],
                    "Channel": CH_NAME.get(t["channel"], t["channel"]),
                    "Answered": t["recorded_at"],
                } for t in view]), width="stretch", hide_index=True, height=460, on_select="rerun",
                    selection_mode="single-row-required", key=f"fu_rows|{reason}|{chan}")  # new filter, first row
                st.caption(f"{len(view):,} farmers, oldest answer first.")
            picked = ev.selection.rows
            with right:
                ticket_card(view[picked[0]] if picked and picked[0] < len(view) else view[0])

# ---------------------------------------------------------------- Evaluation (second half of "Dashboard")
# Digital Green's five dimensions (relevance, timeliness, format, safety, speed) next to our decision and
# rule accuracy, under either send-time rule, plus the run history that shows each improvement.
BASIS_LABEL = {"brief": "Brief rules (default)", "answer_key": "Answer-key setting"}
DIMENSIONS = {"decision_acc": "Decision", "rule_acc": "Rule", "window_acc": "Window match",
              "timeliness_pass": "Timeliness", "format_pass": "Format", "safety_pass": "Safety",
              "item_similarity_avg": "Item similarity", "relevance_avg": "Relevance (P4)",
              "judge_relevance": "Relevance (AI judge)", "s_per_survey": "Seconds per survey"}


@st.cache_data(show_spinner="Scoring the answer key and checking every survey in the full dataset…")
def _evaluate(basis):
    return evaluate(basis)


def _pct(v):
    return "—" if v is None else f"{v:.1%}"


with tab_over:
    st.divider()
    st.header("Evaluation")
    basis = st.radio("Send-time rule", list(BASIS_LABEL), format_func=BASIS_LABEL.get, horizontal=True,
                     help="P2 built both. Brief rules = Digital Green's written brief (7:00 AM India time, after the farmer's "
                          "action window). Answer-key setting = what the 150-case answer key expects.")
    res = {b: _evaluate(b) for b in BASIS_LABEL}
    r = res[basis]
    src, card = r["full"] or r["mock"], r["card"]

    st.subheader("Answer key")
    st.caption(f"{'Full pack' if r['full'] else 'Mock subset'}: {src['n']} cases with the right answer. "
               f"Mock subset ({r['mock']['n']} rows): decision {r['mock']['decision_acc']:.1%}, "
               f"window {r['mock']['window_acc']:.1%}.")
    g = st.columns(5)
    g[0].metric("Decision", _pct(src["decision_acc"]), "survey or not", delta_color="off", delta_arrow="off")
    g[1].metric("Rule", _pct(src["rule_acc"]), "which of R1–R8", delta_color="off", delta_arrow="off")
    g[2].metric("First channel", _pct(src["channel_acc"]))
    g[3].metric("Window match", _pct(src["window_acc"]), "exact, vs answer key", delta_color="off", delta_arrow="off")
    g[4].metric("Item similarity", f"{src['item_similarity_avg']:.2f}", "keyword overlap", delta_color="off", delta_arrow="off")

    st.subheader("Every survey we write")
    st.caption(f"Checks on all {card['n_survey_files']:,} survey files (Hindi + English) from "
               f"{card['n_insights']:,} insights → {card['n_surveyed']:,} surveys. No answer key needed.")
    q = st.columns(6)
    q[0].metric("Format", _pct(card["format_pass"]), "schema, 1–3 tap items, language", delta_color="off", delta_arrow="off")
    q[1].metric("Safety", _pct(card["safety_pass"]), "no new advice or personal info", delta_color="off", delta_arrow="off")
    q[2].metric("Timeliness", _pct(card["timeliness_pass"]), "after action window, daytime, in season",
                delta_color="off", delta_arrow="off")
    jr = card.get("judge_relevance")
    q[3].metric("Relevance", f"{card['relevance_avg']:.2f}",
                "P4 score, 0–1. AI judge: " + ("not run" if jr is None else f"{jr:.2f} / 5"), delta_color="off", delta_arrow="off")
    q[4].metric("Speed", f"{card['s_per_survey'] * 1000:.1f} ms", f"per survey, {card['batch_seconds']:.0f} s for all",
                delta_color="off", delta_arrow="off")
    q[5].metric("Failing but scheduled", card["failed_but_scheduled"], "target 0", delta_color="off", delta_arrow="off")
    for title, ex_rows in ((f"Surveys that failed format or safety (first {len(card['examples'])})", card["examples"]),
                        (f"Send windows that failed timeliness (first {len(card['timeliness_examples'])})",
                         card["timeliness_examples"])):
        if ex_rows:
            with st.expander(title):
                table(pd.DataFrame(ex_rows), width="stretch", hide_index=True)

    st.subheader("Brief rules vs answer-key setting")
    st.caption("Matching the answer key's send times costs timeliness: most of its windows open before the "
               "farmer could have acted on the advice. We keep the brief as the default until Digital Green confirms.")
    cmp = []
    for b, rr in res.items():
        gg, cc = rr["full"] or rr["mock"], rr["card"]
        cmp.append({"Send-time rule": BASIS_LABEL[b], "Decision": _pct(gg["decision_acc"]),
                    "Window match": _pct(gg["window_acc"]), "Timeliness": _pct(cc["timeliness_pass"]),
                    "Surveys": f"{cc['n_surveyed']:,}", "Misses": len(gg["misses"])})
    table(pd.DataFrame(cmp), width="stretch", hide_index=True)

    st.subheader("Run history")
    hist = load_history()
    if not hist:
        st.info('No recorded runs yet. Run `python scripts/readme_numbers.py --write --record "what changed"`.')
    else:
        st.caption("Each recorded eval run: what we changed and what it did to the scores (the hill-climb).")
        changed = rules_changed(hist)
        if changed:
            st.markdown("**Rules we changed**")
            st.caption("Each run is compared with the last run under the same send-time rule.")

            def _chg(pair, f):
                a, b = (("—" if v is None else f(v)) for v in pair)
                return b if a == b else f"{a} → {b}"

            def _n(v):
                return f"{v:.2f}" if isinstance(v, float) else str(v)

            table(pd.DataFrame([{
                "Run": f"{c['run']} (vs {c['vs_run']})", "What changed": c["change"],
                "Send-time rule": BASIS_LABEL.get(c["timing_basis"]),
                **{lab: _chg(c[k], _pct) for k, lab in (("decision_acc", "Decision"), ("window_acc", "Window match"),
                                                       ("timeliness_pass", "Timeliness"))},
                "Item sim": _chg(c["item_similarity_avg"], _n), "Relevance (P4)": _chg(c["relevance_avg"], _n),
                "Misses": _chg(c["misses"], _n)} for c in changed]),
                width="stretch", hide_index=True)
        hd = pd.DataFrame(hist)
        avail = [k for k in DIMENSIONS if k in hd and hd[k].notna().any()]
        dims = st.multiselect("Dimensions to chart", avail, default=[k for k in ("decision_acc", "window_acc",
                              "timeliness_pass") if k in avail], format_func=DIMENSIONS.get)
        if len(hd) > 1 and dims:
            st.line_chart(hd.set_index("run")[dims].rename(columns=DIMENSIONS), height=220)
        with st.expander("All recorded runs"):
            table(hd, width="stretch", hide_index=True)

    with st.expander("Per-rule confusion matrix"):
        st.caption("Rows = expected rule, columns = our prediction. Diagonal = correct.")
        rule_ids = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
        df = pd.DataFrame(src["confusion"], index=rule_ids)[rule_ids]
        df.index.name = "expected → predicted"
        table(df, width="stretch")

    if src["item_similarities"]:
        with st.expander(f"Item similarity per case (avg {src['item_similarity_avg']:.2f})"):
            st.caption("Keyword overlap between our questions and the golden set's expected questions")
            table(pd.DataFrame(src["item_similarities"]), width="stretch", height=150)

    st.subheader("Misses")
    if src["misses"]:
        table(pd.DataFrame(src["misses"]), width="stretch", height=200)
    else:
        st.success("No misses — every decision and rule matches.")
