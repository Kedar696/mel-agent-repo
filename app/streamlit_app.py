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
    root = Path(__file__).resolve().parents[1]
    stamp = max(p.stat().st_mtime for p in (root / "mel").rglob("*.py"))
    loaded = sys.modules.get("mel")
    if loaded is not None and getattr(loaded, "_code_stamp", None) != stamp:
        for name in [m for m in sys.modules if m == "mel" or m.startswith("mel.")]:
            del sys.modules[name]
        st.cache_data.clear()
        st.cache_resource.clear()
    # The app's own helper modules (app/theme.py, app/channel_preview.py, ...) are imported the same way and
    # go stale the same way: a long-running server would otherwise fail on a new name with ImportError.
    app_stamp = max(p.stat().st_mtime for p in (root / "app").glob("*.py") if p.name != "streamlit_app.py")
    loaded_app = sys.modules.get("app")
    if loaded_app is not None and getattr(loaded_app, "_code_stamp", None) != app_stamp:
        for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            del sys.modules[name]
    return stamp, app_stamp


_MEL_STAMP, _APP_STAMP = _reload_mel_if_changed()

from mel.channels import render
from mel.config import CHANNELS, PACK_DATA, ROOT as ROOT_DIR
from mel.data import load_insights, load_farmers, errors
from mel.evaluation import evaluate
from mel.pipeline import run_pipeline, run_insight, clean
from mel.schedule import build_handoff
from mel.schedule.handoff import CapLedger
from mel.schedule import SeasonScheduler
from mel.simulator import simulate
from mel.writer import (check_survey, write_surveys, FarmerMemory, history_notes)

sys.modules["mel"]._code_stamp = _MEL_STAMP  # see _reload_mel_if_changed

from app import custom_context as cc
from app import tts
from app.display_time import ZONE_LABEL, format_clock, format_date, format_datetime, format_dates_in_text
from app import dashboard
from app.channel_preview import render_channel_preview
from app.theme import LOCKUP, MASCOT, PALETTE, apply_theme

sys.modules["app"]._code_stamp = _APP_STAMP  # see _reload_mel_if_changed

APP_NAME = "Fasal Pulse - MEL Survey Agent"
st.set_page_config(page_title=APP_NAME, layout="wide")
apply_theme()

RULE_LABEL = {"R1": "Junk / unclear", "R2": "Critical → human call", "R3": "Nothing to verify",
              "R4": "Waiting for details", "R5": "No check needed", "R6": "After season",
              "R7": "Already harvested", "R8": "Survey planned"}
RULE_TONE = {"R2": "red", "R4": "amber", "R6": "amber", "R8": "green"}
CH_NAME = {"app": "App", "web": "Web", "whatsapp": "WhatsApp", "telegram": "Telegram", "voice": "Voice"}
LANG_NAME = {"hi-IN": "Hindi", "en-IN": "English"}
HINDI_SHEET = ROOT_DIR / "docs" / "p4" / "hindi_review_sheet.csv"  # P4's native-speaker review, one row per line


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
html(f'<div class="mel-mast"><div class="mel-brand">{LOCKUP}</div>'
     '<div class="mel-head"><h1 class="mel-title">MEL Survey Agent</h1></div></div>')
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
  const scan = () => document.querySelectorAll('[data-testid="stMetricValue"], .mel-fill, .mel-count').forEach(el => {
    if (!seen.has(el)) { seen.add(el); io.observe(el); } });
  let queued = false;
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; scan(); }); } })
    .observe(document.body, {childList: true, subtree: true});
  scan();
})();
"""

@st.cache_data(show_spinner="Scoring the answer key and checking every survey in the full dataset…")
def _evaluate(basis):
    return evaluate(basis)


def _pct(v):
    return "—" if v is None else f"{v:.1%}"


# ---------------------------------------------------------------- Dashboard (app/dashboard.py: mostly charts)
with tab_over:
    st.html(f"<script>{COUNT_UP_JS}</script>", unsafe_allow_javascript=True)
    dashboard.render(rows=rows, admits=admits, upcoming=upcoming, n_valid=n_valid, n_files=n_files,
                     evaluate_fn=_evaluate, rule_label=RULE_LABEL, ch_name=CH_NAME, channels=CHANNELS,
                     table=table, short=short)

# ---------------------------------------------------------------- Survey demo
labels = {f"{i.get('insight_id')} · {(i.get('asset') or {}).get('name')} · {i.get('resolution_type')} · "
          f"{'survey' if o['decision'].survey else 'no survey ' + o['decision'].rule}": (i, o) for i, o in rows}


AGENT_VERBS = [("Schlepping", "Schlepped"), ("Pondering", "Pondered"), ("Mulling", "Mulled"),
               ("Percolating", "Percolated"), ("Ruminating", "Ruminated"), ("Noodling", "Noodled")]


def guard_checks(surveys):
    """-> (passed, total, failed check names), over both languages."""
    probs = [p for s in surveys.values() for p in check_survey(clean(s))]
    checks = [("Schema valid", "schema"), ("No new advice", "advice"), ("No personal info", "personal"),
              ("Labels ≤ 20 chars", "label")]
    failed = [t for t, k in checks if any(k in p for p in probs)]
    return len(checks) - len(failed), len(checks), failed


def _route(h):
    return " → ".join(CH_NAME[c["channel"]] + (f' <small>({c["wait_hours"]} h)</small>' if c.get("wait_hours") else "")
                      for c in h["channel_order"])


def _next_survey(h):
    """This farmer's next survey that gets past the weekly limit, from the batch."""
    me, start = h["survey"]["source_insight_ids"][0], h["send_window"]["not_before"]
    nxt = next(((t, iid) for t, iid in upcoming.get(h["survey"]["farmer_id"], []) if t > start and iid != me), None)
    if not nxt:
        return "None planned"
    a = INSIGHT_BY_ID.get(nxt[1]) or {}
    return (f'<b>{format_date(nxt[0])}</b> · {escape(str((a.get("asset") or {}).get("name") or "").title())}, '
            f'{escape(str(a.get("concern") or "").replace("_", " "))}')


def agent_view(ins, out, d, notes, attention):
    """The agent at work, styled like a Claude Code session (William's ask): one "⏺ Tool(args)" step per stage with
    an indented "⎿" result on a dark terminal, a spinner status line that ticks seconds and tokens and ends as
    "✻ <verb> for Ns", then the mascot. CSS-only motion: Streamlit keeps this HTML in place while the farmer taps,
    so it plays once per case, not on every tap."""
    a, loc = ins.get("asset") or {}, ins.get("location") or {}
    sev = ins.get("severity") or "n/a"
    fid = escape(str(ins.get("farmer_id")))
    why = us_text(out["surveys"][ins["conversation_language"]]["rationale"].split(" Personalised:")[0] if d.survey
                  else re.sub(r"^\[[^\]]*\]\s*", "", out["no_survey"]["reason"]))  # drop the "[R5 code]" prefix

    def kv(pairs):
        return '<dl class="kv">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in pairs) + "</dl>"

    steps = [("Read", f'conversation {ins.get("conversation_id") or ""}', kv([
                 ("Farmer", f'{fid} · {escape(str(loc.get("district") or "—"))}, {escape(str(loc.get("state") or ""))}'
                            f' · speaks {LANG_NAME.get(ins.get("conversation_language"), "—")}'),
                 ("Severity", f'<span class="sev {escape(sev)}">{escape(sev.title())}</span>'),
                 ("Topic", f'{escape(str(a.get("name") or "—").title())} · '
                           f'{escape(str(ins.get("concern") or "").replace("_", " "))}'),
                 ("Reported", f'“{escape(ins.get("query_summary") or "—")}”'),
                 ("Advice", f'“{escape(ins.get("advice_summary") or "—")}”')])),
             ("Decide", "rules R1–R8", kv([("Decision", f'<b>{d.rule} · {"Survey" if d.survey else "No survey"}</b>'
                                                        f' · {escape(why)}')]))]
    recall = [("Remembers", f"<b>{r}</b> · {escape(w)}") for r, w in notes]
    if d.survey and attention and attention.get("tier") != "neutral":
        recall.append(("Attention", f'<b>{escape(attention["tier"].replace("_", " "))}</b> · {escape(attention["explanation"])}'))
    if recall:
        steps.append(("Recall", f"history of {ins.get('farmer_id')}", kv(recall)))
    if d.survey:
        h = out["handoff"]
        ok, total, failed = guard_checks(out["surveys"])
        steps.append(("Check", "survey", kv([("Checklist", f'<span class="{"fail" if failed else "pass"}">{ok} / {total} passed</span>'
                                                           + (f' · ✕ {escape(", ".join(failed))}' if failed else ""))])))
        decision, reason = admits.get(h["handoff_id"], ("sent", ""))
        held = "" if decision == "sent" else f' · {escape(decision.replace("_", " "))} by weekly limit: {escape(us_text(reason))}'
        steps.append(("Schedule", "hand-off", kv([("Sends", f'<b>{long(d.send_time["send_at"])}</b><br>{_route(h)}{held}'),
                                                  ("Next survey", _next_survey(h))])))
        say = "Survey ready. Handed to the scheduler."
    else:
        say = "No survey. A person calls this farmer instead." if d.rule == "R2" else f"No survey: {RULE_LABEL[d.rule].lower()}."
    body = "".join(f'<div class="step" style="--i:{k}"><div class="call"><i>⏺</i><b>{name}</b>(<em>{escape(arg)}</em>)</div>'
                   f'<div class="res"><span class="elbow">⎿</span>{res}</div></div>' for k, (name, arg, res) in enumerate(steps))
    t = 0.3 + 0.6 * len(steps)  # when the last step is in: the status turns to "✻ … for Ns", the mascot smiles
    verb, done = AGENT_VERBS[sum(map(ord, str(ins.get("insight_id")))) % len(AGENT_VERBS)]
    secs, tokens = max(1, round(t)), len(re.sub(r"<[^>]+>", "", body)) // 3 + 380
    html(f'<div class="mel-agent" style="--t:{t:.2f}s;--secs:{secs};--toks:{tokens};--spins:{max(1, round(t / .8))};'
         f'--m:{max(1, round(t))}">{body}'
         f'<div class="status"><span class="spin"></span><span class="run">{verb}… <em>(<i class="sec"></i>s · ↓ '
         f'<i class="tok"></i> tokens · thinking some more with max effort)</em></span>'
         f'<span class="fin">{done} for {secs}s</span></div>'
         f'<div class="foot">{MASCOT}<div class="bubble">{escape(say)}</div></div></div>')


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


# The sketch's five demo cases, in its order; the first one is the default.
# 4 (empty): no survey at all. 5 (abnormal): F-000208 reported wheat drying in patches on 12/08 (low); four days
# later the same problem is high (history rule H5 asks whether the earlier advice was followed).
DEMO_PICKS = {"I-001253": "1 · High: goat, vet follow-up", "I-001645": "2 · Medium: lentil nutrient care",
              "I-005625": "3 · Low: stored mustard", "I-000291": "4 · Edge, empty: no survey (critical cow)",
              "I-001996": "5 · Edge, abnormal: low turned high (wheat)"}
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
    # Top bar, as in the sketch: the demo case on the left, the channel next to it (filled once the case is known),
    # then the user's own insight, never inside the dropdown.
    # One level row: the case and the channel on the left, the insight buttons at the right edge. Everything that
    # changes the preview itself lives in the two view headers below (What if… left, language + restart right).
    bar = st.columns([2.2, 1.3, 2.1], vertical_alignment="bottom")
    acts = bar[2].container(horizontal=True, horizontal_alignment="right", vertical_alignment="bottom", gap="small",
                            key="studio_acts")
    if own:
        pick = None
        a0 = (sub["insight"].get("asset") or {}) if sub else {}
        what = (f"{str(a0.get('name') or '').title()}: {str(sub['insight'].get('concern') or '').replace('_', ' ')}"
                if sub else "draft, no report yet")
        bar[0].markdown(f'<div class="mel-source"><div class="mel-k">Source</div><b>Your insight</b>'
                        f'<span>{escape(what)}</span></div>', unsafe_allow_html=True)
        acts.button("Hide editor" if st.session_state["editor_open"] else "Edit insight", key="own_toggle",
                    icon=":material/edit:", on_click=_toggle_editor)
        acts.button("Back to the demos", key="own_back", on_click=_back_to_demos)
    else:
        # The picker's widget key is dropped while own mode hides it; last_pick (plain state) brings it back.
        st.session_state.setdefault("studio_pick", st.session_state.get("last_pick", next(iter(picks), BROWSE)))
        pick = bar[0].selectbox("Demo case", [*picks, BROWSE], key="studio_pick", format_func=lambda k: picks.get(k, k))
        st.session_state["last_pick"] = pick
        if sub:
            acts.button("Your insight", key="own_show", icon=":material/person:", on_click=_show_own)
        acts.button("Add your own insight", key="own_add", icon=":material/add:", on_click=_open_own)
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
        mem, pretend, restart, notes = None, "none", False, []
        # The attention the batch computed for this insight (the app runs with attention on). "What if…" can
        # override it with a made-up tier, because the pack's activity is flat with no designed surges.
        attention, pretend_att = getattr(d, "attention", None), next(iter(PRETEND_ATT))
        col_a, col_f = st.columns([1.05, 1], gap="large")
        # Two headers of the same height, so the agent's panel and the phone start on the same line.
        head = col_a.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                               key="agent_head")
        head.markdown('<div class="mel-sec">Agent\'s view</div>', unsafe_allow_html=True)
        fhead = col_f.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                                key="farmer_head")
        fhead.markdown('<div class="mel-sec">Farmer\'s view</div>', unsafe_allow_html=True)
        if d.survey:
            # The farmer's controls sit at the right of the Farmer's view header (William's ask): the English/Hindi
            # switch, then Restart (and the speaker on voice). History rules H1-H5 are always on here (team
            # decision 4 Nov); scoring and the CLI keep them off.
            # English by default so judges can read along. The phone's key includes the language, so each
            # language keeps its own place in the survey.
            tools = fhead.container(horizontal=True, width="content", gap="small", vertical_alignment="center",
                                    key="farmer_ctl")
            tools.markdown('<span class="mel-lang">English</span>', unsafe_allow_html=True)
            hindi = tools.toggle("Hindi", key="lang_hi")
            langs = list(out["surveys"])
            lang = "hi-IN" if hindi and "hi-IN" in langs else ("en-IN" if "en-IN" in langs else langs[0])
            # Icon-only: the label is the accessible name, hidden visually by app/theme.py (.st-key-studio_restart).
            restart = tools.button("Restart survey", key="studio_restart", icon=":material/restart_alt:",
                                   width="content", help="Restart survey")
            # Icon-only like Restart: the label stays as the accessible name, clipped off screen by app/theme.py.
            with head.popover("What if…", icon=":material/tune:", key="studio_whatif",
                              help="What if… pretend a different history or activity for this farmer (demo only)"):
                pretend = st.selectbox("Pretend this farmer's survey history", PRETEND)
                pretend_att = st.selectbox("Pretend activity pattern", list(PRETEND_ATT),
                                           help="The pack's activity is flat with no designed surges, so this made-up "
                                                "pattern shows how a surge or steady-high farmer is treated differently.")
            if PRETEND_ATT[pretend_att] is not None:
                attention = PRETEND_ATT[pretend_att]
            mem = copy.copy(memory())
            mem.responses = __import__("collections").defaultdict(list)
            when = lambda days: (datetime.fromisoformat(ins["created_at"]) - timedelta(days=days)).isoformat()
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
            ch = bar[1].selectbox("Channel", CHANNELS, index=CHANNELS.index(first_ch), format_func=CH_NAME.get,
                                  help="Defaults to the first channel the scheduler tries for this farmer.")
            if ch == "voice":
                sound_button(tools)
            notes = [(r, us_text(w)) for r, w in history_notes(ins, mem, attention)]
        else:
            bar[1].selectbox("Channel", ["—"], disabled=True, help="No survey, so there is nothing to preview.")
        with col_a:
            agent_view(ins, out, d, notes, attention)
        if not d.survey:
            with col_f:
                who = "A person calls this farmer instead." if d.rule == "R2" else "Nothing is sent to this farmer."
                html(f'<div class="mel-empty"><b>No survey</b>{escape(who)}<br>{d.rule} · {escape(RULE_LABEL[d.rule])}</div>')
                with st.expander("Developer details: no-survey record (JSON)"):
                    st.json(out["no_survey"])
        else:
            surveys = out["surveys"]
            sv = clean(surveys[lang])
            with col_f:
                if lang == "hi-IN":  # label Hindi until every line in P4's sheet has a reviewer's Y/N
                    sheet = pd.read_csv(HINDI_SHEET, dtype=str, keep_default_na=False)
                    done = int((sheet["reviewer_ok(Y/N)"].str.strip() != "").sum())
                    if done < len(sheet):
                        st.caption(f"Hindi pending review: {done} of {len(sheet)} lines checked by a native speaker")
                # restart=True resets the phone before it is drawn; show_restart=False hides the phone's own
                # "Start over", so the Restart icon above the agent's view is the only reset control.
                pkey = f"preview|{ins['insight_id']}|{ch}|{lang}|{pretend}|{pretend_att}|{mem is not None}"
                rec = render_channel_preview(sv, ch, key=pkey, send_at=d.send_time["send_at"] if ch == first_ch else None,
                                             restart=restart, show_restart=False)
                if ch == "voice":
                    voice_readout(sv, pkey, rec)
            with col_a:
                if rec is None:
                    st.caption("The farmer's answers appear here when the conversation ends.")
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

# ---------------------------------------------------------------- footer (farmer.chat's forest band)
html(f'<div class="mel-foot">{LOCKUP}<div>MEL Survey Agent</div></div>')
