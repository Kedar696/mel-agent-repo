"""Fasal Pulse - MEL Survey Agent: the team demo. Owner: P5.  Run: streamlit run app/streamlit_app.py
P4's standalone survey demo (demo/p4_standalone) is folded in: Survey demo shows what the agent remembers
about the farmer and how history rules H1-H5 adapt the survey (on in the app, off for scoring).
Tabs: Dashboard (default: overview + evaluation), Survey demo (insight | interactive channel preview | hand-off),
Follow-up queue. Look and feel: app/theme.py. Interactive preview: app/channel_preview.py.
Every number on screen comes from the real pipeline; nothing is hard-coded."""
import copy
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
import streamlit.components.v1 as components


def _reload_mel_if_changed():
    """Streamlit reruns this file when code changes (local `git pull`, or Streamlit Cloud pulling a merge),
    but keeps already-imported packages in memory, so new mel/ code would not be used and calls fail with
    'unexpected keyword argument'. The loaded `mel` package is marked with the code timestamp it came from;
    if it has no mark (loaded by an older version of this app) or an older one, drop the old modules and
    cached results so everything below is imported and computed fresh."""
    stamp = max(p.stat().st_mtime for p in (Path(__file__).resolve().parents[1] / "mel").rglob("*.py"))
    loaded = sys.modules.get("mel")
    if loaded is not None and getattr(loaded, "_code_stamp", None) != stamp:
        for name in [m for m in sys.modules if m == "mel" or m.startswith("mel.")]:
            del sys.modules[name]
        st.cache_data.clear()
        st.cache_resource.clear()
    return stamp


_MEL_STAMP = _reload_mel_if_changed()

from mel.channels import render
from mel.config import CHANNELS, PACK_DATA, ROOT as ROOT_DIR
from mel.data import load_insights, load_farmers, errors
from mel.evaluation import evaluate, load_history, rules_changed
from mel.pipeline import run_pipeline, run_insight, clean
from mel.schedule import build_handoff
from mel.schedule.handoff import CapLedger
from mel.schedule import SeasonScheduler
from mel.simulator import simulate
from mel.writer import (check_survey, write_surveys, FarmerMemory, build_context, summary_lines,
                        history_notes)

sys.modules["mel"]._code_stamp = _MEL_STAMP  # see _reload_mel_if_changed

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
                       history=True,     # P4's history rules: on in the app, off for scoring (team decision 4 Nov)
                       attention=True)   # activity attention: on in the app, off for scoring (same decision)
    rows = list(zip(res.insights, res.outputs))
    # Contract order: send-window start, then created time, then farmer. Copies, because admit() edits the
    # hand-off it merges into, and Survey demo must keep showing the original survey.
    hs = sorted((copy.deepcopy(o["handoff"]) for _, o in rows if "handoff" in o),
                key=lambda h: (h["send_window"]["not_before"], h["created_at"], h["frequency_cap"]["key"]))
    led = CapLedger()
    admits, upcoming = {}, {}  # upcoming: farmer -> [(send start, insight id)] of surveys that go out
    for h in hs:
        a = led.admit(h)
        admits[h["handoff_id"]] = (a.decision, a.reason)
        if a.decision in ("sent", "moved"):
            upcoming.setdefault(h["survey"]["farmer_id"], []).append(
                (a.handoff["send_window"]["not_before"], h["survey"]["source_insight_ids"][0]))
    for v in upcoming.values():
        v.sort()
    surveyed = [o for _, o in rows if o["decision"].survey]
    files = [clean(s) for o in surveyed for s in o["surveys"].values()] + [o["handoff"] for o in surveyed]
    kinds = ["survey"] * (len(files) - len(surveyed)) + ["schedule_handoff"] * len(surveyed)
    valid = sum(not errors(k, f) for k, f in zip(kinds, files))
    return rows, admits, upcoming, valid, len(files)


@st.cache_resource(show_spinner=False)
def memory():
    """What the agent knows about each farmer (P4's FarmerMemory): earlier conversations + farmer profile."""
    return FarmerMemory(load_insights(DATA_DIR / "insights.jsonl" if DATA_DIR else None),
                        load_farmers(DATA_DIR / "farmers.csv" if DATA_DIR else None))


rows, admits, upcoming, n_valid, n_files = batch()
INSIGHT_BY_ID = {i.get("insight_id"): i for i, _ in rows}
html('<div class="mel-mast"><div class="mel-brand"><i class="mel-mark">✻</i>FarmerChat <span>Fasal Pulse</span></div>'
     '<div class="mel-tag">MEL Survey Agent</div></div>')
tab_over, tab_studio, tab_season, tab_follow = st.tabs(["Dashboard", "Survey demo", "Season", "Follow-up queue"])

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
        # Same bars as "Decisions by rule", so they grow in with the dashboard animation (COUNT_UP_JS watches
        # .mel-fill); st.bar_chart draws a static Vega chart the animation cannot reach.
        first_counts = Counter(o["handoff"]["channel_order"][0]["channel"] for o in surveyed)
        top_ch = max(first_counts.values() or [1])
        ch_bars = "".join(
            f'<div class="mel-rule" style="grid-template-columns:180px 1fr 44px"><span>{CH_NAME[ch]}</span>'
            f'<div class="mel-track"><div class="mel-fill green" style="width:{first_counts.get(ch, 0) / top_ch * 100:.0f}%"></div></div>'
            f'<b>{first_counts.get(ch, 0):,}</b></div>' for ch in CHANNELS)
        html(f'<div class="mel-card"><b>First channel planned</b><div class="mel-note">'
             f'Where each survey goes first</div>{ch_bars}</div>')

    # Highlighted farmers: SURGE only (quiet, then a jump or an urgent question). steady_high is deliberately
    # not highlighted: the representative asked us to attend to positive CHANGE, not to constant high activity.
    st.subheader("Highlighted farmers")
    st.caption("Farmers whose activity is rising: quiet, then a jump or a sudden urgent question. The "
               "beneficiary's representative asked us to focus attention on this positive change, not on "
               "constantly-busy farmers. Sorted by weight, then most recent.")
    surges = [(i, o) for i, o in rows
              if (getattr(o["decision"], "attention", None) or {}).get("tier") == "surge"]
    if not surges:
        st.info("No surge farmers in this run.")
    else:
        # One row per farmer: keep that farmer's most recent surge insight.
        latest_by_farmer: dict[str, tuple] = {}
        for i, o in surges:
            fid = i.get("farmer_id")
            prev = latest_by_farmer.get(fid)
            if prev is None or (i.get("created_at") or "") > (prev[0].get("created_at") or ""):
                latest_by_farmer[fid] = (i, o)
        highlighted = sorted(latest_by_farmer.values(),
                             key=lambda io: (io[1]["decision"].attention["weight"], io[0].get("created_at", "")),
                             reverse=True)
        REASON_LABEL = {"quiet_then_high_weight": "Quiet, then urgent", "activity_jump": "Activity jump"}
        table(pd.DataFrame([{
            "Farmer": i.get("farmer_id"),
            "Crop / animal": (i.get("asset") or {}).get("name"),
            "Why": REASON_LABEL.get(o["decision"].attention["reason"], o["decision"].attention["reason"]),
            "Weight": o["decision"].attention["weight"],
            "What we noticed": o["decision"].attention["explanation"],
            "When": short(i["created_at"]) if i.get("created_at") else "—",
        } for i, o in highlighted[:50]]), width="stretch", hide_index=True, height=260)
        st.caption(f"{len(highlighted):,} farmers highlighted (from {len(surges):,} surge insights; "
                   f"most recent surge per farmer, showing up to 50).")

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
    """The scheduler in plain words: when it sends, which channel it tries next if there is no answer, when it
    stops, and this farmer's next survey. The full hand-off stays in Developer details (JSON)."""
    decision, reason = admits.get(h["handoff_id"], ("sent", ""))
    status = {"sent": badge("Ready to send"), "moved": badge("Moved by weekly limit", "amber"),
              "merged": badge("Merged by weekly limit", "amber"), "skipped": badge("Skipped by weekly limit", "red"),
              "opted_out": badge("Opted out", "red")}[decision]
    limit = "" if decision == "sent" else f'<div class="mel-note">{escape(us_text(reason))}</div>'
    route = "".join(f'<span>{CH_NAME[c["channel"]]}</span>'
                    + (f'<small>{c["wait_hours"]} h →</small>' if c.get("wait_hours") else "") for c in h["channel_order"])
    me, start = h["survey"]["source_insight_ids"][0], h["send_window"]["not_before"]
    nxt = next((iid for t, iid in upcoming.get(h["survey"]["farmer_id"], []) if t > start and iid != me), None)
    if nxt:
        t = next(t for t, iid in upcoming[h["survey"]["farmer_id"]] if iid == nxt)
        a = INSIGHT_BY_ID[nxt]
        nxt_html = (f'<b>{format_date(t)}</b><div class="mel-note">{escape(str((a.get("asset") or {}).get("name") or "").title())}, '
                    f'{escape(str(a.get("concern") or "").replace("_", " "))}</div>')
    else:
        nxt_html = '<b>None planned</b>'
    html(f'''<div class="mel-card"><div><b>Scheduler</b> {status}</div>{limit}<br><div class="mel-strip">
<div><div class="mel-k">Sends</div><b>{long(send_time["send_at"])}</b>
<div class="mel-note">{escape(us_text(send_time["reason"]))}</div></div>
<div><div class="mel-k">No answer? Next channel</div><div class="mel-route">{route}</div>
<div class="mel-note">Stops trying {short(h["send_window"]["not_after"])}</div></div>
<div><div class="mel-k">Next survey for this farmer</div>{nxt_html}</div></div></div>''')


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


# One pick per insight severity (high / medium / low) plus two edge cases; first one is the default.
# I-001996: F-000208 reported wheat drying in patches on 12/08 (low); four days later it is high (history rule H5).
DEMO_PICKS = {"I-001253": "High — Goat veterinary follow-up", "I-001645": "Medium — Lentil nutrient care",
              "I-005625": "Low — Stored mustard monitoring", "I-001996": "Edge case — Low turned high (wheat)",
              "I-000291": "Edge case — No survey (critical cow)"}
BROWSE = "Browse all conversations"
PRETEND = ["none", "said the input was not available nearby", "said it was too costly", "ignored the last 3 surveys"]
PRETEND_ATT = {
    "as computed from the real data": None,
    "quiet, then urgent (surge)": {"tier": "surge", "reason": "quiet_then_high_weight", "weight": 1.5,
                                   "baseline_per_week": 0.0, "recent_count": 1,
                                   "explanation": "This farmer was quiet, then raised an urgent question: worth extra attention."},
    "steady heavy user (steady_high)": {"tier": "steady_high", "reason": "none", "weight": 0.5,
                                        "baseline_per_week": 2.5, "recent_count": 3,
                                        "explanation": "This farmer is consistently busy, so no extra priority by default."},
    "went quiet (neutral)": {"tier": "neutral", "reason": "declining", "weight": 1.0,
                             "baseline_per_week": 2.0, "recent_count": 1,
                             "explanation": "This farmer's activity has dropped below their usual rate: treated normally."},
}



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


def _flip_sound():
    st.session_state["tts_on"] = not st.session_state.get("tts_on", True)


def sound_button(where):
    """Apple-style speaker beside Restart, one pill with two taps: the speaker turns the read-aloud on or off,
    the chevron opens the volume. On by default (user's choice, 4 Nov): the call is read aloud as soon as it is
    answered, so ElevenLabs is called for each line the first time it is heard."""
    on = st.session_state.get("tts_on", True)
    pill = where.container(horizontal=True, gap=None, wrap=False, width="content", key="tts_pill")
    pill.button("Mute the call" if on else "Read the call aloud", key="tts_toggle", on_click=_flip_sound,
                icon=":material/volume_up:" if on else ":material/volume_off:", width="content",
                help="Mute" if on else "Read the call aloud (ElevenLabs, Hindi and English)")
    with pill.popover("Volume", key="tts_pop", help="Volume"):
        st.slider("Volume", 0, 100, 80, key="tts_volume", format="%d%%")


def voice_readout(sv: dict, preview_key: str, rec):
    """Read aloud what the farmer hears on the call: the greeting, then each question as it comes up, then the
    closing line. ElevenLabs text to speech, multilingual; nothing is sent to a farmer. The speaker in the settings
    bar (sound_button) turns it on; Volume acts on the player directly (a tiny script), so it never restarts the line."""
    if not st.session_state.get("tts_on", True):
        return
    if not tts.api_key():
        st.caption("Add ELEVENLABS_API_KEY to the repo's .env (copy .env.example) or, on Streamlit Cloud, to the app's secrets, then rerun to hear the call.")
        return
    volume = st.session_state.get("tts_volume", 80)
    state, vo = st.session_state.get(f"mel_preview|{preview_key}"), render(sv, "voice")
    if state is None or state.stage == "ringing":
        return  # the phone is still ringing: nothing is spoken until the farmer answers
    if state.stage == "invite":
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
        components.html(f"""<script>
const vol = {volume / 100:.2f};
const apply = () => window.parent.document.querySelectorAll('audio').forEach(a => {{ a.volume = vol; }});
apply(); [150, 500, 1200, 2500].forEach(t => setTimeout(apply, t));
</script>""", height=0)


def report_strip(kicker: str, title: str, note: str = ""):
    """The report's title line: what this insight is, plus the submission time for an own insight."""
    html(f'<div class="mel-report"><div><div class="mel-kicker{" own" if kicker == "Your insight" else ""}">{escape(kicker)}'
         f'</div><h2>{escape(title)}</h2></div>' + (f'<div class="mel-sum">{escape(note)}</div>' if note else "") + '</div>')


# ---------------------------------------------------------------- the agent, step by step (P5, AWS AgentCore design)
# Evidence Extractor -> Analyst -> Verifier -> Synthesizer, with bounded revision (mel/agent). Runs locally, or on
# Amazon Bedrock AgentCore when MEL_AGENTCORE_ARN is set. A run recorded on a laptop with Bedrock access
# (python -m mel.agent --record) is shown on the hosted app, which has no AWS keys.
AGENT_RUNS = ROOT_DIR / "docs" / "results" / "agent_runs"
STEP_ICON = {"evidence": ":material/search:", "analyst": ":material/table_chart:", "verifier": ":material/shield:",
             "synthesizer": ":material/description:"}
STEP_NAME = {"evidence": "Evidence Extractor", "analyst": "Analyst", "verifier": "Verifier", "synthesizer": "Synthesizer"}


@st.cache_resource(show_spinner=False)
def _farmers_by_id():
    return load_farmers(DATA_DIR / "farmers.csv" if DATA_DIR else None)


def _agent_inputs(ins):
    from mel.timing import chat_hours
    same = [i for i, _ in rows if i.get("farmer_id") == ins.get("farmer_id")]
    return {"farmer": _farmers_by_id().get(ins.get("farmer_id")),
            "history_hours": chat_hours(same, ins.get("farmer_id"), ins.get("created_at"))}


def _recorded_run(insight_id):
    try:
        return json.loads((AGENT_RUNS / f"{insight_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _show_event(e, where):
    ok = e["status"] == "ok"
    head = f"{'✓' if ok else '✗'} **{e['title']}**" + (f" · {e['ms']:.0f} ms" if e.get("ms") is not None else "")
    where.markdown(head)
    data = e.get("data") or {}
    if e["step"] == "analyst" and data.get("questions"):
        where.markdown("\n".join(f"  - {q}" for q in data["questions"]))
        if e["detail"]:
            where.caption(e["detail"])
    elif e["step"] == "verifier" and not ok:
        where.markdown("\n".join(f"  - {p}" for p in data.get("problems", [])) or e["detail"])
    elif e["step"] == "verifier":
        where.caption(f"passed every check · relevance {data.get('relevance')}"
                      + (f" · AI judge {data['judge']}/5" if data.get("judge") is not None else ""))
    else:
        where.caption(us_text(e["detail"]))


def agent_panel(ins, attention, mem):
    """Shows how the agent writes this conversation's survey, step by step."""
    from mel.agent import run_agent
    from mel.writer import llm
    arn = os.environ.get("MEL_AGENTCORE_ARN", "").strip()
    rec = _recorded_run(ins["insight_id"])
    where = ("Amazon Bedrock AgentCore" if arn else
             "this machine, writing with Bedrock" if llm.enabled() else "this machine, templates only (no AWS keys here)")
    st.caption("Four steps, as in our AWS design: the **Evidence Extractor** gathers what we know, the **Analyst** "
               "decides and drafts, the **Verifier** checks (safety, relevance, short questions, Guardrails), and a "
               "rejected draft goes back to the Analyst at most twice before the safe template is used. The "
               f"**Synthesizer** builds the files. Runs on: {where}.")
    key = f"agent_events|{ins['insight_id']}|{attention is not None and attention.get('tier')}|{mem is not None}"
    c = st.columns([1, 2.4], vertical_alignment="center")
    if c[0].button("Run the agent", key=f"run_{key}", icon=":material/play_arrow:"):
        events = []
        from mel.evaluation.costs import CostMeter, record_cost, row_from_results
        meter = CostMeter()
        with st.status("The agent is working…", expanded=True) as box:
            stream = (agentcore_stream(arn, ins) if arn else
                      run_agent(ins, memory=mem, attention=attention, **_agent_inputs(ins)))
            for e in stream:
                if e.get("step") == "result":
                    events.append(e)
                    break
                events.append(e)
                _show_event(e, box)
            m = (events[-1] if events and events[-1].get("step") == "result" else {}).get("metrics", {})
            box.update(label=f"Done in {m.get('seconds', 0):.1f} s · {m.get('calls', 0)} model calls · "
                             f"{m.get('revisions', 0)} revisions", state="complete", expanded=False)
        st.session_state[key] = events
        if not arn and meter.summary()["calls"]:       # a local run that paid for model calls: track its cost
            record_cost(row_from_results("single", f"app: {ins['insight_id']}", meter,
                                         [e for e in events if e.get("step") == "result"],
                                         writer=llm.write_model() if llm.enabled() else None,
                                         checker=llm.check_model() or None))
    shown = st.session_state.get(key)
    if not shown and rec:
        c[1].caption(f"Showing a run recorded on {rec.get('recorded', '?')} with Bedrock "
                     f"({rec.get('writer') or 'templates'}; judge {rec.get('judge') or 'none'}). Press Run the agent "
                     "to run it here.")
        shown = rec["events"]
    if shown:
        res = shown[-1] if shown[-1].get("step") == "result" else {}
        m = res.get("metrics", {})
        if m:
            k = st.columns(4)
            k[0].metric("Model calls", m.get("calls", 0), delta_color="off", delta_arrow="off")
            k[1].metric("Revisions", m.get("revisions", 0), "Analyst ↔ Verifier", delta_color="off", delta_arrow="off")
            k[2].metric("Cost", f"${m.get('cost_usd') or 0:.4f}", f"{m.get('input_tokens', 0):,} in / "
                        f"{m.get('output_tokens', 0):,} out tokens", delta_color="off", delta_arrow="off")
            k[3].metric("Time", f"{m.get('seconds', 0):.1f} s",
                        " · ".join(f"{l}: {src}" for l, src in (m.get("sources") or {}).items()),
                        delta_color="off", delta_arrow="off")
        for e in shown:
            if e.get("step") in STEP_NAME:
                with st.container(border=True):
                    st.markdown(f"{STEP_ICON[e['step']]} {STEP_NAME[e['step']]}")
                    _show_event(e, st)


def agentcore_stream(arn, ins):
    """Events from the agent running on Amazon Bedrock AgentCore Runtime (agentcore/app.py), as they arrive."""
    from mel.agent.remote import invoke
    yield from invoke(arn, {"insight": ins})


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
        pick = bar[0].selectbox("Demo selection", [*picks, BROWSE], key="studio_pick", format_func=lambda k: picks.get(k, k))
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
        if kicker != "Demo insight":  # a demo pick is already named in the selector; no repeated heading
            report_strip(kicker, title, note)
        d = out["decision"]
        a = ins.get("asset") or {}
        mem, pretend, restart = None, "none", False
        # The attention the batch computed for this insight (the app runs with attention on). The demo picker
        # below can override it with a made-up tier, because the pack's activity is flat with no designed surges.
        attention, pretend_att = getattr(d, "attention", None), next(iter(PRETEND_ATT))
        if d.survey:
            # One settings bar for everything that changes what the farmer sees in the preview. History rules
            # H1-H4 are always on here (team decision 4 Nov); scoring and the CLI keep them off.
            bar = st.columns([2.3, 1, 0.9, 2.3], vertical_alignment="bottom")
            tools = bar[2].container(horizontal=True, wrap=False, vertical_alignment="bottom")  # Restart, then the speaker
            # Icon-only: the label is the accessible name, hidden visually by app/theme.py (.st-key-studio_restart).
            restart = tools.button("Restart survey", key="studio_restart", icon=":material/restart_alt:",
                                    width="content", help="Restart survey")
            pretend = bar[3].selectbox("Pretend this farmer's survey history (demo)", PRETEND)
            pretend_att = st.selectbox("Pretend activity pattern (attention demo)", list(PRETEND_ATT),
                                       help="The pack's activity is flat with no designed surges, so this made-up "
                                            "pattern shows how a surge or steady-high farmer is treated differently.")
            if PRETEND_ATT[pretend_att] is not None:
                attention = PRETEND_ATT[pretend_att]
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
            # The batch was built with history on, no answers yet, and the data-computed attention.
            if pretend != "none" or attention is not getattr(d, "attention", None):
                surveys_now = write_surveys(ins, d.send_window, memory=mem, attention=attention)
                farmer_copy = clean(surveys_now.get(ins["conversation_language"]) or surveys_now["hi-IN"])
                out = {**out, "surveys": surveys_now, "handoff": build_handoff(ins, farmer_copy, attention)}
            h = out["handoff"]
            first_ch = h["channel_order"][0]["channel"]  # P2's recommended send time is for this channel
            ch = bar[0].segmented_control("Channel", CHANNELS, default=first_ch, required=True, format_func=CH_NAME.get,
                                          wrap=True)  # wrap instead of a sideways scroll on narrow screens
            # English by default so judges can read along; Hindi is one tap away. A widget keeps the choice across
            # the reruns that every tap on the phone causes.
            langs = list(out["surveys"])
            lang = bar[1].segmented_control("Language", langs, default="en-IN" if "en-IN" in langs else langs[0],
                                            required=True, format_func=lambda l: LANG_NAME.get(l, l))
            if ch == "voice":
                sound_button(tools)
        sev_tone = {"critical": "red", "high": "red", "medium": "amber"}.get(ins.get("severity"), "slate")
        why = us_text(out["surveys"][ins["conversation_language"]]["rationale"].split(" Personalised:")[0] if d.survey
                      else re.sub(r"^\[[^\]]*\]\s*", "", out["no_survey"]["reason"]))  # drop the "[R5 code]" prefix
        col_i, col_p, col_m = st.columns([1, 1.6, 0.8], gap="medium")
        col_i.markdown('<div class="mel-sec">Conversation</div>', unsafe_allow_html=True)
        col_p.markdown('<div class="mel-sec">What the farmer sees</div>', unsafe_allow_html=True)
        col_m.markdown('<div class="mel-sec">Plan and checks</div>', unsafe_allow_html=True)
        with col_i:
            # Context only: what was asked, what was advised, what the survey checks. IDs and fields are in the JSON.
            html(f'''<div class="mel-insight"><div class="mel-eyebrow">
    {badge((ins.get("severity") or "n/a").title() + " severity", sev_tone)}</div>
    <h3>{escape(str(a.get("name") or "—").title())} · {escape(str(ins.get("concern") or "").replace("_", " "))}</h3>
    <div class="f"><span>Farmer asked</span>“{escape(ins.get("query_summary") or "—")}”</div>
    <div class="f"><span>Advice given</span>“{escape(ins.get("advice_summary") or "—")}”</div>
    <div class="mel-why">{"What the survey checks" if d.survey else f"Why no survey ({d.rule})"}<p>{escape(why)}</p></div></div>''')
            if attention and d.survey:  # P1's activity attention (main, 4 Nov), shown under the redesigned card
                TIER_TONE = {"surge": "green", "steady_high": "slate", "neutral": "slate"}
                html(f'<div class="mel-card"><b>Activity attention</b><p>'
                     f'{badge(attention["tier"].replace("_", " ").title(), TIER_TONE.get(attention["tier"], "slate"))}'
                     f'{badge(attention["reason"].replace("_", " "), "slate")}</p>'
                     f'<p>{escape(attention["explanation"])}</p>'
                     f'<div class="mel-note">Baseline per week {attention["baseline_per_week"]}, '
                     f'recent {attention["recent_count"]}, weight {attention["weight"]}</div></div>')
            if mem is not None:
                notes = [(r, us_text(w)) for r, w in history_notes(ins, mem, attention)]
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
                pkey = f"preview|{ins['insight_id']}|{ch}|{lang}|{pretend}|{pretend_att}|{mem is not None}"
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
            with st.expander("How the agent wrote this survey: Evidence → Analyst → Verifier → Synthesizer",
                             icon=":material/smart_toy:"):
                agent_panel(ins, attention, mem)
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
        att = getattr(out["decision"], "attention", None) or {}
        tickets.append({
            "response_key": rec["response_key"], "farmer_id": rec["farmer_id"],
            "asset": a.get("name"), "concern": ins.get("concern"),
            "survey_id": rec["survey_id"], "channel": ch, "recorded_at": rec["recorded_at"],
            "reason": t_reason, "item_id": t_item, "prompt": t_def.get("prompt", ""),
            "answer": _answer_label(t_def, t_val), "rec": rec, "insight": ins, "survey": survey,
            "weight": att.get("weight", 1.0), "tier": att.get("tier", "neutral"),
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
    # Rising-activity farmers first (activity attention), then a normal queue: oldest answer first.
    tickets = sorted(_follow_queue(), key=lambda t: (-t["weight"], t["recorded_at"]))
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
                    "Weight": t["weight"],
                    "Farmer": t["farmer_id"],
                    "Crop / animal": str(t["asset"] or "—").title(),
                    "Why": FU_REASON.get(t["reason"], t["reason"]),
                    "Answer": t["answer"],
                    "Channel": CH_NAME.get(t["channel"], t["channel"]),
                    "Answered": t["recorded_at"],
                } for t in view]), width="stretch", hide_index=True, height=460, on_select="rerun",
                    selection_mode="single-row-required", key=f"fu_rows|{reason}|{chan}")  # new filter, first row
                st.caption(f"{len(view):,} farmers, rising activity first, then oldest answer first.")
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


def _model_name(model_id: str) -> str:
    """'us.anthropic.claude-haiku-4-5-20251001-v1:0' -> 'Claude Haiku 4.5'."""
    import re
    m = re.search(r"claude-([a-z]+)-(\d+)(?:-(\d)(?!\d))?", model_id or "")
    return f"Claude {m.group(1).title()} {m.group(2)}{'.' + m.group(3) if m.group(3) else ''}" if m else (model_id or "a model")


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
    from mel.evaluation.judge import load_summary
    judge = load_summary()   # committed results of the last Bedrock run, so the app never calls Bedrock itself
    jr = card.get("judge_relevance")
    if jr is None:
        jr = (judge.get("run") or {}).get("judge_relevance")
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

    cal, jrun = judge.get("calibration"), judge.get("run")
    from mel.evaluation.judge_models import load as load_models
    sweep = load_models()   # committed results of `python -m mel.evaluation.judge_models --run`
    names = {m.get("call_id"): f"{m['provider']} {m['name']}" for m in sweep.get("models", []) if m.get("call_id")}
    if cal:
        st.subheader("Can we trust the AI judge?")
        pr = [v for v in (cal.get("people_rank_r") or {}).values() if v is not None]
        st.caption(f"Five of us scored 20 surveys by hand (1–5), each on our own. The AI judge "
                   f"({names.get(cal['model']) or _model_name(cal['model'])} on Amazon Bedrock, picked below for "
                   "accuracy and cost) scored the same questions. It agrees with us at least as well as we agree with "
                   "each other.")
        j = st.columns(3)
        j[0].metric("Within 1 point of a person", _pct(cal["within_1"]),
                    f"people with each other: {_pct(cal['people_vs_people']['within_1'])}", delta_color="off", delta_arrow="off")
        j[1].metric("Average gap", f"{cal['mean_abs_diff']:.2f} points",
                    f"people with each other: {cal['people_vs_people']['mean_abs_diff']:.2f}", delta_color="off", delta_arrow="off")
        if cal.get("rank_r") is not None:
            j[2].metric("Follows the team's ranking", f"r = {cal['rank_r']:.2f}",
                        f"each person: {min(pr):.2f}–{max(pr):.2f}" if pr else None, delta_color="off", delta_arrow="off")
        with st.expander("How to read this, and the limits"):
            st.markdown(
                f"- A judge that always says 5 would be within 1 point {_pct(cal['always_5']['within_1'])} of the time, "
                "because people mostly gave 4s and 5s. So the strongest sign is the ranking: the AI gives its 4s to the "
                "surveys people rated lower, and follows the team's average more closely than any one of us does.\n"
                f"- Small sample (20 surveys). The AI used the scores {', '.join(sorted(str(k) for k in cal.get('judge_scores', {})))}.\n"
                "- People caught a data problem: the cauliflower advice in G-0129 talks about grain. A judge scores the "
                "survey, not the advice, so data errors still need a person.\n"
                "- Details: `docs/results/judge_calibration.md`.")
        if jrun:
            st.caption(f"On all {jrun['n']} answer-key surveys: average {jrun['judge_relevance']:.2f} / 5 "
                       f"({', '.join(f'{v}× {k}' for k, v in sorted(jrun['score_counts'].items(), reverse=True))}), "
                       f"{jrun['seconds']:.0f} s on Bedrock. Points were lost mostly on a generic second question "
                       "(\"Do you need more help?\", \"How is your goat now?\").")

    if sweep.get("models"):
        st.subheader("Which model makes the best judge?")
        ok = [m for m in sweep["models"] if m.get("rank")]
        pv = sweep.get("people_vs_people") or {}
        st.caption(f"Every text model on Amazon Bedrock that our account could call ({len(sweep['models'])} listed, "
                   f"{len(ok)} answered every survey) judged the same {sweep.get('surveys', 20)} hand-scored surveys. "
                   "Best first: how closely it follows the team's ranking (r), then the smallest gap. People with each "
                   f"other: within 1 point {_pct(pv.get('within_1'))}, gap {pv.get('mean_abs_diff', '—')}. "
                   f"Run {sweep.get('date', '')}, {sweep.get('region', '')}.")
        used = (cal or {}).get("model", "")
        by_id = {m["model_id"]: m for m in sweep["models"]}
        pick, top = by_id.get(sweep.get("best_value") or ""), by_id.get(sweep.get("most_accurate") or "")
        qm = sweep.get("quality_margin") or {}

        def _usd(v):
            return "price unknown" if v is None else (f"${v:,.2f}" if v >= 0.1 else f"${v:,.4f}")

        if pick or top:
            shown = pick or top
            b = st.columns(4)
            b[0].metric("Best value" if pick else "Most accurate (no prices yet)", shown["name"], shown["provider"],
                        delta_color="off", delta_arrow="off")
            b[1].metric("Its ranking match", f"r = {shown['rank_r']:.2f}" if shown.get("rank_r") is not None else "—",
                        f"within 1 point {_pct(shown['within_1'])}", delta_color="off", delta_arrow="off")
            b[2].metric("Cost per 1,000 surveys", _usd(shown.get("usd_per_1000_surveys")),
                        f"whole season ({sweep.get('season_surveys', 2616):,} surveys): {_usd(shown.get('usd_per_season'))}",
                        delta_color="off", delta_arrow="off")
            b[3].metric("Speed", f"{shown['seconds_per_call']:.1f} s" if shown.get("seconds_per_call") is not None else "—",
                        "per survey", delta_color="off", delta_arrow="off")
            note = (f"Best value = the cheapest model whose quality is close to the most accurate one (ranking match "
                    f"within {qm.get('rank_r', 0.1)} and gap within {qm.get('mean_abs_diff', 0.15)}), so we don't pay "
                    "for accuracy we can't measure.")
            if pick and top and pick is not top:
                note += (f" The most accurate is {top['provider']} {top['name']} (r = {top.get('rank_r')}, "
                         f"{_usd(top.get('usd_per_1000_surveys'))} per 1,000 surveys).")
            if not pick:
                note += (" No priced model is close enough to the most accurate one: add its price to "
                         "docs/results/bedrock_prices.json and re-run."
                         if any(m.get("usd_per_1000_surveys") is not None for m in sweep["models"]) else
                         " No model has a price yet: run `python -m mel.evaluation.judge_models --prices`.")
            st.caption(note)
            ok_c = [m for m in ok if m.get("usd_per_1000_surveys") is not None]
            if ok_c:
                chart = pd.DataFrame({"model": [f"{m['provider']} {m['name']}" for m in ok_c],
                                      "follows the team's ranking (r)": [m.get("rank_r") or 0 for m in ok_c]}).set_index("model")
                st.markdown("**Ranking match by model** (higher is better; models with a known price)")
                st.bar_chart(chart, horizontal=True, color=PALETTE["green"], height=max(160, 26 * len(ok_c)), sort=False)
        tab = [{"Rank": str(m["rank"]) if m.get("rank") else "—", "Pick": m.get("pick") or "",
                "Provider": m["provider"], "Model": m["name"] + ("  (judge used above)" if used and m.get("call_id") == used else ""),
                "Within 1 point": _pct(m.get("within_1")), "Average gap": m.get("mean_abs_diff"),
                "Ranking match (r)": m.get("rank_r"), "Close to best": "yes" if m.get("close_to_best") else "",
                "Cost per 1,000 surveys": _usd(m.get("usd_per_1000_surveys")) if m.get("status") == "ok" else "",
                "Seconds per survey": m.get("seconds_per_call"), "Surveys answered": m.get("surveys_scored"),
                "Result": {"ok": "ok", "skipped": "not callable on demand", "error": "error"}.get(m["status"], m["status"])}
               for m in sweep["models"]]
        with st.expander(f"All {len(tab)} models"):
            table(pd.DataFrame(tab), width="stretch", hide_index=True)
            errs = [m for m in sweep["models"] if m.get("error")]
            if errs:
                st.caption("Why some models have no score: " + "; ".join(
                    f"{m['name']}: {m['error'][:90]}" for m in errs[:8]) + (" …" if len(errs) > 8 else ""))

    # Activity attention: the deliberate change, shown with numbers (CLAUDE.md). Reads the report JSON written
    # by scripts/activity_report.py; the app itself runs with attention on.
    _att_json = Path(__file__).resolve().parents[1] / "docs" / "results" / "activity_attention.json"
    if _att_json.exists():
        am = __import__("json").loads(_att_json.read_text(encoding="utf-8"))
        st.subheader("Activity attention (deliberate change)")
        st.caption("Why: " + am["reason"] + ". We attend to rising activity (surge), step constantly-busy "
                   "farmers down by default (steady_high), and leave everyone else unchanged. Decision, rule and "
                   "send window are identical with attention off vs on — only priority, question count and the "
                   "send moment change. Full pack: " + f"{am['n_insights']:,} insights.")
        tt = am["tier_totals"]
        ac = st.columns(4)
        ac[0].metric("Surge", tt.get("surge", 0), "quiet, then a jump / urgent", delta_color="off")
        ac[1].metric("Steady-high", tt.get("steady_high", 0), "stepped down by default", delta_color="off")
        ac[2].metric("Neutral", tt.get("neutral", 0), "unchanged", delta_color="off")
        sc_on = am["scorecard_on"]
        ac[3].metric("Format / safety / timeliness",
                     f"{sc_on['format_pass']:.0%} / {sc_on['safety_pass']:.0%} / {sc_on['timeliness_pass']:.0%}",
                     "held at 100%", delta_color="off")
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**Priority, off vs on**")
            st.dataframe(pd.DataFrame([{"Priority": k, "off": am["priority_off"].get(k, 0),
                                        "on": am["priority_on"].get(k, 0)} for k in ("high", "normal", "low")],
                                      ), hide_index=True, width="stretch")
            st.markdown("**Golden set, off vs on**")
            g_off, g_on = am["golden_off"], am["golden_on"]
            # Every value in the off/on columns is a string, so item similarity (a 0-1 ratio) renders the same
            # way as the percentage rows instead of pandas mixing numbers and text in one column.
            _sim = lambda v: f"{v:.3f}"
            st.dataframe(pd.DataFrame([
                {"Metric": "Decision", "off": _pct(g_off["decision_acc"]), "on": _pct(g_on["decision_acc"])},
                {"Metric": "Rule", "off": _pct(g_off["rule_acc"]), "on": _pct(g_on["rule_acc"])},
                {"Metric": "Channel", "off": _pct(g_off["channel_acc"]), "on": _pct(g_on["channel_acc"])},
                {"Metric": "Item similarity", "off": _sim(g_off["item_similarity_avg"]), "on": _sim(g_on["item_similarity_avg"])},
            ]), hide_index=True, width="stretch")
        with cc2:
            st.markdown("**Tier by activity level (on)**")
            st.dataframe(pd.DataFrame([{"Activity": al, "surge": c.get("surge", 0), "neutral": c.get("neutral", 0),
                                        "steady_high": c.get("steady_high", 0)}
                                       for al, c in sorted(am["tier_by_activity"].items())]),
                         hide_index=True, width="stretch")
            st.markdown("**Avg questions / survey, off vs on**")
            st.dataframe(pd.DataFrame([{"Activity": al, "off": am["avg_questions_off"].get(al, "—"),
                                        "on": am["avg_questions_on"].get(al, "—")}
                                       for al in sorted(am["avg_questions_on"])]), hide_index=True, width="stretch")
        st.caption("Surge is concentrated in light and regular farmers (rising change), not in heavy users — a "
                   "plain 'activity doubled' ratio over-flagged heavy/regular users, so we use a Poisson jump "
                   "test against each farmer's own baseline instead. Thresholds live in "
                   "`config/activity_attention.json` (starting values, tuned with this evidence).")
    else:
        st.subheader("Activity attention (deliberate change)")
        st.info("Run `python scripts/activity_report.py` to generate the before/after numbers for this section.")

    from mel.evaluation.costs import load_costs, FULL_SET_SURVEYS
    ledger = load_costs()     # docs/results/cost_history.jsonl: one row per run that wrote surveys with Bedrock
    if ledger:
        st.subheader("What it costs")
        try:
            full = json.loads((ROOT_DIR / "docs" / "results" / "full_bedrock_run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            full = None
        priced = [r for r in ledger if r.get("usd_per_survey") is not None]
        latest = next((r for r in reversed(priced) if r.get("kind") in ("batch", "pilot", "partial")),
                      priced[-1] if priced else None)
        st.caption("Every run that writes surveys with Bedrock is logged with its real spend (cached answers cost "
                   "nothing), split into writing, checking and judging. Cost per survey covers both languages, "
                   f"revisions and checks; the projection is for the full synthetic dataset ({FULL_SET_SURVEYS:,} surveys, "
                   f"{FULL_SET_SURVEYS * 2:,} files).")
        k = st.columns(4)
        if latest:
            k[0].metric("Cost per survey", f"${latest['usd_per_survey']:.4f}",
                        f"{latest.get('writer') or 'templates'} · {latest['kind']} run {latest['run']}",
                        delta_color="off", delta_arrow="off")
            k[1].metric("Per 1,000 surveys", f"${latest['usd_per_1000_surveys']:.2f}", delta_color="off", delta_arrow="off")
            k[2].metric("Projected, full dataset", f"${latest['projected_full_usd']:.2f}",
                        f"{FULL_SET_SURVEYS:,} surveys, Hindi + English", delta_color="off", delta_arrow="off")
        if full:
            c = full.get("cost") or {}
            k[3].metric("Full run, actual", f"${c.get('spent_usd') or 0:.2f}",
                        f"{full['surveys']:,} surveys in {full['seconds'] / 60:.0f} min"
                        + (" · stopped at the cap" if full.get("stopped_at_cap") else ""),
                        delta_color="off", delta_arrow="off")
        else:
            k[3].metric("Full run, actual", "not run yet", "python -m mel.agent.batch", delta_color="off", delta_arrow="off")
        if len(priced) >= 2:
            st.markdown("**Cost per survey, run by run**")
            st.line_chart(pd.DataFrame({"run": [f"{r['run']} {r['kind']}" for r in priced],
                                        "cost per survey (USD)": [r["usd_per_survey"] for r in priced]}).set_index("run"),
                          color=PALETTE["green"], height=200)
        if full:
            st.caption(f"Full run: {full.get('sources')} · revisions {full.get('revisions')} on "
                       f"{full.get('surveys_revised')} surveys · template fallbacks {sum((full.get('fallbacks') or {}).values())}"
                       + (f" · AI judge relevance {full['judge_relevance']}" if full.get("judge_relevance") else "")
                       + f" · {full.get('schema_invalid_files', 0)} schema-invalid files.")
        with st.expander(f"All {len(ledger)} cost runs"):
            table(pd.DataFrame([{
                "Run": r["run"], "When": r["at"], "What": r.get("label"), "Writer": r.get("writer") or "templates",
                "Surveys": r.get("surveys"), "Model calls": r.get("calls"), "From cache": r.get("cached_calls"),
                "Spent": f"${r.get('spent_usd') or 0:.4f}",
                "Write / check / judge": " / ".join(f"${(r.get('by_purpose') or {}).get(p, {}).get('usd', 0):.4f}"
                                                    for p in ("write", "check", "judge")),
                "Per survey": f"${r['usd_per_survey']:.5f}" if r.get("usd_per_survey") is not None else "—",
                "Projected full set": f"${r['projected_full_usd']:.2f}" if r.get("projected_full_usd") is not None else "—",
                "Revisions": r.get("revisions"), "Fallbacks": sum((r.get("fallbacks") or {}).values())}
                for r in reversed(ledger)]), width="stretch", hide_index=True)

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


# ---------------------------------------------------------------- Season (P3's shared simulated clock)
# The contract's "simulated clock moving through the season": one SimClock shared by the scheduler (weekly limit,
# opt-outs) and the broadcaster (send window, send hours, quality check), with a manual trigger per step.
# P3's API: docs/p3_season_screen_api.md. Nothing is sent; every delivery is P3's simulator.
PERSONA_LABEL = {
    "default": "Responsive: answers on the first channel",
    "app_push_dead": "App notifications never arrive: falls back to the next channel",
    "never_answers": "Never answers: the survey expires",
    "opts_out_first": "Opts out on the first message",
    "no_voice": "Cannot take phone calls",
    "sometimes_fails": "Sometimes says the advice didn't work (about 1 in 4)",
}
STATUS_LABEL = {"completed": "Answered", "delivery_failed": "Not delivered", "expired": "Expired, no answer",
                "declined": "Opted out", "partial": "Partly answered"}
from mel.writer import RELEVANCE_THRESHOLD as SEASON_THRESHOLD   # the agreed send bar (0.3, P4 + P5, 4 Nov)


def _india(ts: str) -> str:
    """India time in the app's US style, e.g. "11/02/2026 7:00 AM IST". The season runs on India time, so this page
    shows it first (Eastern alongside), or 07:00 on 1 November would read as the evening of 31 October."""
    d = datetime.fromisoformat(ts)
    return f"{d:%m/%d/%Y} {d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'} IST"


def _new_season(threshold: float, persona: str) -> dict:
    sched = SeasonScheduler(relevance_threshold=threshold, persona=persona)
    # Copies: admit() edits the hand-off it merges into, and the other tabs keep showing the originals.
    admitted = sched.admit_all([copy.deepcopy(o["handoff"]) for _, o in rows if "handoff" in o])
    return {"sched": sched, "key": (threshold, persona), "log": [], "days": Counter(),
            "admits": Counter(a.decision for a in admitted)}


def _season_send(state: dict, one: bool = False) -> list:
    """Fire one due step (the manual trigger) or every step due now, and log what happened."""
    sched = state["sched"]
    results = [sched.step()] if one else sched.run_due(max_steps=10000)
    sent = [r for r in results if r.kind == "sent"]
    ins_of = {i.get("insight_id"): i for i, _ in rows}
    for r in sent:
        rec = r.record
        ins = ins_of.get((rec.get("source_insight_ids") or [None])[0]) or {}
        state["log"].append({"when": _india(sched.now_ist()), "survey": rec["survey_id"], "farmer": rec["farmer_id"],
                             "crop or animal": (ins.get("asset") or {}).get("name", ""),
                             "channel": CH_NAME.get(r.channel, r.channel),
                             "result": STATUS_LABEL.get(rec["status"], rec["status"]),
                             "next": {"none": "done", "give_up": "stop", "fall_back_to_next_channel": "try next channel"}
                             .get(rec["retry_decision"], rec["retry_decision"]),
                             "needs a person": "yes" if rec.get("needs_follow_up") else ""})
        state["days"][sched.now_ist()[:10]] += 1
    return results


def _season_advance(state: dict, days: int, send: bool) -> None:
    """Move the shared clock a day at a time, sending what falls due each morning when `send` is on."""
    sched = state["sched"]
    for _ in range(days):
        if sched.is_season_over():
            break
        if send:
            _season_send(state)
        sched.advance(1)
    if send:
        _season_send(state)


with tab_season:
    st.subheader("The season, on a simulated clock")
    st.caption("One shared clock drives the scheduler (weekly limit, opt-outs) and the broadcaster (send window, "
               "send hours, quality check) from 1 November to 31 March. Move it a day, a week, or to the end of the "
               "season, or send one step at a time. Delivery and answers are simulated; nothing is sent.")
    cfg = st.columns([1.2, 1.6, 0.8], vertical_alignment="bottom")
    threshold = cfg[0].slider("Relevance needed to send", 0.0, 1.0, SEASON_THRESHOLD, 0.05,
                              help="P3's quality check blocks any survey whose relevance score (P4's, 0–1) is below "
                                   f"this. The agreed bar is {SEASON_THRESHOLD}: it blocks only surveys that name neither the "
                                   "crop, the problem nor the advice. Slide it to see the trade-off.")
    persona = cfg[1].selectbox("How farmers respond", list(PERSONA_LABEL), format_func=PERSONA_LABEL.get,
                               help="P3's simulated farmers. Pick one to see fall-back, expiry and opt-out.")
    reset = cfg[2].button("Restart season", width="stretch")
    if reset or st.session_state.get("season", {}).get("key") != (threshold, persona):
        st.session_state.season = _new_season(threshold, persona)
    season = st.session_state.season
    sched = season["sched"]

    ctl = st.columns(5)
    auto = st.toggle("Send what falls due while the clock moves", value=True,
                     help="Off: the clock moves and work piles up; then use the send buttons by hand.")
    over = sched.is_season_over()
    if ctl[0].button("Send next step", width="stretch", disabled=over,
                     help="The manual trigger: one channel attempt for the next due survey."):
        r = _season_send(season, one=True)[0]
        if r.kind == "nothing":
            st.toast("Nothing is due right now. Move the clock forward.")
    if ctl[1].button("Send all due now", width="stretch", disabled=over):
        _season_send(season)
    if ctl[2].button("+1 day", width="stretch", disabled=over):
        _season_advance(season, 1, auto)
    if ctl[3].button("+1 week", width="stretch", disabled=over):
        _season_advance(season, 7, auto)
    if ctl[4].button("To end of March", width="stretch", disabled=over, type="primary"):
        _season_advance(season, 400, auto)

    start, end, now = sched.season.start, sched.season.end, sched.now()
    total = (end - start).total_seconds()
    done = min(1.0, max(0.0, (now - start).total_seconds() / total)) if total else 1.0
    st.progress(done, text=f"Simulated time: {_india(sched.now_ist())} ({long(sched.now_ist())}) · day {(now - start).days + 1} of "
                           f"{(end - start).days + 1}" + (" · season over" if sched.is_season_over() else ""))

    log, adm, drops = season["log"], season["admits"], sched.broadcaster.counts()
    res_count = Counter(e["result"] for e in log)
    m = st.columns(6)
    m[0].metric("Waiting to send", f"{len(sched.pending):,}", "queued, in send-window order", delta_color="off", delta_arrow="off")
    m[1].metric("Messages sent", f"{len(log):,}", "channel attempts", delta_color="off", delta_arrow="off")
    m[2].metric("Answered", f"{res_count.get('Answered', 0):,}", delta_color="off", delta_arrow="off")
    m[3].metric("No answer or not delivered", f"{res_count.get('Expired, no answer', 0) + res_count.get('Not delivered', 0):,}",
                delta_color="off", delta_arrow="off")
    m[4].metric("Opted out", f"{res_count.get('Opted out', 0):,}", "never asked again", delta_color="off", delta_arrow="off")
    m[5].metric("Blocked by quality check", f"{drops['rejected']:,}", f"relevance below {threshold:.2f}",
                delta_color="off", delta_arrow="off")
    st.caption(f"Weekly limit at the start of the season: {adm.get('sent', 0):,} on time, {adm.get('moved', 0):,} moved "
               f"to a later week, {adm.get('merged', 0):,} merged into an earlier survey, {adm.get('skipped', 0):,} "
               f"skipped. {drops['expired']:,} expired in the queue. "
               f"{sum(1 for e in log if e['needs a person']):,} answers need a person to follow up.")

    if season["days"]:
        weeks = Counter()
        for day, n in season["days"].items():
            d = datetime.fromisoformat(day)
            weeks[(d - timedelta(days=d.weekday())).date().isoformat()] += n
        wk = pd.DataFrame({"week of": [format_date(w) for w in sorted(weeks)],
                           "messages sent": [weeks[w] for w in sorted(weeks)]}).set_index("week of")
        st.markdown("**Messages sent per week**")
        st.bar_chart(wk, color=PALETTE["green"], height=220, sort=False)
        st.markdown(f"**Latest sends** (newest first, {min(len(log), 50)} of {len(log):,})")
        table(pd.DataFrame(log[-50:][::-1]), width="stretch", hide_index=True)
    else:
        first = min((h["send_window"]["not_before"] for h in sched.pending), default=None)
        st.info("Nothing sent yet." + (f" The first send window opens {_india(first)}." if first else "")
                + " Press +1 day, +1 week, or To end of March.")
