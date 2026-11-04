"""MEL Survey Agent demo. Owner: P5.  Run: streamlit run app/streamlit_app.py
Layout borrowed from the v0 sketch (v0-sketch/): Overview, Survey Studio, Simulate, Evaluation.
Every number on screen comes from the real pipeline; nothing is hard-coded."""
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from mel.channels import render
from mel.channels.render import choices
from mel.config import CHANNELS, PACK_DATA
from mel.data import load_insights, load_farmers, errors
from mel.evaluation import evaluate, load_history, rules_changed
from mel.pipeline import run_pipeline, clean
from mel.schedule.handoff import CapLedger
from mel.simulator import simulate, cases_for
from mel.writer import check_survey

st.set_page_config(page_title="MEL Survey Agent", layout="wide")

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
    return datetime.fromisoformat(ts).strftime("%-d %b, %H:%M")


@st.cache_resource
def batch():
    """Run the whole pipeline once; replay the frequency cap in send order."""
    res = run_pipeline(load_insights(), farmers=load_farmers())  # farmers + chat history feed the send time
    rows = list(zip(res.insights, res.outputs))
    led, capped = CapLedger(), set()
    hs = sorted((o["handoff"] for _, o in rows if "handoff" in o), key=lambda h: h["send_window"]["not_before"])
    for h in hs:
        if not led.allow(h):
            capped.add(h["handoff_id"])
    return rows, capped


rows, capped = batch()
st.title("MEL Survey Agent")
tab_over, tab_studio, tab_sim, tab_follow, tab_eval = st.tabs(["Overview", "Survey Studio", "Simulate answers", "Follow-up queue", "Evaluation"])

# ---------------------------------------------------------------- Overview
with tab_over:
    n = len(rows)
    rules = Counter(o["decision"].rule for _, o in rows)
    surveyed = [o for _, o in rows if o["decision"].survey]
    files = [clean(s) for o in surveyed for s in o["surveys"].values()] + [o["handoff"] for o in surveyed]
    kinds = ["survey"] * (len(files) - len(surveyed)) + ["schedule_handoff"] * len(surveyed)
    valid = sum(not errors(k, f) for k, f in zip(kinds, files))
    high = sum(o["handoff"]["priority"] == "high" for o in surveyed)
    llm = sum(s.get("_source") == "llm" for o in surveyed for s in o["surveys"].values())
    c = st.columns(6)
    c[0].metric("Insights processed", n)
    c[1].metric("Surveys planned", len(surveyed), f"{len(surveyed) / n:.0%} of insights", delta_color="off")
    c[2].metric("No survey", n - len(surveyed), f"{(n - len(surveyed)) / n:.0%} of insights", delta_color="off")
    c[3].metric("Schema-valid files", f"{valid / max(len(files), 1):.0%}", f"{valid} / {len(files)}", delta_color="off")
    c[4].metric("High priority", high, "sent first", delta_color="off")
    c[5].metric("Capped (1 per 7 days)", len(capped), "would be held back", delta_color="off")

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
    st.caption(f"{len(capped)} survey(s) would be held back by the cap; skip, move or merge policy is still open (P3).")

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
    cap_state = ("Exempt (high priority)" if cap["exempt"] else
                 "⚠ Over cap: another survey is already planned this week" if h["handoff_id"] in capped else "✓ Within cap")
    html(f'''<div class="mel-card"><div style="display:flex;justify-content:space-between"><b>Scheduler hand-off · {h["handoff_id"]}</b>
{badge("Ready to send") if h["handoff_id"] not in capped else badge("Held by cap", "amber")}</div><br>
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


with tab_studio:
    key = st.selectbox("Insight", list(labels))
    ins, out = labels[key]
    d = out["decision"]
    a = ins.get("asset") or {}
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
    if not d.survey:
        with col_q:
            st.warning(f"No survey · {d.rule} {RULE_LABEL[d.rule]}")
            st.json(out["no_survey"])
    else:
        surveys, h = out["surveys"], out["handoff"]
        hi, en = surveys.get("hi-IN"), surveys.get("en-IN")
        with col_q:
            src = {s.get("_source") for s in surveys.values()}
            html(f'<div style="display:flex;justify-content:space-between;align-items:center"><b>Questions · {len(en["items"])}</b>'
                 f'<span>{" ".join(badge(x.title(), "amber") for x in src)}</span></div>')
            for i, (qh, qe) in enumerate(zip(hi["items"], en["items"]), 1):
                html(f'''<div class="mel-card"><span class="mel-id">0{i}</span> {badge(qe["type"].replace("survey-", ""), "slate")}
<div class="mel-q" style="margin-top:8px"><div><div class="mel-k">हिन्दी</div><p>{escape(qh["prompt"])}</p>{option_pills(qh)}</div>
<div><div class="mel-k">English</div><p>{escape(qe["prompt"])}</p>{option_pills(qe)}</div></div></div>''')
            html(guard_ticks(surveys) + '<span style="font-size:12px;color:#8a958d">⚑ = answer triggers a follow-up</span>')
        with col_p:
            ch = st.segmented_control("Channel preview", CHANNELS, default=h["channel_order"][0]["channel"],
                                      format_func=CH_NAME.get) or "app"
            lang = st.segmented_control("Language", list(surveys), default=ins["conversation_language"]) or "hi-IN"
            html(phone(clean(surveys[lang]), ch))
        handoff_strip(h, d.send_time)
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
        tickets.append({
            "response_key": rec["response_key"], "farmer_id": rec["farmer_id"],
            "asset": a.get("name"), "concern": ins.get("concern"),
            "survey_id": rec["survey_id"], "channel": ch, "recorded_at": rec["recorded_at"],
            "reason": t_reason, "item_id": t_item, "prompt": t_def.get("prompt", ""),
            "answer": _answer_label(t_def, t_val), "rec": rec, "insight": ins,
        })
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
                "Farmer": t["farmer_id"],
                "Crop / animal": t["asset"],
                "Survey": t["survey_id"],
                "Channel": CH_NAME.get(t["channel"], t["channel"]),
                "Flagged answer": f"{t['prompt']} → {t['answer']}",
                "Why": FU_REASON.get(t["reason"], t["reason"]),
                "Answered": t["recorded_at"],
            } for t in view]), width="stretch", hide_index=True, height=280)

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
            st.dataframe(pd.DataFrame([{
                "Run": c["run"], "What changed": c["change"], "Send-time rule": BASIS_LABEL.get(c["timing_basis"]),
                **{lab: (_pct(c[k][1]) if c[k][0] == c[k][1] else f"{_pct(c[k][0])} → {_pct(c[k][1])}")
                   for k, lab in (("decision_acc", "Decision"), ("window_acc", "Window match"),
                                  ("timeliness_pass", "Timeliness"))},
                "Misses": f"{c['misses'][0]} → {c['misses'][1]}"} for c in changed]),
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
