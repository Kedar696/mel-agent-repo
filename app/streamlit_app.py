"""Fasal Pulse - MEL Survey Agent: the team demo. Owner: P5.  Run: streamlit run app/streamlit_app.py
P4's standalone survey demo (demo/p4_standalone) is folded in: Survey demo shows what the agent remembers
about the farmer and how history rules H1-H5 adapt the survey (on in the app, off for scoring).
Tabs: Dashboard (default: overview + evaluation), Survey demo (insight | interactive channel preview | hand-off). Look and feel: app/theme.py. Interactive preview: app/channel_preview.py.
Every number on screen comes from the real pipeline; nothing is hard-coded."""
import copy
import json
import os
import re
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
import streamlit.components.v1 as components


def _reload_mel_if_changed():
    """Streamlit reruns this file when code changes (local `git pull`),
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
from mel.writer import (check_survey, write_surveys, FarmerMemory, history_notes, llm, relevance, RELEVANCE_THRESHOLD)
from mel.writer.templates import template_items

sys.modules["mel"]._code_stamp = _MEL_STAMP  # see _reload_mel_if_changed

from app import custom_context as cc
from app import tts
from app.display_time import (format_clock, format_date, format_datetime, format_dates_in_text,
                              use as use_zone, zone_label)

use_zone(None)   # the numbers in Eastern Time; one farmer's screen switches to India time below (Survey demo, queue)
from app import dashboard
from app.channel_preview import render_channel_preview
from app.theme import LOCKUP, MASCOT, apply_theme

sys.modules["app"]._code_stamp = _APP_STAMP  # see _reload_mel_if_changed

APP_NAME = "Fasal Pulse - MEL Survey Agent"
# Bedrock writes only where the demo shows a survey being written (bedrock_surveys, own_insight_run, the agent
# panel). The batch at start-up, the scoring numbers and every other survey stay templates, whatever MEL_USE_LLM
# says: they never spend tokens, and 2,616 surveys would take 30 minutes before the first screen.
BEDROCK_ON = llm.enabled()
llm.override(False)
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
OUT_BY_ID = {i.get("insight_id"): o for i, o in rows}
html(f'<div class="mel-mast"><div class="mel-brand">{LOCKUP}</div>'
     '<div class="mel-head"><h1 class="mel-title">MEL Survey Agent</h1></div></div>')
tab_over, tab_studio = st.tabs(["Dashboard", "Survey demo"])

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
    dashboard.render(rows=rows, admits=admits, upcoming=upcoming, evaluate_fn=_evaluate, rule_label=RULE_LABEL,
                     ch_name=CH_NAME, channels=CHANNELS)

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


def _planned_next(h):
    """(send start, insight id) of this farmer's next batch survey that gets past the weekly limit, or None."""
    me, start = h["survey"]["source_insight_ids"][0], h["send_window"]["not_before"]
    return next(((t, iid) for t, iid in upcoming.get(h["survey"]["farmer_id"], []) if t > start and iid != me), None)


def _why(out, d, lang):
    """The decision's reason in plain words (the survey rationale, or the no-survey reason without its code)."""
    return us_text(out["surveys"][lang]["rationale"].split(" Personalised:")[0] if d.survey
                   else re.sub(r"^\[[^\]]*\]\s*", "", out["no_survey"]["reason"]))  # drop the "[R5 code]" prefix


def agent_view(ins, out, d, notes, attention, review=None, chat=(), shown=0) -> int:
    """The agent at work, styled like a Claude Code session (William's ask): one "⏺ Tool(args)" step per stage with
    an indented "⎿" result on a dark terminal, a spinner status line that ticks seconds and tokens and ends as
    "✻ <verb> for Ns", then the mascot. CSS-only motion: Streamlit keeps this HTML in place while the farmer taps,
    so it plays once per case, not on every tap. `review` = (steps, line) from review_steps once the farmer has
    answered, `chat` = what the viewer typed in the terminal and the answers. The first `shown` steps were played
    on an earlier run and stay still; only the new ones play. Returns the step count (the next `shown`)."""
    a, loc = ins.get("asset") or {}, ins.get("location") or {}
    sev = ins.get("severity") or "n/a"
    fid = escape(str(ins.get("farmer_id")))
    why = _why(out, d, ins["conversation_language"])

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
        steps.append(("Schedule", "hand-off", kv([("Sends", f'<b>{long(d.send_time["send_at"])}</b><br>{_route(h)}{held}')])))
        say = "Survey ready. Handed to the scheduler."
    else:
        say = "No survey. A person calls this farmer instead." if d.rule == "R2" else f"No survey: {RULE_LABEL[d.rule].lower()}."
    lines = lambda at: [("Ask", c["q"], c["a"]) for c in chat if c.get("at") == at]
    steps = lines("top") + steps + lines("agent")
    if review:
        steps, say = steps + review[0], review[1]
    steps += lines("review")
    first = min(shown, len(steps))

    def step(k, name, arg, res):
        cls = "step" + (" done" if k < first else "") + {"Think": " think", "Ask": " ask"}.get(name, "")
        call = ('<i>✻</i><em>Thinking…</em>' if name == "Think" else f'<i>❯</i><span>{escape(arg)}</span>' if name == "Ask"
                else f'<i>⏺</i><b>{name}</b>(<em>{escape(arg)}</em>)')
        return (f'<div class="{cls}" style="--i:{k - first}"><div class="call">{call}</div>'
                f'<div class="res"><span class="elbow">⎿</span><div>{res}</div></div></div>')
    body = "".join(step(k, *s_) for k, s_ in enumerate(steps))
    t = 0.3 + 0.6 * (len(steps) - first)  # when the last new step is in: the status turns to "✻ … for Ns", the mascot smiles
    verb, done = AGENT_VERBS[sum(map(ord, str(ins.get("insight_id")))) % len(AGENT_VERBS)]
    secs, tokens = max(1, round(t)), len(re.sub(r"<[^>]+>", "", body)) // 3 + 380
    html(f'<div class="mel-agent" style="--t:{t:.2f}s;--secs:{secs};--toks:{tokens};--spins:{max(1, round(t / .8))};'
         f'--m:{max(1, round(t))}"><div class="scroll" tabindex="0" aria-label="Agent log"><div class="log">{body}'
         f'<div class="status"><span class="spin"></span><span class="run">{verb}… <em>(<i class="sec"></i>s · ↓ '
         f'<i class="tok"></i> tokens · thinking some more with max effort)</em></span>'
         f'<span class="fin">{done} for {secs}s</span></div></div></div>'
         f'<div class="foot">{MASCOT}<div class="bubble">{escape(say)}</div></div></div>')
    return len(steps)


FU_LABEL = {"advice_did_not_work": "the advice didn't work", "crop_or_animal_damaged": "the crop or animal was damaged",
            "could_not_get_input": "they couldn't get the inputs", "could_not_reach_expert": "they couldn't reach the expert"}
FU_ACTION = {"advice_did_not_work": "a person re-checks the advice and calls with a corrected recommendation",
             "crop_or_animal_damaged": "a person assesses the damage and connects the farmer to a vet or extension worker",
             "could_not_get_input": "a person shares the nearest input supplier or a subsidy",
             "could_not_reach_expert": "a person books a call with the nearest agriculture expert"}
RETRY = ("retry_same_channel", "fall_back_to_next_channel")


def _answer_label(item, value):
    if item["type"] == "survey-scale":
        return f"{value} / {item.get('scale_max', '?')}"
    return next((o["label"] for o in item.get("options", []) if o["value"] == value), str(value))


def _judge_score(insight_id):
    """The AI judge's 1-5 score for the recorded Bedrock survey of this conversation, if one was recorded."""
    run = _recorded_run(insight_id) or {}
    scores = [(e.get("data") or {}).get("judge") for e in run.get("events", []) if e.get("step") == "verifier"]
    return next((x for x in reversed(scores) if x is not None), None)


def plan_next(h, rec, lang):
    """The agent's next step once the farmer has answered, by the scheduler's rules (docs/cap_policy.md): a retry of
    this survey first; then the next survey already in the batch; else the earliest day the weekly limit allows one.
    -> (another survey?, [(label, html)], one line for the thinking)."""
    if rec["status"] == "declined":
        return False, [("Next survey", "<b>No</b> · the farmer opted out; we never ask again")], \
            "The farmer opted out, so the only right move is to stop."
    if rec["retry_decision"] in RETRY:
        wait = rec.get("retry_after_minutes") or 0
        at = datetime.fromisoformat(rec["recorded_at"]) + timedelta(minutes=wait)
        how = "same channel" if rec["retry_decision"] == "retry_same_channel" else "the next channel in the farmer's order"
        return True, [("Next survey", "<b>Yes, this one again</b> · it did not get through"),
                      ("When", f"<b>{long(at)}</b>"), ("Channel", how)], \
            "The survey did not get through, so the same questions go out again before anything new."
    nxt = _planned_next(h)
    if nxt:
        a, o = INSIGHT_BY_ID.get(nxt[1]) or {}, OUT_BY_ID.get(nxt[1]) or {}
        sv = (o.get("surveys") or {}).get(lang) or next(iter((o.get("surveys") or {}).values()), None)
        topic = f'{str((a.get("asset") or {}).get("name") or "").title()} · {str(a.get("concern") or "").replace("_", " ")}'
        rows_ = [("Next survey", "<b>Yes</b>"), ("When", f"<b>{long(nxt[0])}</b>"),
                 ("What", f"{escape(topic)} <small>(their conversation of {format_date(a['created_at'])})</small>"
                  if a.get("created_at") else escape(topic))]
        if sv:
            rows_.append(("Opens with", f"“{escape(sv['items'][0]['prompt'])}”"))
        if o.get("handoff"):
            rows_.append(("Channel", _route(o["handoff"])))
        about = f'{(a.get("asset") or {}).get("name") or "the crop"} ({str(a.get("concern") or "").replace("_", " ")})'
        return True, rows_, (f"This farmer has since asked about {escape(about)}. That survey is already planned for "
                             f"{format_date(nxt[0])}, 7 days after this one, so it respects the weekly limit.")
    if not rec["counts_toward_cap"]:
        return False, [("Next survey", "<b>Only when needed</b> · this attempt does not count toward the weekly limit")], \
            "Nothing else from this farmer needs checking yet."
    me, fid = h["survey"]["source_insight_ids"][0], h["survey"]["farmer_id"]
    start = next((t for t, iid in upcoming.get(fid, []) if iid == me), h["send_window"]["not_before"])  # moved? its new day
    gate = datetime.fromisoformat(start) + timedelta(days=7)
    return False, [("Next survey", "<b>Not yet</b> · only when a new conversation needs one"),
                   ("Earliest", f"<b>{format_date(gate)}</b> · 7 days after this send (weekly limit)")], \
        "Nothing else from this farmer needs checking, and the weekly limit holds the next survey for 7 days."


def review_steps(ins, out, h, sv, rec, lang, ch):
    """What the agent does once the farmer's conversation ends: read the answers, judge the survey, think it over,
    and plan the next step. -> (steps for agent_view, the mascot's line). Every fact comes from the record P3's
    simulator built from the real taps, the checks, and the batch; nothing is invented."""
    got = {e["item_id"]: e for e in rec["items"]}
    answered = [it for it in sv["items"] if got.get(it["item_id"], {}).get("result") == "answered"]
    qa = "".join(f'<div class="qa"><span>{escape(it["prompt"])}</span><b>'
                 + (escape(_answer_label(it, got[it["item_id"]]["value"])) if it in answered else "<small>no answer</small>")
                 + "</b></div>" for it in sv["items"])
    status = rec["status"].replace("_", " ").capitalize()
    flags = [FU_LABEL.get(r, r.replace("_", " ")) for r in rec["follow_up_reasons"]]
    steps = [("Review", f"answers from {CH_NAME.get(ch, ch)}", f'<dl class="kv"><dt>Status</dt><dd><b>{escape(status)}</b> · '
              f'{len(answered)} of {len(sv["items"])} answered · {short(rec["recorded_at"])}</dd>'
              f'<dt>Answers</dt><dd>{qa}</dd>'
              + (f'<dt>Flag</dt><dd><span class="fail">⚑ {escape("; ".join(flags))}</span></dd>' if flags else "") + "</dl>")]

    ok, total, failed = guard_checks(out["surveys"])
    rel = relevance(sv, ins)
    judge = _judge_score(ins["insight_id"]) if out["surveys"][lang].get("_source") == "bedrock" else None
    full = len(answered) == len(sv["items"])
    good = not failed and rel >= RELEVANCE_THRESHOLD and full
    verdict = ("Good survey" if good else "Usable, with gaps" if not failed and answered else "Weak survey")
    why = ("safe, on topic and every question answered" if good else
           f"{len(sv['items']) - len(answered)} question(s) unanswered" if not failed and answered else
           "it failed a check" if failed else "the farmer answered nothing")
    steps.append(("Assess", "survey quality", f'<dl class="kv"><dt>Checks</dt><dd><span class="{"fail" if failed else "pass"}">'
                  f'{ok} / {total} passed</span>' + (f' · ✕ {escape(", ".join(failed))}' if failed else "")
                  + f'</dd><dt>Relevance</dt><dd><b>{rel:.2f}</b> <small>(0 to 1; the send bar is {RELEVANCE_THRESHOLD})</small></dd>'
                  + (f'<dt>AI judge</dt><dd><b>{judge} / 5</b> <small>(Gemma 3 12B, recorded run)</small></dd>' if judge else "")
                  + f'<dt>Verdict</dt><dd><span class="{"pass" if good else "warn"}">{verdict}</span> · {why}</dd></dl>'))

    again, plan, plan_thought = plan_next(h, rec, lang)
    thoughts = [f"The farmer says {escape(' and '.join(flags))}. A person should call before we ask anything else: "
                f"{escape('; '.join(FU_ACTION.get(r, 'a person follows up') for r in rec['follow_up_reasons']))}."
                if flags else
                "Every answer is in and none of them points to trouble, so the advice looks like it is working."
                if full else
                f"Only {len(answered)} of {len(sv['items'])} answers came back; the record keeps what we got and we do not chase the rest."
                if answered else "No answers came back; the record says why."]
    thoughts.append(f"The questions stayed on topic (relevance {rel:.2f}) and short enough to answer in about a minute."
                    if not failed and rel >= RELEVANCE_THRESHOLD else "The survey itself needs work before it is reused.")
    thoughts.append(plan_thought)
    steps.append(("Think", "", "".join(f"<p>{t}</p>" for t in thoughts)))
    steps.append(("Plan", "next step", '<dl class="kv">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in plan) + "</dl>"))
    when = next((v for k, v in plan if k == "When"), "")
    say = ("A person should call this farmer first." if flags else
           f"{verdict}. Next one {re.sub(r'<[^>]+>', '', when)}." if again and when else
           f"{verdict}. Nothing else to ask yet.")
    return steps, say


# One strong example (William, 5 Nov): F-000208 reported wheat drying in patches on 12/08 (low); four days later the
# same problem is high. The agent remembers the first report (H5), Bedrock wrote the survey (judge 5/5, recorded from
# AgentCore), and the batch already holds this farmer's next survey, so the closing plan is concrete.
EXAMPLE = {"I-001996": "Wheat drying in patches: low turned high"}
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
    reseed = st.session_state.get("custom_reseed")   # Bedrock read the last submission: its Details win over the
    if reseed:                                        # widget values still around from the run that submitted
        draft.update(reseed)
    else:
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


def _agent_key(ins, attention, mem_present: bool) -> str:
    """Where the agent panel keeps a run's events (one per conversation, attention tier and memory setting)."""
    return f"agent_events|{ins['insight_id']}|{attention is not None and attention.get('tier')}|{mem_present}"


def own_insight_run(fields: dict, n: int) -> dict:
    """The user's conversation through the pipeline. With Bedrock on (and the box ticked), the model first reads the
    conversation and fills in the Details: crop or animal, problem, severity, advice type, days to act, when to check
    back and how many questions. P2's rules then decide survey or not and the send window from those fields, and the
    agent writes and checks the questions with Bedrock (English, then a Hindi translation). Without Bedrock: the
    Details as typed and the checked templates."""
    from mel.agent import run_agent
    from mel.decision import decide
    with llm.writer(BEDROCK_ON):
        read = (llm.read_conversation(fields["question"], fields["advice"])
                if BEDROCK_ON and st.session_state.get("cc_read", True) else None)
        if read:
            fields.update(cc.apply_reading(fields, read))  # the draft is this dict: the Details now show what the model read
            st.session_state["custom_reseed"] = {f: fields[f] for f in EDITOR_KEYS}
        sub = cc.submission(fields, n)
        sub["read"], sub["fields"] = read, dict(fields)
        ins = sub["insight"]
        if not BEDROCK_ON:
            sub["out"] = run_insight(ins, memory=memory())
            sub["bedrock_note"] = "from the checked template (Bedrock is off on this machine)"
            return sub
        evs = list(run_agent(ins, memory=None, n_items=sub.get("questions")))   # one agent run, no second writer call
    res = evs[-1] if evs and evs[-1].get("step") == "result" else {}
    d = decide(ins)                                                           # the same call the agent made
    out = {"decision": d, "no_survey": None if d.survey else d.no_survey_record(ins)}
    sub["bedrock_note"] = None
    if d.survey and res.get("surveys"):
        out.update(surveys=res["surveys"], handoff=res["handoff"])
        m = res.get("metrics") or {}
        src = res["surveys"].get(ins["conversation_language"], {}).get("_source")
        sub["bedrock_note"] = (f"written by Bedrock just now ({llm.write_model()}) · {m.get('seconds', 0):.1f} s · "
                               f"${m.get('cost_usd') or 0:.4f}" if src == "bedrock" else
                               "from the checked template: the Bedrock draft failed the checks twice")
        st.session_state[_agent_key(ins, d.attention, True)] = evs            # the agent panel shows this run
    elif d.survey:                                                            # the agent run broke: the templates
        out, sub["bedrock_note"] = run_insight(ins, memory=memory()), "from the checked template (the agent run failed)"
    sub["out"] = out
    return sub


def own_insight_editor(draft: dict) -> bool:
    """The editor for the user's own insight (app/custom_context.py does the mapping). Drawn only while open.
    Returns True right after a valid submission; the pipeline runs only then, never on reopen or rerender."""
    reseed = st.session_state.pop("custom_reseed", None)  # the widgets are not drawn yet, so their keys may be set
    for field, wkey in EDITOR_KEYS.items():
        if reseed:
            st.session_state[wkey] = draft[field]            # show what Bedrock read (apply_reading)
        else:
            st.session_state.setdefault(wkey, draft[field])  # re-seed from the draft (keys are gone after hiding)
    with st.container(border=True, key="own_editor"):
        st.caption("Type a FarmerChat conversation. With Bedrock on, the model reads it and fills in the Details; "
                   "otherwise the Details decide the survey, not the text. The same rules, writer and checks run on "
                   "it, and nothing you type joins the numbers.")
        t = st.columns(2)
        t[0].text_area("What the farmer asked", key="cc_question", height=96,
                       placeholder="Small green insects on the mustard flowers, what should I do?",
                       help="Shown on the green card as typed.")
        t[1].text_area("Advice FarmerChat gave", key="cc_advice", height=96,
                       placeholder="Spray neem oil in the evening and check the plants after three days.",
                       help="Leave empty if no advice was given yet: there is nothing to check, so no survey. Without "
                            "Bedrock no model reads the text: the questions follow the Details, plus a few keywords in the advice.")
        st.checkbox("Let Bedrock read the conversation and fill in the Details: crop, problem, severity, advice type, "
                    "days to act, when to check back, how many questions", key="cc_read", value=True,
                    disabled=not BEDROCK_ON,
                    help="Needs MEL_USE_LLM=1 and AWS keys on this machine. The model's reading replaces the Details "
                         "below; untick it to use the Details as you set them.")
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
            st.caption(f"Dates show in {zone_label()}. The conversation is stamped with the real current time; the rules "
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
    with st.spinner("Bedrock is reading the conversation and writing the survey…" if BEDROCK_ON else "Building the survey…"):
        sub = own_insight_run(fields, n)
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
        st.caption("Add ELEVENLABS_API_KEY to the repo's .env (copy .env.example) or, on the hosted copy, as a container secret, then rerun to hear the call.")
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


def bedrock_surveys(ins, out, attention):
    """-> (out, note): the Bedrock-written surveys for a pack conversation in place of the batch's template. First
    the run recorded from AgentCore (docs/results/agent_runs/), else a live run of the agent when Bedrock is on
    (its answers are cached on disk and in docs/results/bedrock_cache.jsonl, so a repeat costs $0), else the batch's
    checked template as it was. The note says which, for the caption above the phone."""
    from mel.agent import run_agent
    rec = _recorded_run(ins["insight_id"])
    res = rec["events"][-1] if rec and rec.get("events") and rec["events"][-1].get("step") == "result" else None
    note = "from the checked template (Bedrock is off on this machine)"
    if res and res.get("surveys"):
        note = (f"written by Bedrock ({rec.get('writer') or 'model'}), recorded from "
                f"{'Amazon Bedrock AgentCore' if rec.get('where') == 'agentcore' else 'a Bedrock run'} on {rec.get('recorded', '?')}")
    elif BEDROCK_ON:
        key = _agent_key(ins, attention, True)
        with llm.writer(True):
            evs = st.session_state.get(key) or list(run_agent(ins, memory=None, attention=attention, **_agent_inputs(ins)))
        st.session_state[key] = evs                       # the agent panel shows the same run, no second call
        res = evs[-1] if evs and evs[-1].get("step") == "result" else None
        m = (res or {}).get("metrics") or {}
        note = (f"written by Bedrock just now ({llm.write_model()}) · {m.get('seconds', 0):.1f} s · "
                f"${m.get('cost_usd') or 0:.4f}" + (" (answered from the cache)" if m.get("cached") else ""))
    if not res or not res.get("surveys"):
        return out, note
    surveys = res["surveys"]
    if not any(s.get("_source") == "bedrock" for s in surveys.values()):
        return out, "from the checked template: the Bedrock draft failed the checks twice"
    farmer_copy = clean(surveys.get(ins["conversation_language"]) or next(iter(surveys.values())))
    return {**out, "surveys": surveys, "handoff": build_handoff(ins, farmer_copy, attention)}, note


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
             "this machine, writing with Bedrock" if BEDROCK_ON else "this machine, templates only (no AWS keys here)")
    st.caption("Four steps, as in our AWS design: the **Evidence Extractor** gathers what we know, the **Analyst** "
               "decides and drafts, the **Verifier** checks (safety, relevance, short questions, Guardrails), and a "
               "rejected draft goes back to the Analyst at most twice before the safe template is used. The "
               f"**Synthesizer** builds the files. Runs on: {where}.")
    key = _agent_key(ins, attention, mem is not None)
    c = st.columns([1, 2.4], vertical_alignment="center")
    if c[0].button("Run the agent", key=f"run_{key}", icon=":material/play_arrow:"):
        events = []
        from mel.evaluation.costs import CostMeter, record_cost, row_from_results
        meter = CostMeter()
        with st.status("The agent is working…", expanded=True) as box, llm.writer(BEDROCK_ON):
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
                                         writer=llm.write_model() if BEDROCK_ON else None,
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


def _set_stage(flow: str, stage: int):
    st.session_state[flow] = stage


def _restart_flow(flow: str):
    st.session_state.update({flow: 0, f"{flow}|fresh": True,   # the phone starts from its first screen next time
                             f"{flow}|chat": [], f"{flow}|shown": 0})


COMMANDS = {"start": "start", "read": "start", "go": "start", "run": "start", "send": "send", "restart": "restart",
            "reset": "restart", "help": "help"}
QUESTIONS = (("why", ("why", "decid", "rule", "reason")), ("quality", ("quality", "good", "score", "check", "judge", "relevan")),
             ("next", ("next", "when", "again", "plan", "follow")), ("history", ("history", "remember", "before", "memory", "earlier")),
             ("help", ("help", "what can", "?")))
ASK_HINT = "Ask why, quality, next or history. Commands: start, send, restart."


def _intent(text: str) -> str:
    """A one-word command (start, send, restart, help), else the question the text is about, by keyword."""
    w = text.lower().strip().strip("/!.? ")
    return COMMANDS.get(w) or next((name for name, keys in QUESTIONS if any(k in w for k in keys)), "unknown")


def _ask(flow: str):
    """The terminal's input (runs before the script): a command moves the flow now; the answer is written during the
    run, when the case's facts are at hand."""
    q = (st.session_state.get(f"ask|{flow}") or "").strip()
    if not q:
        return
    cmd, stage = _intent(q), st.session_state.get(flow, 0)
    if cmd == "restart":
        return _restart_flow(flow)
    if cmd == "start" and stage == 0:
        st.session_state[flow] = 1
    elif cmd == "send" and stage == 1 and st.session_state.get(f"{flow}|survey"):
        st.session_state[flow] = 2
    st.session_state.setdefault(f"{flow}|chat", []).append({"q": q, "cmd": cmd, "stage": stage})


def answer(c, ins, out, d, notes, sv, rec, h, lang) -> str:
    """The agent's reply to one line typed in the terminal, from this case's facts only (HTML)."""
    cmd, stage = c["cmd"], c["stage"]
    if cmd == "start":
        return "Reading the conversation." if stage == 0 else "I already have this conversation."
    if cmd == "send":
        if not d.survey:
            return f"There is no survey to send: {escape(RULE_LABEL[d.rule].lower())}."
        return ("Hand me the conversation first: drag it in, or type <b>start</b>." if stage == 0 else
                "Sent. The survey is on the farmer's phone." if stage == 1 else "It is already on the farmer's phone.")
    if cmd == "why":
        return f'<b>{d.rule} · {"Survey" if d.survey else escape(RULE_LABEL[d.rule])}</b> · {escape(_why(out, d, lang or ins["conversation_language"]))}'
    if cmd == "history":
        return ("; ".join(f"<b>{r}</b> {escape(w)}" for r, w in notes) or
                "Nothing earlier from this farmer changes this survey.")
    if cmd == "quality":
        if not d.survey:
            return "No survey was written, so there is nothing to grade."
        ok, total, failed = guard_checks(out["surveys"])
        judge = _judge_score(ins["insight_id"]) if out["surveys"][lang].get("_source") == "bedrock" else None
        return (f'Checks <span class="{"fail" if failed else "pass"}">{ok} / {total}</span> · relevance '
                f'<b>{relevance(sv, ins):.2f}</b> (send bar {RELEVANCE_THRESHOLD})' + (f" · AI judge <b>{judge} / 5</b>" if judge else "")
                + (". The answers are graded above." if rec else ". I grade the answers once the farmer replies."))
    if cmd == "next":
        if not d.survey:
            return "No survey for this conversation, so nothing to follow up."
        if rec:
            return " · ".join(f"{k}: {v}" for k, v in plan_next(h, rec, lang)[1])
        return (f'It goes out <b>{long(d.send_time["send_at"])}</b> via {_route(h)}. Once the farmer answers, '
                "I decide on the next survey.")
    return ASK_HINT


FLOW_STEPS = (("The agent reads the conversation", "Drag the conversation onto the terminal", "Survey ready: press Send to the farmer"),
              ("The farmer answers", "Answer on the phone as the farmer would", ""),
              ("The agent reviews and plans", "How good was the survey, and what comes next", ""))


def flow_steps(stage: int, survey: bool, answered: bool) -> str:
    """The three-step strip above the two views; the current step is lit and says what to do now."""
    now = 0 if stage < 2 else (2 if answered else 1)
    out = []
    for k, (title_, cue0, cue1) in enumerate(FLOW_STEPS):
        if not survey and k and stage >= 1:
            state, cue = "skip", "No survey for this conversation"
        else:
            state = "done" if k < now or (k == 2 and answered) else "now" if k == now else ""
            cue = (cue1 if k == 0 and stage == 1 else cue0) if state == "now" or (k == 2 and answered) else ""
        out.append(f'<div class="s {state}"><b>{"✓" if state == "done" and k < 2 else k + 1}</b><div><span>{title_}</span>'
                   + (f"<small>{escape(cue)}</small>" if cue else "") + "</div></div>")
    return f'<div class="mel-steps">{"".join(out)}</div>'


INTAKE_CSS = """
.intake{display:flex;flex-direction:column;gap:14px}
.card{background:#fff;border:1.5px solid #00C950;border-radius:16px;padding:14px 16px;cursor:grab;touch-action:none;
  user-select:none;-webkit-user-select:none;box-shadow:0 6px 18px rgba(0,130,54,.14);position:relative;z-index:2;
  transition:box-shadow .2s,transform .3s cubic-bezier(.2,.7,.2,1)}
.card:focus-visible{outline:3px solid #00832B;outline-offset:3px}
.card.drag{cursor:grabbing;transition:box-shadow .2s;box-shadow:0 20px 44px rgba(3,46,21,.3)}
.card.in{transition:transform .5s cubic-bezier(.5,0,.75,0),opacity .5s ease;opacity:0}
.head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:11.5px;color:#52525C;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase}
.sev{border-radius:999px;padding:2px 9px;letter-spacing:.02em}
.sev.high,.sev.critical{background:#FCE7E3;color:#9B2C1A}.sev.medium{background:#FFF4D6;color:#7A5200}.sev.low{background:#E3F6E8;color:#0B4524}
.topic{font-size:18px;font-weight:700;color:#09090B;margin-top:8px}
.meta{font-size:13px;color:#52525C;margin-top:2px}
.q{font-size:14.5px;color:#3F3F46;margin-top:10px;line-height:1.45}
.grip{margin-top:12px;font-size:13px;font-weight:600;color:#00832B}
.term{background:#1A1A19;border-radius:16px 16px 0 0;min-height:500px;padding:16px 18px;display:flex;flex-direction:column;
  font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:13px;color:#C9C7BE;transition:box-shadow .2s}
.line{color:#F2F1EC}.line i{font-style:normal;color:#4EBA65;margin-right:8px}
.caret{display:inline-block;width:8px;height:15px;background:#C9C7BE;vertical-align:-3px;margin-left:4px;animation:blink 1s steps(1) infinite}
.hint{margin:auto;text-align:center;color:#8A887F;border:1.5px dashed #4A4944;border-radius:12px;padding:28px 22px;
  max-width:300px;line-height:1.5;transition:border-color .2s,color .2s,opacity .3s}
.term.hot{box-shadow:0 0 0 3px #00C950}.term.hot .hint{border-color:#00C950;color:#F2F1EC}.term.got .hint{opacity:0}
@keyframes blink{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){.caret{animation:none}.card,.card.in,.card.drag{transition:none}}
"""

INTAKE_JS = """
export default function ({ parentElement, data, setTriggerValue }) {
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text; return e; };
  parentElement.querySelector('.intake')?.remove();
  const root = el('div', 'intake');
  const card = el('div', 'card');
  card.tabIndex = 0;
  card.setAttribute('role', 'button');
  card.setAttribute('aria-label', `Conversation ${data.conv}: drag it onto the terminal, or press Enter, to hand it to the agent`);
  const head = el('div', 'head');
  head.append(el('span', '', `FarmerChat conversation · ${data.conv}`), el('span', `sev ${data.sevc}`, data.sev));
  card.append(head, el('div', 'topic', data.topic), el('div', 'meta', data.meta), el('div', 'q', `“${data.asked}”`),
              el('div', 'grip', '⠿  Drag this onto the terminal'));
  const term = el('div', 'term');
  const line = el('div', 'line');
  line.append(el('i', '', '❯'), document.createTextNode('mel agent'), el('span', 'caret'));
  term.append(line, el('div', 'hint', 'Drop the conversation here. The agent reads it, decides, and writes the survey.'));
  root.append(card, term);
  parentElement.append(root);

  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let sx = 0, sy = 0, dx = 0, dy = 0, dragging = false, moved = false, done = false;
  const over = (x, y) => { const r = term.getBoundingClientRect();
    return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom; };
  const hand = () => {
    if (done) return;
    done = true;
    term.classList.add('hot', 'got');
    const c = card.getBoundingClientRect(), t = term.getBoundingClientRect();
    card.classList.add('in');
    card.style.transform = `translate(${dx + t.left + t.width / 2 - (c.left + c.width / 2)}px,` +
                           `${dy + t.top + 90 - (c.top + c.height / 2)}px) scale(.3)`;
    setTimeout(() => setTriggerValue('dropped', data.id), still ? 0 : 520);
  };
  card.addEventListener('pointerdown', e => {
    if (done || e.button > 0) return;
    dragging = true; moved = false; sx = e.clientX; sy = e.clientY; dx = dy = 0;
    card.setPointerCapture(e.pointerId); card.classList.add('drag');
  });
  card.addEventListener('pointermove', e => {
    if (!dragging) return;
    dx = e.clientX - sx; dy = e.clientY - sy;
    if (Math.abs(dx) + Math.abs(dy) > 5) moved = true;
    card.style.transform = `translate(${dx}px,${dy}px) rotate(${Math.max(-4, Math.min(4, dx / 40))}deg)`;
    term.classList.toggle('hot', over(e.clientX, e.clientY));
  });
  card.addEventListener('pointerup', e => {
    if (!dragging) return;
    dragging = false; card.classList.remove('drag');
    if (!moved || over(e.clientX, e.clientY)) return hand();   // a plain click hands it over too
    dx = dy = 0; card.style.transform = ''; term.classList.remove('hot');
  });
  card.addEventListener('pointercancel', () => {
    dragging = false; dx = dy = 0; card.classList.remove('drag'); card.style.transform = ''; term.classList.remove('hot');
  });
  card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); hand(); } });
}
"""

_INTAKE = st.components.v2.component("mel_intake", css=INTAKE_CSS, js=INTAKE_JS)


def intake_card(ins, flow: str):
    """The conversation as a card the viewer drags onto the empty terminal (or clicks, or presses Enter on). Dropping it
    sends a trigger back to Python, which starts the agent (stage 1)."""
    a, loc, sev = ins.get("asset") or {}, ins.get("location") or {}, str(ins.get("severity") or "n/a")
    _INTAKE(data={"id": ins["insight_id"], "conv": ins.get("conversation_id") or ins["insight_id"],
                  "sev": sev.title(), "sevc": sev,
                  "topic": f'{str(a.get("name") or "—").title()} · {str(ins.get("concern") or "").replace("_", " ")}',
                  "meta": f'Farmer {ins.get("farmer_id")} · {loc.get("district") or "—"}, {loc.get("state") or ""} · '
                          f'speaks {LANG_NAME.get(ins.get("conversation_language"), "—")} · {short(ins["created_at"])}',
                  "asked": ins.get("query_summary") or "—"},
            key=f"intake|{ins['insight_id']}", on_dropped_change=lambda: _set_stage(flow, 1))


use_zone("india")   # one farmer's screen: the phone, the send time and the dates are in India time
with tab_studio:
    by_id = {i.get("insight_id"): (i, o) for i, o in rows}
    picks = {k: v for k, v in EXAMPLE.items() if k in by_id}
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
        pick = bar[0].selectbox("Conversation", [*picks, BROWSE], key="studio_pick",
                                format_func=lambda k: f"Example: {picks[k]}" if k in picks else k,
                                on_change=lambda: st.session_state.update(browse_pop=st.session_state.studio_pick == BROWSE))
        st.session_state["last_pick"] = pick
        # Browse: the filters and the conversation list sit behind one Search button; picking a conversation folds it
        # away (the popover's key holds its open state). Its widgets still run while it is closed, so they keep values.
        search = (acts.popover("Search", icon=":material/search:", key="browse_pop", on_change="rerun")
                  if pick == BROWSE else None)
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
            note = (f"Submitted {long(sub['insight']['created_at'])}." + (f" {sub['note']}" if sub["note"] else "")
                    + (f" {cc.reading_note(sub['fields'])}" if sub.get("read") and sub.get("fields") else ""))
        elif not st.session_state["editor_open"]:  # hidden before any report exists: say what to do next
            st.info("Your insight has no report yet. Press Edit insight to finish it, or pick a demo above.")
    elif pick != BROWSE:
        ins, out = by_id[pick]
        kicker, title = "Demo insight", picks[pick]
    else:
        search.markdown("**Search conversations**")
        f = search.columns(2)
        f_dec = f[0].selectbox("Decision", ["All", "Survey", "No survey"], key="f_dec")
        f_rule = f[1].selectbox("Rule", ["All", *RULE_LABEL], key="f_rule",
                                format_func=lambda r: r if r == "All" else f"{r} {RULE_LABEL[r]}")
        f = search.columns(2)
        f_res = f[0].selectbox("Advice type", ["All", *sorted({str(i.get("resolution_type")) for i, _ in rows})], key="f_res")
        f_asset = f[1].selectbox("Crop / animal", ["All", *sorted({str((i.get("asset") or {}).get("name")) for i, _ in rows})],
                                 key="f_asset")
        shown = [k for k, (i, o) in labels.items()
                 if (f_dec == "All" or (f_dec == "Survey") == o["decision"].survey)
                 and (f_rule == "All" or o["decision"].rule == f_rule)
                 and (f_res == "All" or str(i.get("resolution_type")) == f_res)
                 and (f_asset == "All" or str((i.get("asset") or {}).get("name")) == f_asset)]
        if not shown:  # never st.stop() here: it would also stop the tabs after this one
            search.warning("No conversations match these filters; showing all.")
            shown = list(labels)
        key = search.selectbox(f"Conversation ({len(shown):,} match; type to search)", shown, key="browse_conv",
                               on_change=lambda: st.session_state.update(browse_pop=False))
        ins, out = labels[key]
        a0 = ins.get("asset") or {}
        kicker, title = "Browsed insight", f"{str(a0.get('name') or '').title()}: {str(ins.get('concern') or '').replace('_', ' ')} ({ins.get('insight_id')})"
    if ins is not None:
        if kicker != "Demo insight":  # the example is already named in the selector; no repeated heading
            report_strip(kicker, title, note)
        d = out["decision"]
        # The guided flow (William, 5 Nov) leads the eye: 0 the conversation is handed to the agent (drag it onto the
        # terminal), 1 the agent works in the terminal, 2 the survey is on the farmer's phone; once the farmer
        # finishes, the same terminal reviews the answers, judges the survey and plans the next one.
        flow = f"flow|{ins['insight_id']}"
        stage = st.session_state.get(flow, 0)
        steps_slot = st.empty()
        mem, pretend, notes, lang, ch, h, sv = None, "none", [], None, None, None, None
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
            tools.button("Restart survey", key="studio_restart", icon=":material/restart_alt:", width="content",
                         help="Start over: hand the conversation to the agent again", on_click=_restart_flow, args=(flow,))
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
            bedrock_note = None
            if pretend != "none" or attention is not getattr(d, "attention", None):
                surveys_now = write_surveys(ins, d.send_window, memory=mem, attention=attention)
                farmer_copy = clean(surveys_now.get(ins["conversation_language"]) or surveys_now["hi-IN"])
                out = {**out, "surveys": surveys_now, "handoff": build_handoff(ins, farmer_copy, attention)}
            elif own:
                bedrock_note = (sub or {}).get("bedrock_note")   # own_insight_run already wrote it with Bedrock
            else:
                out, bedrock_note = bedrock_surveys(ins, out, attention)   # the questions Bedrock wrote, not the template
            h = out["handoff"]
            first_ch = h["channel_order"][0]["channel"]  # P2's recommended send time is for this channel
            ch = bar[1].selectbox("Channel", CHANNELS, index=CHANNELS.index(first_ch), format_func=CH_NAME.get,
                                  help="Defaults to the first channel the scheduler tries for this farmer.")
            if ch == "voice":
                sound_button(tools)
            notes = [(r, us_text(w)) for r, w in history_notes(ins, mem, attention)]
            sv = clean(out["surveys"][lang])
        else:
            bar[1].selectbox("Channel", ["—"], disabled=True, help="No survey, so there is nothing to preview.")

        agent_box, phone_box = col_a.container(key="flow_agent"), col_f.container(key="flow_phone")
        st.session_state[f"{flow}|survey"] = d.survey
        chat = st.session_state.get(f"{flow}|chat", [])
        rec = None
        with phone_box:  # the farmer's side first: the agent's review needs the record the phone returns
            if d.survey and stage >= 2:
                # The Restart icon above is the only reset control; it sends the flow back to the start.
                pkey = f"preview|{ins['insight_id']}|{ch}|{lang}|{pretend}|{pretend_att}|{mem is not None}"
                rec = render_channel_preview(sv, ch, key=pkey, send_at=d.send_time["send_at"] if ch == first_ch else None,
                                             restart=st.session_state.pop(f"{flow}|fresh", False), show_restart=False)
                if ch == "voice":
                    voice_readout(sv, pkey, rec)
                # Provenance lines go under the phone so its top lines up with the agent's view in the other column.
                if bedrock_note:
                    st.caption(f"Questions {bedrock_note}")
                if lang == "hi-IN":  # label Hindi until every line in P4's sheet has a reviewer's Y/N
                    sheet = pd.read_csv(HINDI_SHEET, dtype=str, keep_default_na=False)
                    done = int((sheet["reviewer_ok(Y/N)"].str.strip() != "").sum())
                    if done < len(sheet):
                        st.caption(f"Hindi pending review: {done} of {len(sheet)} lines checked by a native speaker")
                html('<i class="mel-dim"></i>' if rec else '<i class="mel-lit"></i>')
            elif not d.survey and stage >= 1:
                who = "A person calls this farmer instead." if d.rule == "R2" else "Nothing is sent to this farmer."
                html(f'<div class="mel-empty"><b>No survey</b>{escape(who)}<br>{d.rule} · {escape(RULE_LABEL[d.rule])}</div>')
                with st.expander("Developer details: no-survey record (JSON)"):
                    st.json(out["no_survey"])
            else:
                html('<i class="mel-dim"></i><div class="mel-phone-wait"><b>The farmer\'s phone</b>'
                     f'<span>{"Waiting for the agent to write the survey" if stage == 0 else "Survey ready. Waiting for Send to the farmer"}</span></div>')
        for c in chat:   # answered once, with the facts of that moment; placed in the log where it was typed
            c.setdefault("a", answer(c, ins, out, d, notes, sv, rec, h, lang))
            c.setdefault("at", "review" if rec else "agent" if c["stage"] else "top")
        with agent_box:
            html('<i class="mel-dim"></i>' if stage >= 2 and d.survey and rec is None else '<i class="mel-lit"></i>')
            term = st.container(key="term_box", gap=None)   # the terminal and its input line, one block
            with term:
                if stage == 0:
                    intake_card(ins, flow)
                else:
                    st.session_state[f"{flow}|shown"] = agent_view(
                        ins, out, d, notes, attention, review_steps(ins, out, h, sv, rec, lang, ch) if rec else None,
                        chat, st.session_state.get(f"{flow}|shown", 0))
                st.chat_input("Ask the agent: why, quality, next… or type send",
                              key=f"ask|{flow}", on_submit=_ask, args=(flow,))
            if stage == 0:
                st.button("Hand it to the agent", key="flow_hand", type="tertiary", icon=":material/south:",
                          on_click=_set_stage, args=(flow, 1), help="Does the same as dragging the card onto the terminal")
            elif stage == 1 and d.survey:
                st.button("Send to the farmer", key="flow_send", type="primary", icon=":material/send:",
                          width="stretch", on_click=_set_stage, args=(flow, 2))
        steps_slot.markdown(flow_steps(stage, d.survey, rec is not None), unsafe_allow_html=True)
        focus = ("phone" if stage >= 2 and d.survey and rec is None else "review" if rec else "agent") if stage else ""
        if st.session_state.get(f"{flow}|focus", "") != focus:
            st.session_state[f"{flow}|focus"] = focus
            target = {"agent": (".st-key-flow_agent", "start"), "phone": (".st-key-flow_phone", "center"),
                      "review": (".st-key-flow_agent", "start")}.get(focus)
            if target:
                st.html(f"""<script>setTimeout(() => document.querySelector('{target[0]}')?.scrollIntoView({{block: '{target[1]}',
  behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}}), 400);</script>""",
                        unsafe_allow_javascript=True)

        if d.survey and stage >= 1:
            surveys = out["surveys"]
            if surveys[lang].get("_history"):
                generic = template_items(ins, lang)      # never a model call: the comparison is with the plain template
                with st.expander(f"Generic vs adapted questions ({LANG_NAME.get(lang, lang)})"):
                    n_rows = max(len(generic), len(sv["items"]))
                    table(pd.DataFrame([{
                        "#": k + 1,
                        "Generic (no history)": generic[k]["prompt"] if k < len(generic) else "(none)",
                        "Adapted to this farmer": sv["items"][k]["prompt"] if k < len(sv["items"]) else "(none)"}
                        for k in range(n_rows)]), hide_index=True, width="stretch")
            if surveys[lang].get("_source") == "bedrock":
                tmpl = template_items(ins, lang)
                with st.expander(f"Template vs Bedrock questions ({LANG_NAME.get(lang, lang)})"):
                    n_rows = max(len(tmpl), len(sv["items"]))
                    table(pd.DataFrame([{
                        "#": k + 1,
                        "Checked template": tmpl[k]["prompt"] if k < len(tmpl) else "(none)",
                        "Written by Bedrock": sv["items"][k]["prompt"] if k < len(sv["items"]) else "(none)"}
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
                    st.caption("Answer record: not yet (the farmer has not finished)")
                else:
                    bad = errors("response", rec)
                    st.caption("Answer record " + ("passes the response schema ✓" if not bad else f"FAILS the response schema: {bad[:2]}"))
                    st.json(rec, expanded=False)

# ---------------------------------------------------------------- footer (farmer.chat's forest band)
html(f'<div class="mel-foot">{LOCKUP}<div>MEL Survey Agent</div></div>')
