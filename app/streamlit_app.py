"""Fasal Pulse - MEL Survey Agent: the team demo. Owner: P5.  Run: streamlit run app/streamlit_app.py
P4's standalone survey demo (demo/p4_standalone) is folded in: Survey demo shows what the agent remembers
about the farmer and how history rules H1-H5 adapt the survey (on in the app, off for scoring).
This file is the shell: the auto-reload guard, the batch every tab reads (the pack through the pipeline and the
scheduler's gate, once), and the two tabs. Dashboard: app/dashboard.py. Survey demo: app/survey_demo.py (the phone:
app/channel_preview.py). Shared labels and display helpers: app/common.py. Look and feel: app/theme.py.
Every number on screen comes from the real pipeline; nothing is hard-coded."""

import copy
import sys
from pathlib import Path

from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st


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

from mel.config import CHANNELS
from mel.data import load_insights, load_farmers, errors
from mel.evaluation import evaluate
from mel.pipeline import run_pipeline, clean
from mel.schedule import CapLedger, FrequencyScheduler, OptOutList
from mel.schedule.batch import schedule_in_send_order
from mel.writer import FarmerMemory, RELEVANCE_THRESHOLD

sys.modules["mel"]._code_stamp = _MEL_STAMP  # see _reload_mel_if_changed

from app.display_time import use as use_zone

use_zone(None)  # the numbers in Eastern Time; the Survey demo switches one farmer's screen to India time
from app import dashboard, survey_demo
from app.common import CH_NAME, DATA_DIR, RULE_LABEL, html
from app.theme import LOCKUP, apply_theme

sys.modules["app"]._code_stamp = _APP_STAMP  # see _reload_mel_if_changed

APP_NAME = "Fasal Pulse - MEL Survey Agent"
st.set_page_config(page_title=APP_NAME, layout="wide")
apply_theme()


@st.cache_resource(show_spinner="Running the pipeline on every conversation…")
def batch():
    """Run the whole pipeline once, put every hand-off through the same gate as `mel.cli run` (opt-out, quality
    gate, weekly cap with deferred moves, in send order), and count schema-valid files once, so later clicks stay
    fast even on the full dataset."""
    insights = load_insights(DATA_DIR / "insights.jsonl" if DATA_DIR else None)
    res = run_pipeline(
        insights,
        farmers=load_farmers(DATA_DIR / "farmers.csv" if DATA_DIR else None),  # feed send time
        history=True,  # P4's history rules: on in the app, off for scoring (team decision 4 Nov)
        attention=True,
    )  # activity attention: on in the app, off for scoring (same decision)
    rows = list(zip(res.insights, res.outputs))
    # Copies, because a merge edits the host hand-off, and Survey demo must keep showing the original survey.
    hs = [copy.deepcopy(o["handoff"]) for _, o in rows if "handoff" in o]
    ranker = FrequencyScheduler.from_insights(insights)  # the CLI's tie-break at the same window start
    decided, _ = schedule_in_send_order(
        hs,
        cap=CapLedger(),
        opt_out=OptOutList(),
        relevance_threshold=RELEVANCE_THRESHOLD,
        ranks={h["handoff_id"]: ranker.score(h) for h in hs},
    )
    admits, upcoming = {}, {}  # upcoming: farmer -> [(send start, insight id)] of surveys that go out
    for hid, a in decided:
        admits[hid] = (a.decision, a.reason)
        if a.decision in ("sent", "moved"):
            upcoming.setdefault(a.handoff["survey"]["farmer_id"], []).append(
                (a.handoff["send_window"]["not_before"], a.handoff["survey"]["source_insight_ids"][0])
            )
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
    return FarmerMemory(
        load_insights(DATA_DIR / "insights.jsonl" if DATA_DIR else None),
        load_farmers(DATA_DIR / "farmers.csv" if DATA_DIR else None),
    )


rows, admits, upcoming, n_valid, n_files = batch()
data = SimpleNamespace(
    rows=rows,
    admits=admits,
    upcoming=upcoming,
    memory=memory,
    insight_by_id={i.get("insight_id"): i for i, _ in rows},
    out_by_id={i.get("insight_id"): o for i, o in rows},
)
html(
    f'<div class="mel-mast"><div class="mel-brand">{LOCKUP}</div>'
    '<div class="mel-head"><h1 class="mel-title">MEL Survey Agent</h1></div></div>'
)
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
    dashboard.render(
        rows=rows,
        admits=admits,
        upcoming=upcoming,
        evaluate_fn=_evaluate,
        rule_label=RULE_LABEL,
        ch_name=CH_NAME,
        channels=CHANNELS,
    )

# ---------------------------------------------------------------- Survey demo

survey_demo.render(tab_studio, data)

# ---------------------------------------------------------------- footer (farmer.chat's forest band)
html(f'<div class="mel-foot">{LOCKUP}<div>MEL Survey Agent</div></div>')
