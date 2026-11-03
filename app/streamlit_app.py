"""MEL Survey Agent demo. Owner: P8.  Run: streamlit run app/streamlit_app.py
Layout borrowed from the v0 sketch (v0-sketch/): Overview, Survey Studio, Simulate, Evaluation.
Every number on screen comes from the real pipeline; nothing is hard-coded."""
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from mel.channels import render
from mel.channels.render import choices
from mel.config import CHANNELS
from mel.data import load_insights, errors
from mel.evaluation import score_golden
from mel.pipeline import run_insight, clean
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
.mel-strip{display:grid;grid-template-columns:110px 1.6fr 1.3fr 1fr;gap:22px;align-items:start}
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
    rows = [(ins, run_insight(ins)) for ins in load_insights()]
    led, capped = CapLedger(), set()
    hs = sorted((o["handoff"] for _, o in rows if "handoff" in o), key=lambda h: h["send_window"]["not_before"])
    for h in hs:
        if not led.allow(h):
            capped.add(h["handoff_id"])
    return rows, capped


rows, capped = batch()
st.title("MEL Survey Agent")
tab_over, tab_studio, tab_sim, tab_eval = st.tabs(["Overview", "Survey Studio", "Simulate answers", "Evaluation"])

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
    st.caption(f"{len(capped)} survey(s) would be held back by the cap; drop vs defer policy is still open (P4).")

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


def handoff_strip(h):
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
        handoff_strip(h)
        with st.expander("Raw JSON: survey, channel payload, hand-off"):
            st.json(clean(surveys[lang]), expanded=False)
            st.json(render(clean(surveys[lang]), ch), expanded=False)
            st.json(h, expanded=False)
        st.session_state["handoff"] = h

# ---------------------------------------------------------------- Simulate
with tab_sim:
    h = st.session_state.get("handoff")
    if not h:
        st.info("Pick an insight that gets a survey in the Survey Studio tab first.")
    else:
        ch = st.selectbox("Channel", CHANNELS)
        case = st.selectbox("Case", cases_for(ch))
        seed = st.number_input("Seed", 0, 999, 0)
        rec = simulate(h["survey"], ch, case, seed=int(seed))
        e = errors("response", rec)
        (st.error if e else st.success)(f"status={rec['status']} failure={rec['failure_code']} "
                                        f"follow_up={rec['follow_up_reasons']} schema={'FAIL' if e else 'ok'}")
        st.json(rec)

# ---------------------------------------------------------------- Evaluation
with tab_eval:
    if st.button("Score golden set"):
        r = score_golden()
        m = st.columns(4)
        for col, k in zip(m, ["decision_acc", "rule_acc", "channel_acc", "window_acc"]):
            col.metric(k, f"{r[k]:.1%}")
        st.dataframe(r["misses"])
