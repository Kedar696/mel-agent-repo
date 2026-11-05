"""Fasal Pulse - MEL Survey Agent: the team demo. Owner: P5.  Run: streamlit run app/streamlit_app.py
P4's standalone survey demo (demo/p4_standalone) is folded in: Survey Studio shows what the agent remembers
about the farmer and how history rules H1-H4 adapt the survey (on in the app, off for scoring).
Layout borrowed from the v0 sketch (v0-sketch/): Overview, Survey Studio, Simulate, Evaluation.
Every number on screen comes from the real pipeline; nothing is hard-coded."""
import copy
import os
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
from mel.channels.render import choices
from mel.config import CHANNELS, PACK_DATA
from mel.data import load_insights, load_farmers, errors
from mel.evaluation import evaluate, load_history, rules_changed
from mel.pipeline import run_pipeline, clean
from mel.schedule import build_handoff
from mel.schedule.handoff import CapLedger
from mel.simulator import simulate, simulate_sheet, cases_for
from mel.writer import (check_survey, write_surveys, FarmerMemory, build_context, summary_lines,
                        history_notes)

APP_NAME = "Fasal Pulse - MEL Survey Agent"
st.set_page_config(page_title=APP_NAME, layout="wide")

RULE_LABEL = {"R1": "Junk / unclear", "R2": "Critical → human call", "R3": "Nothing to verify",
              "R4": "Waiting for details", "R5": "No check needed", "R6": "After season",
              "R7": "Already harvested", "R8": "Survey planned"}
RULE_TONE = {"R2": "red", "R4": "amber", "R6": "amber", "R8": "green"}
CH_NAME = {"app": "App", "web": "Web", "whatsapp": "WhatsApp", "telegram": "Telegram", "voice": "Voice"}

st.markdown("""<style>
:root{--g:#266b4a;--gs:#e7f3ea;--a:#a66b13;--as:#fff3dc;--r:#b94c42;--rs:#fce9e6;--ss:#eef1ef;--ln:#e5e9e2;--mu:#6e7a72}
.mel-card{background:#fff;border:1px solid var(--ln);border-radius:12px;padding:16px;margin-bottom:10px;color:#18231d}
.mel-k{font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:800;color:#88938b;margin-bottom:6px}
.mel-badge{display:inline-block;border-radius:20px;font-size:11px;font-weight:700;padding:3px 9px;margin-right:4px;background:var(--gs);color:var(--g)}
.mel-badge.amber{background:var(--as);color:var(--a)}.mel-badge.red{background:var(--rs);color:var(--r)}.mel-badge.slate{background:var(--ss);color:#5d6a62}
.mel-rule{display:grid;grid-template-columns:34px 170px 1fr 30px;gap:10px;align-items:center;font-size:13px;margin:7px 0}
.mel-id{font-family:monospace;font-size:11px;background:#f1f3f1;border-radius:5px;padding:2px 5px;color:#5d6a62}
.mel-track{height:8px;border-radius:8px;background:#eef1ee;overflow:hidden}.mel-fill{height:100%;border-radius:8px;background:#9ca7a0}
.mel-fill.green{background:var(--g)}.mel-fill.amber{background:#d9a03b}.mel-fill.red{background:#c86154}
.mel-insight{background:#1f5f43;color:#f3faf3;border-radius:12px;padding:18px}
.mel-insight h3{color:#fff;margin:6px 0 14px;font-size:19px}.mel-insight .f{border-top:1px solid #ffffff2c;padding:10px 0;font-size:13px;line-height:1.5}
.mel-insight .f span{display:block;color:#a5c9ad;text-transform:uppercase;font-size:10px;letter-spacing:.8px;font-weight:700;margin-bottom:3px}
.mel-meta{display:grid;grid-template-columns:1fr 1fr;gap:10px;border-top:1px solid #ffffff2c;padding-top:10px;font-size:12px}
.mel-meta span{display:block;color:#a5c9ad;font-size:10px;text-transform:uppercase;letter-spacing:.8px}
.mel-why{border-top:1px solid #ffffff2c;margin-top:12px;padding-top:10px;color:#ffd887;font-size:12px}.mel-why p{color:#d7eadb;margin:3px 0 0}
.mel-q{display:grid;grid-template-columns:1fr 1fr;gap:14px}.mel-q>div+div{border-left:1px solid var(--ln);padding-left:14px}
.mel-q p{font-size:14px;margin:4px 0 8px}.mel-pill{display:inline-block;border:1px solid #dce4dd;background:#fbfdfb;color:#4f5c53;border-radius:20px;font-size:12px;padding:3px 9px;margin:0 4px 4px 0}
.mel-pill.fu{border-color:#e5bd6d;background:#fff9ea}.mel-chk{font-size:12px;color:#3f7d52;margin-right:12px}.mel-chk.bad{color:var(--r)}
.mel-phone{border:7px solid #28382d;border-radius:24px;background:#f2f6f2;overflow:hidden;max-height:520px;overflow-y:auto}
.mel-top{background:#e3eee5;padding:8px 12px;color:#4a6552;font-size:11px;font-weight:700;position:sticky;top:0}
.mel-body{padding:10px}.mel-bub{background:#fff;border-radius:11px 11px 11px 3px;padding:9px 10px;margin-bottom:8px;font-size:13px;color:#2d3d32;box-shadow:0 1px 4px #243a2920}
.mel-bub small{color:#98a29a;font-size:10px}.mel-btn{display:block;border:1px solid #c5ddca;background:#f3faf4;border-radius:6px;color:var(--g);padding:5px;margin-top:5px;font-size:12px;text-align:center}
.mel-wa .mel-top{background:#075e54;color:#fff}.mel-wa{background:#ece5dd}.mel-tg .mel-top{background:#2aabee;color:#fff}
.mel-sheet{background:#fff;border-radius:16px 16px 0 0;padding:12px;box-shadow:0 -2px 8px #0001}
.mel-step{border-top:1px solid var(--ln);padding:8px 0}.mel-step:first-of-type{border-top:0}
.mel-strip{display:grid;grid-template-columns:110px 1.6fr 1.2fr 1.3fr 1fr;gap:22px;align-items:start}
.mel-tl{position:relative;height:8px;background:#e8ece8;border-radius:6px;margin:10px 0 4px}
.mel-tl i{position:absolute;top:0;height:8px;border-radius:6px}.mel-tl i.w{background:#6ca378}.mel-tl i.x{background:#e3ad52}
.mel-tlab{display:flex;justify-content:space-between;color:#8a958d;font-size:11px}
.mel-ch b{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:5px;background:var(--gs);color:var(--g);font-size:11px;margin-right:3px}
.mel-ch small{color:#8a958d;margin:0 6px}
</style>""", unsafe_allow_html=True)


def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def badge(text, tone="green"):
    return f'<span class="mel-badge {tone}">{escape(str(text))}</span>'


def short(ts: str) -> str:
    # Build the day number without a platform-specific strftime flag (%-d is glibc-only, %#d is Windows-only).
    dt = datetime.fromisoformat(ts)
    return f"{dt.day} {dt:%b}, {dt:%H:%M}"


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
    # hand-off it merges into, and Survey Studio must keep showing the original survey.
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
st.title(APP_NAME)
st.caption(f"Data: {'full participant pack' if DATA_DIR else os.environ.get('MEL_DATA_DIR') or 'mock sample (data/mock)'}"
           f" · {len(rows):,} conversations · history rules on (scores in Evaluation use history off)")
tab_over, tab_studio, tab_sim, tab_follow, tab_eval = st.tabs(["Overview", "Survey Studio", "Simulate answers", "Follow-up queue", "Evaluation"])

# ---------------------------------------------------------------- Overview
with tab_over:
    n = len(rows)
    rules = Counter(o["decision"].rule for _, o in rows)
    surveyed = [o for _, o in rows if o["decision"].survey]
    limit = Counter(d for d, _ in admits.values())
    held = len(admits) - limit["sent"]
    high = sum(o["handoff"]["priority"] == "high" for o in surveyed)
    llm = sum(s.get("_source") == "llm" for o in surveyed for s in o["surveys"].values())
    c = st.columns(6)
    c[0].metric("Insights processed", n)
    c[1].metric("Surveys planned", len(surveyed), f"{len(surveyed) / n:.0%} of insights", delta_color="off")
    c[2].metric("No survey", n - len(surveyed), f"{(n - len(surveyed)) / n:.0%} of insights", delta_color="off")
    c[3].metric("Schema-valid files", f"{n_valid / max(n_files, 1):.0%}", f"{n_valid:,} / {n_files:,}", delta_color="off")
    c[4].metric("High priority", high, "sent first", delta_color="off")
    c[5].metric("Weekly limit (1 per 7 days)", held, "moved, merged or skipped", delta_color="off")

    left, right = st.columns([1.1, 0.9])
    with left:
        top = max(rules.values() or [1])
        bars = "".join(
            f'<div class="mel-rule"><span class="mel-id">{r}</span><span>{RULE_LABEL[r]}</span>'
            f'<div class="mel-track"><div class="mel-fill {RULE_TONE.get(r, "")}" style="width:{rules.get(r, 0) / top * 100:.0f}%"></div></div>'
            f'<b>{rules.get(r, 0)}</b></div>' for r in RULE_LABEL)
        html(f'<div class="mel-card"><b>Decisions by rule</b><div style="color:#8b958e;font-size:12px;margin-bottom:8px">'
             f'Why an insight was or wasn\'t surveyed</div>{bars}</div>')
    with right:
        st.markdown("**First channel planned**")
        first = Counter(CH_NAME[o["handoff"]["channel_order"][0]["channel"]] for o in surveyed)
        st.bar_chart({"surveys": first}, horizontal=True, color="#266b4a", height=170)
        st.markdown("**Survey source**")
        st.caption(f"Template: {len(surveyed) * 2 - llm} · Claude: {llm}"
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
    st.caption(f"Weekly limit (P3): {limit['sent']:,} sent as planned · {limit['moved']:,} moved to a later date · "
               f"{limit['merged']:,} merged into the farmer's other survey · {limit['skipped']:,} skipped. "
               f"High-priority surveys are exempt.")

    # Highlighted farmers: SURGE only (quiet, then a jump or an urgent question). steady_high is deliberately
    # not highlighted — the representative asked us to attend to positive CHANGE, not to constant high activity.
    st.subheader("Highlighted farmers")
    st.caption("Farmers whose activity is rising — quiet, then a jump or a sudden urgent question. The "
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
        st.dataframe(pd.DataFrame([{
            "Farmer": i.get("farmer_id"),
            "Crop / animal": (i.get("asset") or {}).get("name"),
            "Why": REASON_LABEL.get(o["decision"].attention["reason"], o["decision"].attention["reason"]),
            "Weight": o["decision"].attention["weight"],
            "What we noticed": o["decision"].attention["explanation"],
            "When": short(i["created_at"]) if i.get("created_at") else "—",
        } for i, o in highlighted[:50]]), width="stretch", hide_index=True, height=260)
        st.caption(f"{len(highlighted):,} farmers highlighted (from {len(surges):,} surge insights; "
                   f"most recent surge per farmer, showing up to 50).")

# ---------------------------------------------------------------- Survey Studio
labels = {f"{i.get('insight_id')} · {(i.get('asset') or {}).get('name')} · {i.get('resolution_type')} · "
          f"{'survey' if o['decision'].survey else 'no survey ' + o['decision'].rule}": (i, o) for i, o in rows}


def option_pills(it):
    if it["type"] == "survey-scale":
        thr = it.get("follow_up_at_or_below")
        return "".join(f'<span class="mel-pill {"fu" if thr is not None and v <= thr else ""}">{v}'
                       f'{" ⚑" if thr is not None and v <= thr else ""}</span>'
                       for v in range(it["scale_min"], it["scale_max"] + 1))
    return "".join(f'<span class="mel-pill {"fu" if o.get("follow_up") else ""}">{escape(o["label"])}'
                   f'{" ⚑" if o.get("follow_up") else ""}</span>' for o in it.get("options", []))


def guard_ticks(surveys):
    probs = [p for s in surveys.values() for p in check_survey(clean(s))]
    checks = [("Schema valid", "schema"), ("No new advice", "advice"), ("No personal info", "personal"),
              ("Labels ≤ 20 chars", "label")]
    return "".join(f'<span class="mel-chk {"bad" if any(k in p for p in probs) else ""}">'
                   f'{"✕" if any(k in p for p in probs) else "✓"} {t}</span>' for t, k in checks)


def phone(survey, ch):
    items, lang = survey["items"], survey["language"]
    top = "Incoming call" if ch == "voice" else f"FarmerChat · {CH_NAME[ch]}"
    cls = {"whatsapp": "mel-wa", "telegram": "mel-tg"}.get(ch, "")
    if ch == "voice":
        p = render(survey, "voice")
        body = (f'<div class="mel-bub"><small>Call opens</small><br>{escape(p["opening"])}</div>'
                + "".join(f'<div class="mel-bub"><small>{x["item_id"]} · keypad '
                          f'{" ".join(f"{k}={v}" for k, v in x["keypad"].items())}</small><br>{escape(x["say"])}</div>'
                          for x in p["items"])
                + f'<div class="mel-bub"><small>Closing</small><br>{escape(p["closing"])}</div>')
    elif ch in ("app", "web"):
        sheet = render(survey, ch)["sheet"]
        steps = "".join(
            f'<div class="mel-step"><small style="color:#98a29a">{escape(s["step_label"])}</small><br>'
            f'<b style="font-size:13px">{escape(s["question"])}</b>'
            + "".join(f'<span class="mel-btn">{escape(str(o["label"]))}</span>' for o in s.get("options", []))
            + "</div>" for s in sheet["steps"])
        body = (f'<div style="height:60px"></div><div class="mel-sheet"><b>{escape(sheet["title"])}</b>{steps}'
                f'<div style="text-align:center;color:#9aa59c;font-size:12px;margin-top:6px">{escape(sheet["skip_label"])}</div></div>')
    else:
        p = render(survey, ch)
        invite = p["template_text_for_approval"]["body"] if ch == "whatsapp" else p["messages"][0]["text"]
        body = f'<div class="mel-bub"><small>FarmerChat</small><br>{escape(invite)}</div>'
        for it in items:
            ch_l = choices(it)
            if ch == "whatsapp" and len(ch_l) > 3:  # WhatsApp allows 3 buttons; longer lists open a picker
                btns = f'<span class="mel-btn">☰ {"चुनें" if lang == "hi-IN" else "Choose"} ({len(ch_l)})</span>'
            else:
                btns = "".join(f'<span class="mel-btn">{escape(l)}</span>' for l, _ in ch_l)
            body += f'<div class="mel-bub">{escape(it["prompt"])}{btns}</div>'
    return f'<div class="mel-phone {cls}"><div class="mel-top">{top}</div><div class="mel-body">{body}</div></div>'


def handoff_strip(h, send_time):
    nb, na = (datetime.fromisoformat(h["send_window"][k]) for k in ("not_before", "not_after"))
    ex = datetime.fromisoformat(h["expires_at"])
    span = (ex - nb).total_seconds() or 1
    w = (na - nb).total_seconds() / span * 100
    tone = {"high": "red", "normal": "slate", "low": "slate"}[h["priority"]]
    chans = "".join(f'<b>{i}</b>{CH_NAME[c["channel"]]}'
                    + (f'<small>wait {c["wait_hours"]}h →</small>' if c.get("wait_hours") else "")
                    for i, c in enumerate(h["channel_order"], 1))
    cap = h["frequency_cap"]
    decision, reason = admits.get(h["handoff_id"], ("sent", ""))
    cap_state = ("Exempt (high priority)" if cap["exempt"] else {
        "sent": "✓ Within the limit", "moved": f"↷ Moved: {reason}", "merged": f"⊕ Merged: {reason}",
        "skipped": "⚠ Skipped: this farmer already has a survey that week", "opted_out": "Farmer opted out"}[decision])
    status = {"sent": badge("Ready to send"), "moved": badge("Moved by weekly limit", "amber"),
              "merged": badge("Merged by weekly limit", "amber"), "skipped": badge("Skipped by weekly limit", "red"),
              "opted_out": badge("Opted out", "red")}[decision]
    html(f'''<div class="mel-card"><div style="display:flex;justify-content:space-between"><b>Scheduler hand-off · {h["handoff_id"]}</b>
{status}</div><br>
<div class="mel-strip">
<div><div class="mel-k">Priority</div>{badge(h["priority"].title(), tone)}</div>
<div><div class="mel-k">Send window · IST</div><b style="font-size:13px">{short(h["send_window"]["not_before"])} → {short(h["send_window"]["not_after"])}</b>
<div class="mel-tl"><i class="w" style="left:0;width:{w:.0f}%"></i><i class="x" style="left:{w:.0f}%;width:{100 - w:.0f}%;opacity:.45"></i></div>
<div class="mel-tlab"><span>Not before</span><span>Not after</span><span>Expires {short(h["expires_at"])}</span></div></div>
<div><div class="mel-k">Recommended send · IST</div><b style="font-size:13px">{short(send_time["send_at"])}</b>
<div style="font-size:12px;margin-top:6px">{escape(send_time["reason"])}</div></div>
<div class="mel-ch"><div class="mel-k">Channel order</div><span style="font-size:13px">{chans}</span></div>
<div><div class="mel-k">Frequency cap</div><b style="font-size:13px">{cap["max_surveys"]} per farmer / {cap["window_days"]} days</b>
<div style="font-size:12px;margin-top:6px">{cap_state}</div></div></div></div>''')


# ---------------------------------------------------------------- Answer as the farmer (from P4's demo)
TAP_UI = {
    "hi": dict(title="आपको मिली सलाह पर एक छोटा सवाल", close="बंद करें", optout="दोबारा न पूछें",
               thanks="धन्यवाद। आपके जवाब से हम और अच्छी सलाह दे पाएँगे।",
               thanks_fu="धन्यवाद। हमने यह नोट कर लिया है। FarmerChat आपसे इस बारे में फिर बात करेगा।",
               step="{n} में से {i}", start="शुरू करें", later="अभी नहीं",
               invite="आपको मिली सलाह के बारे में FarmerChat से एक छोटा सवाल। बस एक मिनट लगेगा।"),
    "en": dict(title="A quick question about the advice you got", close="Close", optout="Do not ask me again",
               thanks="Thank you. Your answers help us give better advice.",
               thanks_fu="Thank you. We have noted this. FarmerChat will talk to you about it again.",
               step="{i} of {n}", start="Start", later="Not now",
               invite="A short question from FarmerChat about the advice you got. It takes one minute."),
}


def tap_record(sv, ch, S, send_at):
    """Turn the taps into an answer record with P3's simulator (the real taps, never invented answers)."""
    how, taps = S["done"], S["taps"]
    if how == "finished":
        return (simulate_sheet(sv, ch, list(taps), answers=taps) if ch in ("app", "web")
                else simulate(sv, ch, "completed", answers=taps, send_at=send_at))
    if how == "closed":
        return simulate_sheet(sv, ch, list(taps), closed=True, answers=taps)
    case = {"dismissed": "sheet_dismissed", "opted_out": "farmer_opted_out",
            "free_text": "free_text_instead_of_choice", "dropped": "voice_call_dropped"}[how]
    return simulate(sv, ch, case, send_at=send_at)


def answer_as_farmer(sv, ch, key, send_at):
    k = "hi" if sv["language"].startswith("hi") else "en"
    U, its = TAP_UI[k], sv["items"]
    n = len(its)
    S = st.session_state.setdefault(key, {"step": 0, "taps": {}, "done": None})

    def tap(qid, val):
        S["taps"][qid] = val
        S["step"] += 1
        if S["step"] >= n:
            S["done"] = "finished"

    def end(how):
        S["done"] = how

    def restart():
        S.update(step=0, taps={}, done=None)

    left, right = st.columns([1, 1])
    with left, st.container(border=True):
        st.caption(f"{CH_NAME[ch]} · tap like the farmer would")
        if ch in ("app", "web"):
            st.markdown(f"**{U['title']}**")
            if S["done"] is None:
                q = its[S["step"]]
                st.caption(U["step"].format(i=S["step"] + 1, n=n))
                st.progress((S["step"] + 1) / n)
                st.markdown(f"#### {q['prompt']}")
                for o in q.get("options", []):
                    st.button(o["label"], key=f"{key}|{q['item_id']}|{o['value']}", on_click=tap,
                              args=(q["item_id"], o["value"]), width="stretch")
                b1, b2 = st.columns(2)
                b1.button(U["close"], key=f"{key}|close", on_click=end, args=("closed" if S["taps"] else "dismissed",))
                b2.button(U["optout"], key=f"{key}|opt", on_click=end, args=("opted_out",))
        elif ch in ("whatsapp", "telegram"):
            if ch == "whatsapp":
                st.chat_message("assistant").write(f"{U['invite']}\n\n[{U['start']}]  [{U['later']}]")
            for q in its[:S["step"]]:
                st.chat_message("assistant").write(q["prompt"])
                v = S["taps"].get(q["item_id"])
                st.chat_message("user").write(next((o["label"] for o in q.get("options", []) if o["value"] == v), "—"))
            if S["done"] is None:
                q = its[S["step"]]
                st.chat_message("assistant").write(q["prompt"])
                for o in q.get("options", []):
                    st.button(o["label"], key=f"{key}|{q['item_id']}|{o['value']}", on_click=tap,
                              args=(q["item_id"], o["value"]), width="stretch")
                b1, b2 = st.columns(2)
                b1.button("Type a message instead", key=f"{key}|ft", on_click=end, args=("free_text",))
                b2.button("STOP" if ch == "whatsapp" else "/stop", key=f"{key}|stop", on_click=end, args=("opted_out",))
        else:  # voice
            vo = render(sv, "voice")
            if S["done"] is None:
                st.markdown(f"🔊 *{vo['items'][S['step']]['say']}*")
                q = its[S["step"]]
                cols = st.columns(len(q.get("options", [])) + 1)
                for num, o in enumerate(q.get("options", []), 1):
                    cols[num - 1].button(f"Press {num}", key=f"{key}|k{num}|{q['item_id']}", on_click=tap,
                                         args=(q["item_id"], o["value"]))
                cols[-1].button("Press 9", key=f"{key}|k9", on_click=end, args=("opted_out",))
                st.button("Farmer hangs up", key=f"{key}|hang", on_click=end, args=("dropped",))
        if S["done"] is not None:
            rec = tap_record(sv, ch, S, send_at)
            st.markdown(f"**{U['thanks_fu'] if rec['needs_follow_up'] else U['thanks']}**")
            st.button("Start over", key=f"{key}|re", on_click=restart)
    with right:
        if S["done"] is None:
            st.info("Tap an answer on the left. When the farmer finishes, closes, opts out or hangs up, the "
                    "answer record appears here, built by P3's simulator from the actual taps.")
        else:
            m = st.columns(3)
            m[0].metric("Status", rec["status"])
            m[1].metric("Counts toward weekly limit", "Yes" if rec["counts_toward_cap"] else "No")
            m[2].metric("Next step", rec["retry_decision"])
            if rec["needs_follow_up"]:
                st.error("Goes to the Follow-up queue: " + ", ".join(FU_LABEL.get(r, r) for r in rec["follow_up_reasons"]))
            if rec["failure_code"]:
                st.warning(f"Failure: {rec['failure_code']}")
            bad = errors("response", rec)
            st.caption("Answer record " + ("passes the response schema ✓" if not bad else f"FAILS the schema: {bad[:2]}"))
            with st.expander("Full answer record (response.schema.json)"):
                st.json(rec)


FU_LABEL = {"advice_did_not_work": "advice didn't work", "crop_or_animal_damaged": "crop / animal damaged",
            "could_not_get_input": "couldn't get inputs", "could_not_reach_expert": "couldn't reach expert"}

DEMO_PICKS = {"I-001253": "Goat → vet (high priority)", "I-006130": "Stored potatoes (the R7 fix)",
              "I-000291": "Critical cow case → a person calls"}
BROWSE = "Browse all conversations"

with tab_studio:
    by_id = {i.get("insight_id"): (i, o) for i, o in rows}
    picks = {k: v for k, v in DEMO_PICKS.items() if k in by_id}
    pick = st.selectbox("Demo picks", [*picks, BROWSE], format_func=lambda k: picks.get(k, k))
    if pick != BROWSE:
        ins, out = by_id[pick]
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
    d = out["decision"]
    a = ins.get("asset") or {}
    mem, pretend = None, "none"
    # The attention the batch computed for this insight (the app runs with attention on). The demo picker below
    # can override it with a made-up tier, because the pack's activity is flat and has no designed surges.
    attention = getattr(d, "attention", None)
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
    if d.survey:
        hc = st.columns([1, 2])
        use_history = hc[0].toggle("Use the farmer's past conversations", value=True,
                                   help="Off = the generic template for this advice type (what scoring uses).")
        with hc[1].expander("Pretend this farmer's survey history (demo)"):
            pretend = st.selectbox("Earlier survey answers", ["none", "said the input was not available nearby",
                                                              "said it was too costly", "ignored the last 3 surveys"])
            pretend_att = st.selectbox("Pretend activity pattern (attention demo)", list(PRETEND_ATT),
                                       help="The pack's activity is flat with no designed surges, so this made-up "
                                            "pattern shows how a surge or steady-high farmer is treated differently.")
            if PRETEND_ATT[pretend_att] is not None:
                attention = PRETEND_ATT[pretend_att]
        if use_history:
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
        # Re-run when history is toggled off, a pretend answer history is chosen, or the attention tier is
        # overridden (the batch built surveys with history on and the data-computed attention).
        if not use_history or pretend != "none" or attention is not getattr(d, "attention", None):
            surveys_now = write_surveys(ins, d.send_window, memory=mem, attention=attention)
            farmer_copy = clean(surveys_now.get(ins["conversation_language"]) or surveys_now["hi-IN"])
            out = {**out, "surveys": surveys_now, "handoff": build_handoff(ins, farmer_copy, attention)}
    sev_tone = {"critical": "red", "high": "red", "medium": "amber"}.get(ins.get("severity"), "slate")
    why = (out["surveys"][ins["conversation_language"]]["rationale"] if d.survey
           else out["no_survey"]["reason"])
    col_i, col_q, col_p = st.columns([1, 2, 1.3])
    with col_i:
        html(f'''<div class="mel-insight"><div style="font-size:10px;letter-spacing:.8px;color:#b7d5bd;text-transform:uppercase">
Selected insight {badge((ins.get("severity") or "n/a").title() + " severity", sev_tone)}</div>
<h3>{escape(str(a.get("name") or "—").title())} · {escape(str(ins.get("concern") or "").replace("_", " "))}</h3>
<div class="f"><span>Farmer asked</span>“{escape(ins.get("query_summary") or "—")}”</div>
<div class="f"><span>Advice given</span>“{escape(ins.get("advice_summary") or "—")}”</div>
<div class="mel-meta"><div><span>Farmer</span>{ins.get("farmer_id")}</div><div><span>Insight</span>{ins.get("insight_id")}</div>
<div><span>Growth stage</span>{escape(str(a.get("growth_stage") or "—"))}</div><div><span>Resolution</span>{escape(str(ins.get("resolution_type") or "—"))}</div></div>
<div class="mel-why">{"Why this survey?" if d.survey else f"Why no survey? ({d.rule})"}<p>{escape(why)}</p></div></div>''')
        if attention and d.survey:
            TIER_TONE = {"surge": "green", "steady_high": "slate", "neutral": "slate"}
            html(f'<div class="mel-card"><div class="mel-k">Activity attention</div>'
                 f'{badge(attention["tier"].replace("_", " ").title(), TIER_TONE.get(attention["tier"], "slate"))}'
                 f'{badge(attention["reason"].replace("_", " "), "slate")}'
                 f'<div style="margin-top:6px;font-size:13px;color:#4f5c53">{escape(attention["explanation"])}</div>'
                 f'<div style="margin-top:4px;font-size:11px;color:#8a958d">baseline/wk '
                 f'{attention["baseline_per_week"]} · recent {attention["recent_count"]} · weight '
                 f'{attention["weight"]}</div></div>')
        if mem is not None:
            notes = history_notes(ins, mem, attention)
            lines = summary_lines(build_context(ins, mem))
            html('<div class="mel-card"><b>What the agent remembers</b><ul style="margin:6px 0 0 16px;font-size:13px">'
                 + "".join(f"<li>{escape(x)}</li>" for x in lines) + "</ul>"
                 + ("".join(f'<div style="margin-top:6px">{badge(r, "amber")} {escape(w)}</div>' for r, w in notes)
                    if notes else '<div style="margin-top:6px;font-size:12px;color:#6e7a72">Nothing in the history '
                                  'changes this survey, so the generic questions are used.</div>') + "</div>")
    if not d.survey:
        with col_q:
            st.warning(f"No survey · {d.rule} {RULE_LABEL[d.rule]}")
            st.json(out["no_survey"])
    else:
        surveys, h = out["surveys"], out["handoff"]
        hi, en = surveys.get("hi-IN"), surveys.get("en-IN")
        with col_q:
            src = {s.get("_source") for s in surveys.values()}
            tags = [badge(x.title(), "amber") for x in src]
            if en.get("_history"):
                tags.append(badge("Personalised · " + ", ".join(r for r, _ in en["_history"])))
            html(f'<div style="display:flex;justify-content:space-between;align-items:center"><b>Questions · {len(en["items"])}</b>'
                 f'<span>{" ".join(tags)}</span></div>')
            for i, (qh, qe) in enumerate(zip(hi["items"], en["items"]), 1):
                html(f'''<div class="mel-card"><span class="mel-id">0{i}</span> {badge(qe["type"].replace("survey-", ""), "slate")}
<div class="mel-q" style="margin-top:8px"><div><div class="mel-k">हिन्दी</div><p>{escape(qh["prompt"])}</p>{option_pills(qh)}</div>
<div><div class="mel-k">English</div><p>{escape(qe["prompt"])}</p>{option_pills(qe)}</div></div></div>''')
            html(guard_ticks(surveys) + '<span style="font-size:12px;color:#8a958d">⚑ = answer triggers a follow-up</span>')
            if en.get("_history"):
                generic = write_surveys(ins, d.send_window)["en-IN"]["items"]
                with st.expander("Generic vs adapted questions (English)", expanded=True):
                    n_rows = max(len(generic), len(en["items"]))
                    st.dataframe(pd.DataFrame([{
                        "#": k + 1,
                        "Generic (no history)": generic[k]["prompt"] if k < len(generic) else "(none)",
                        "Adapted to this farmer": en["items"][k]["prompt"] if k < len(en["items"]) else "(none)"}
                        for k in range(n_rows)]), hide_index=True, width="stretch")
        with col_p:
            ch = st.segmented_control("Channel preview", CHANNELS, default=h["channel_order"][0]["channel"],
                                      format_func=CH_NAME.get) or "app"
            lang = st.segmented_control("Language", list(surveys), default=ins["conversation_language"]) or "hi-IN"
            html(phone(clean(surveys[lang]), ch))
        handoff_strip(h, d.send_time)
        st.subheader("Answer as the farmer")
        first = ch == h["channel_order"][0]["channel"]  # P2's recommended time is for the first channel
        answer_as_farmer(clean(surveys[lang]), ch,
                         f"tap|{ins['insight_id']}|{ch}|{lang}|{pretend}|{mem is not None}",
                         d.send_time["send_at"] if first else None)
        with st.expander("Raw JSON: survey, channel payload, hand-off"):
            st.json(clean(surveys[lang]), expanded=False)
            st.json(render(clean(surveys[lang]), ch), expanded=False)
            st.json(h, expanded=False)
        st.session_state["handoff"], st.session_state["send_time"] = h, d.send_time

# ---------------------------------------------------------------- Simulate
with tab_sim:
    h = st.session_state.get("handoff")
    if not h:
        st.info("Pick an insight that gets a survey in the Survey Studio tab first.")
    else:
        ch = st.selectbox("Channel", CHANNELS)
        case = st.selectbox("Case", cases_for(ch))
        seed = st.number_input("Seed", 0, 999, 0)
        first = ch == h["channel_order"][0]["channel"]  # the recommended time is for the first channel
        rec = simulate(h["survey"], ch, case, seed=int(seed),
                       send_at=st.session_state["send_time"]["send_at"] if first else None)
        e = errors("response", rec)
        (st.error if e else st.success)(f"status={rec['status']} failure={rec['failure_code']} "
                                        f"follow_up={rec['follow_up_reasons']} schema={'FAIL' if e else 'ok'}")
        st.json(rec)

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
            "answer": _answer_label(t_def, t_val), "rec": rec, "insight": ins,
            "weight": att.get("weight", 1.0), "tier": att.get("tier", "neutral"),
        })
    # Sort by activity-attention weight first (rising-activity farmers rise to the top), then most recent.
    tickets.sort(key=lambda t: (t["weight"], t["recorded_at"]), reverse=True)
    return tickets


with tab_follow:
    tickets = _follow_queue()
    st.subheader("Follow-up queue")
    st.caption("Answers that came back flagged ⚑ — the advice failed, harm happened, or the farmer couldn't "
               "act on it. FarmerChat staff work this queue and get back to the farmer. Each row is one "
               "survey's trouble answer (simulated); in production only the answers a farmer actually gives land here.")
    if not tickets:
        st.info("No survey in this run can produce a follow-up flag.")
    else:
        rc = Counter(t["reason"] for t in tickets)
        m = st.columns(len(FU_REASON) + 1)
        m[0].metric("Flagged surveys", len(tickets))
        for col, (k, lab) in zip(m[1:], FU_REASON.items()):
            col.metric(lab, rc.get(k, 0))

        fr, fc = st.columns(2)
        sel_reasons = fr.multiselect("Reason", list(FU_REASON), default=list(FU_REASON),
                                      format_func=FU_REASON.get)
        chans = sorted({t["channel"] for t in tickets})
        sel_chans = fc.multiselect("Channel", chans, default=chans, format_func=CH_NAME.get)
        view = [t for t in tickets if t["reason"] in sel_reasons and t["channel"] in sel_chans]

        if not view:
            st.warning("No tickets match these filters.")
        else:
            st.dataframe(pd.DataFrame([{
                "Weight": t["weight"],
                "Farmer": t["farmer_id"],
                "Crop / animal": t["asset"],
                "Survey": t["survey_id"],
                "Channel": CH_NAME.get(t["channel"], t["channel"]),
                "Flagged answer": f"{t['prompt']} → {t['answer']}",
                "Why": FU_REASON.get(t["reason"], t["reason"]),
                "Answered": t["recorded_at"],
            } for t in view]), width="stretch", hide_index=True, height=280)
            st.caption("Sorted by activity-attention weight first (rising-activity farmers at the top), then most recent.")

            st.subheader("Open a ticket")
            opts = {t["response_key"]: f"{t['farmer_id']} · {t['asset']} · {FU_REASON[t['reason']]}"
                    for t in view}
            key = st.selectbox("Ticket", list(opts), format_func=lambda k: opts.get(k, k),
                               label_visibility="collapsed")
            t = next((x for x in view if x["response_key"] == key), None)
            if t:
                ins, a = t["insight"], t["insight"].get("asset") or {}
                col_d, col_a = st.columns([1.4, 1])
                with col_d:
                    html(f'''<div class="mel-card"><span class="mel-k">Farmer</span><b>{escape(t["farmer_id"])}</b>
                    <span class="mel-id" style="margin-left:10px">{ins.get("insight_id")}</span><br>
                    <span class="mel-k">Crop / animal</span>{escape(str(a.get("name") or "—").title())} · {escape(str(ins.get("concern") or "").replace("_", " "))}<br>
                    <span class="mel-k">Survey</span><span class="mel-id">{t["survey_id"]}</span>
                    <span class="mel-k" style="margin-left:10px">Sent via</span>{CH_NAME.get(t["channel"], t["channel"])}<br>
                    <span class="mel-k">Advice given</span>“{escape(ins.get("advice_summary") or "—")}”
                    </div>''')
                    html(f'''<div class="mel-card"><span class="mel-k">Flagged answer · {t["item_id"]}</span>
                    <p style="font-size:15px;margin:4px 0">{escape(t["prompt"])}</p>
                    <p>Answer: <b>{escape(str(t["answer"]))}</b> &nbsp; {badge("⚑ " + FU_REASON[t["reason"]], "red")}</p></div>''')
                with col_a:
                    st.markdown("**Suggested follow-up**")
                    st.info(FU_ACTION[t["reason"]])
                    st.caption(f"Recorded {short(t['recorded_at'])} · status {t['rec']['status']}")
                with st.expander("Full answer record (response.schema.json)"):
                    st.json(t["rec"])

# ---------------------------------------------------------------- Evaluation
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


with tab_eval:
    basis = st.radio("Send-time rule", list(BASIS_LABEL), format_func=BASIS_LABEL.get, horizontal=True,
                     help="P2 built both. Brief rules = Digital Green's written brief (07:00, after the farmer's "
                          "action window). Answer-key setting = what the 150-case answer key expects.")
    res = {b: _evaluate(b) for b in BASIS_LABEL}
    r = res[basis]
    src, card = r["full"] or r["mock"], r["card"]

    st.subheader("Answer key")
    st.caption(f"{'Full pack' if r['full'] else 'Mock subset'}: {src['n']} cases with the right answer. "
               f"Mock subset ({r['mock']['n']} rows): decision {r['mock']['decision_acc']:.1%}, "
               f"window {r['mock']['window_acc']:.1%}.")
    g = st.columns(5)
    g[0].metric("Decision", _pct(src["decision_acc"]), "survey or not", delta_color="off")
    g[1].metric("Rule", _pct(src["rule_acc"]), "which of R1–R8", delta_color="off")
    g[2].metric("First channel", _pct(src["channel_acc"]))
    g[3].metric("Window match", _pct(src["window_acc"]), "exact, vs answer key", delta_color="off")
    g[4].metric("Item similarity", f"{src['item_similarity_avg']:.2f}", "keyword overlap", delta_color="off")

    st.subheader("Every survey we write")
    st.caption(f"Checks on all {card['n_survey_files']:,} survey files (Hindi + English) from "
               f"{card['n_insights']:,} insights → {card['n_surveyed']:,} surveys. No answer key needed.")
    q = st.columns(6)
    q[0].metric("Format", _pct(card["format_pass"]), "schema, 1–3 tap items, language", delta_color="off")
    q[1].metric("Safety", _pct(card["safety_pass"]), "no new advice or personal info", delta_color="off")
    q[2].metric("Timeliness", _pct(card["timeliness_pass"]), "after action window, daytime, in season",
                delta_color="off")
    jr = card.get("judge_relevance")
    q[3].metric("Relevance", f"{card['relevance_avg']:.2f}",
                "P4 score, 0–1 · AI judge: " + ("not run" if jr is None else f"{jr:.2f} / 5"), delta_color="off")
    q[4].metric("Speed", f"{card['s_per_survey'] * 1000:.1f} ms", f"per survey · {card['batch_seconds']:.0f} s for all",
                delta_color="off")
    q[5].metric("Failing but scheduled", card["failed_but_scheduled"], "target 0", delta_color="off")
    for title, rows in ((f"Surveys that failed format or safety (first {len(card['examples'])})", card["examples"]),
                        (f"Send windows that failed timeliness (first {len(card['timeliness_examples'])})",
                         card["timeliness_examples"])):
        if rows:
            with st.expander(title):
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

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

    st.subheader("Brief rules vs answer-key setting")
    st.caption("Matching the answer key's send times costs timeliness: most of its windows open before the "
               "farmer could have acted on the advice. We keep the brief as the default until Digital Green confirms.")
    cmp = []
    for b, rr in res.items():
        gg, cc = rr["full"] or rr["mock"], rr["card"]
        cmp.append({"Send-time rule": BASIS_LABEL[b], "Decision": _pct(gg["decision_acc"]),
                    "Window match": _pct(gg["window_acc"]), "Timeliness": _pct(cc["timeliness_pass"]),
                    "Surveys": f"{cc['n_surveyed']:,}", "Misses": len(gg["misses"])})
    st.dataframe(pd.DataFrame(cmp), width="stretch", hide_index=True)

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

            st.dataframe(pd.DataFrame([{
                "Run": f"{c['run']} (vs {c['vs_run']})", "What changed": c["change"],
                "Send-time rule": BASIS_LABEL.get(c["timing_basis"]),
                **{lab: _chg(c[k], _pct) for k, lab in (("decision_acc", "Decision"), ("window_acc", "Window match"),
                                                       ("timeliness_pass", "Timeliness"))},
                "Item sim": _chg(c["item_similarity_avg"], _n), "Relevance (P4)": _chg(c["relevance_avg"], _n),
                "Misses": _chg(c["misses"], _n)} for c in changed]),
                width="stretch", hide_index=True)
        hd = pd.DataFrame(hist)
        avail = [k for k in DIMENSIONS if k in hd and hd[k].notna().any()]
        pick = st.multiselect("Dimensions to chart", avail, default=[k for k in ("decision_acc", "window_acc",
                              "timeliness_pass") if k in avail], format_func=DIMENSIONS.get)
        if len(hd) > 1 and pick:
            st.line_chart(hd.set_index("run")[pick].rename(columns=DIMENSIONS), height=220)
        with st.expander("All recorded runs"):
            st.dataframe(hd, width="stretch", hide_index=True)

    st.subheader("Per-rule confusion matrix")
    st.caption("Rows = expected rule, columns = our prediction. Diagonal = correct.")
    rules = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    df = pd.DataFrame(src["confusion"], index=rules)[rules]
    df.index.name = "expected → predicted"
    st.dataframe(df, width="stretch")

    if src["item_similarities"]:
        st.subheader("Item similarity")
        st.caption(f"Keyword overlap between our questions and the golden set's expected questions (avg {src['item_similarity_avg']:.2f})")
        st.dataframe(pd.DataFrame(src["item_similarities"]), width="stretch", height=150)

    st.subheader("Misses")
    if src["misses"]:
        st.dataframe(pd.DataFrame(src["misses"]), width="stretch", height=200)
    else:
        st.success("No misses — every decision and rule matches.")
