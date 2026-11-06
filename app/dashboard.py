"""The Dashboard tab, top to bottom: what the agent did with the whole participant pack, shown mostly as charts.

Every number is computed live: the batch the rest of the app uses (the pack through run_pipeline with history
and attention on, then P3's weekly limit) and mel.evaluation (answer key, scorecard, the committed judge files).
Charts follow the dataviz method: one hero figure, stat tiles, ranked bars instead of pies, validated colours,
and a tooltip on every mark.
"""
from collections import Counter
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
import json

import altair as alt
import pandas as pd
import streamlit as st

from mel.evaluation import load_history
from mel.evaluation.judge import load_summary
from mel.evaluation.judge_models import load as load_models

# FarmerChat greens (farmer.chat's tokens) plus the dataviz reference blue and yellow. Checked with the dataviz
# palette validator on the white card surface:
#   categorical DEEP, BLUE, GOLD: every check passes; GOLD is under 3:1, so wherever it appears it is labelled.
#   ordinal ORDINAL (dark to light): monotone lightness, one hue, light end 2.43:1 on white.
#   SEVERITY (light to dark red): the ramp the previous Dashboard validated.
DEEP, BRIGHT, BLUE, GOLD = "#00832B", "#00C950", "#2a78d6", "#eda100"
ORDINAL = ["#0B4524", "#00832B", "#00A843", "#3DBA68"]
SEVERITY = ["#EF9583", "#E5533D", "#B83A25", "#7A2416"]
PALE = "#BFE8CC"  # the context bars beside the one bar that matters
INK, MUTED, LINE = "#09090B", "#52525C", "#E4E4E7"
RULES = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8")

def _html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def _ink_on(hex_color: str) -> str:
    """White or near-black text for a label set inside a coloured block, by the fill's luminance."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = sum(w * (c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4) for w, c in zip((.2126, .7152, .0722), (r, g, b)))
    return INK if lum > .3 else "#FFFFFF"


def _card(key: str, title: str, sub: str = ""):
    """A white chart card (a keyed container, styled in app/theme.py) with a claim as its title."""
    box = st.container(key=f"dcard_{key}")
    box.markdown(f'<div class="mel-dh">{escape(title)}{f"<small>{escape(sub)}</small>" if sub else ""}</div>',
                 unsafe_allow_html=True)
    return box


def _show(where, chart, height: int):
    where.altair_chart(
        chart.properties(height=height, background="#FFFFFF").configure_view(stroke=None)
        .configure_axis(labelColor=MUTED, labelFont="Inter", labelFontSize=12, titleColor=MUTED, titleFont="Inter",
                        titleFontWeight=500, gridColor=LINE, domainColor=LINE, tickColor=LINE)
        .configure_legend(labelColor=INK, labelFont="Inter", labelFontSize=12.5, labelLimit=0, orient="top", symbolType="circle",
                          symbolSize=90),
        width="stretch")


def _ranked(df: pd.DataFrame, cat: str, val: str, color, tip: list, fmt: str = ","):
    """Ranked horizontal bars: one baseline, largest first, the value at each bar's tip."""
    df = df.sort_values(val, ascending=False)
    top = float(df[val].max() or 1)
    base = alt.Chart(df).encode(
        y=alt.Y(f"{cat}:N", sort=None, title=None,
                axis=alt.Axis(labelLimit=230, labelPadding=10, labelColor=INK, labelFontSize=13, domain=False, ticks=False)),
        x=alt.X(f"{val}:Q", title=None, axis=None, scale=alt.Scale(domain=[0, top * 1.16])))
    bars = base.mark_bar(size=16, cornerRadiusEnd=4).encode(color=color, tooltip=tip)
    tips = base.mark_text(align="left", dx=6, fontSize=12.5, fontWeight=600, color=INK).encode(
        text=alt.Text(f"{val}:Q", format=fmt))
    return bars + tips


def _segmented(parts: list, colors: list, unit: str = "") -> str:
    """A tall segmented bar (one whole, at most six parts): shares printed where they fit, names in the legend."""
    total = sum(n for _, n in parts) or 1
    blocks = "".join(
        f'<div style="flex:{n};background:{c};color:{_ink_on(c)}" title="{escape(name)}: {n:,}{unit} ({n / total:.0%})">'
        + (f"<span>{n / total:.0%}</span>" if n / total >= .07 else "") + "</div>"
        for (name, n), c in zip(parts, colors) if n)
    key = "".join(f'<span><i style="background:{c}"></i>{escape(name)}<b>{n:,}</b></span>'
                  for (name, n), c in zip(parts, colors))
    return f'<div class="mel-d-seg">{blocks}</div><div class="mel-d-key">{key}</div>'


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1%}".replace(".0%", "%")


def _kpis(cells: list, cls: str = "", title: str = "") -> str:
    """A KPI strip (one panel, cells split by hairlines): label on top, the value, a one-line note under it.
    `title` heads the panel; cls "funnel" puts an arrow between cells (each one is a subset of the one before)."""
    return (f'<div class="mel-kpis {cls}">' + (f'<div class="h">{escape(title)}</div>' if title else "") + "".join(
        f'<div class="k"><div class="l">{escape(label)}</div><div class="v"><span class="mel-count">{escape(v)}</span></div>'
        f'<div class="n">{escape(note)}</div></div>' for label, v, note in cells) + "</div>")


def _section(where, title: str, meta: str = ""):
    where.markdown(f'<div class="mel-dsec"><b>{escape(title)}</b>{f"<span>{escape(meta)}</span>" if meta else ""}</div>',
                   unsafe_allow_html=True)


def _weekly(upcoming) -> alt.Chart:
    weeks = Counter()
    for v in upcoming.values():
        for t, _ in v:
            day = datetime.fromisoformat(t).date()
            weeks[day - timedelta(days=day.weekday())] += 1
    df = pd.DataFrame([{"week": pd.Timestamp(w), "surveys": n, "label": f"Week of {w:%m/%d/%Y}"}
                       for w, n in sorted(weeks.items())])
    hover = alt.selection_point(fields=["week"], nearest=True, on="pointerover", empty=False)
    base = alt.Chart(df).encode(x=alt.X("week:T", title=None, axis=alt.Axis(format="%b %-d", grid=False)))
    y = alt.Y("surveys:Q", title=None, axis=alt.Axis(domain=False, ticks=False, tickCount=4))
    area = base.mark_area(interpolate="monotone", color=DEEP, opacity=.1).encode(y=y)
    line = base.mark_line(interpolate="monotone", strokeWidth=2, color=DEEP).encode(y=y)
    rule = base.mark_rule(color=MUTED, strokeWidth=1).encode(
        opacity=alt.condition(hover, alt.value(.6), alt.value(0)),
        tooltip=[alt.Tooltip("label:N", title="Week"), alt.Tooltip("surveys:Q", title="Surveys", format=",")]).add_params(hover)
    dots = base.mark_circle(size=90, color=DEEP, stroke="#FFFFFF", strokeWidth=2).encode(
        y=y, opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    return area + line + rule + dots


def _confusion(src) -> alt.Chart:
    df = pd.DataFrame([{"key": e, "agent": p, "n": c, "right": e == p} for e, row in src["confusion"].items() for p, c in row.items()])
    base = alt.Chart(df).encode(
        x=alt.X("agent:N", sort=list(RULES), title="Agent's rule", axis=alt.Axis(orient="top", labelAngle=0, domain=False, ticks=False)),
        y=alt.Y("key:N", sort=list(RULES), title="Answer key", axis=alt.Axis(domain=False, ticks=False)))
    tip = [alt.Tooltip("key:N", title="Answer key"), alt.Tooltip("agent:N", title="Agent"), alt.Tooltip("n:Q", title="Cases")]
    rect = base.mark_rect(cornerRadius=4, stroke="#FFFFFF", strokeWidth=2)
    empty = rect.transform_filter("datum.n == 0").encode(color=alt.value("#F4F4F5"), tooltip=tip)
    right = rect.transform_filter("datum.n > 0 && datum.right").encode(
        color=alt.Color("n:Q", scale=alt.Scale(range=["#3DBA68", "#0B4524"], type="sqrt"), legend=None), tooltip=tip)
    miss = rect.transform_filter("datum.n > 0 && !datum.right").encode(color=alt.value("#E5533D"), tooltip=tip)
    nums = base.transform_filter("datum.n > 0").mark_text(fontSize=12.5, fontWeight=700, color="#FFFFFF").encode(text="n:Q")
    return empty + right + miss + nums


def _paired(df: pd.DataFrame, series: list, colors: list, cat: str, val: str = "v", fmt: str = ".0%", domain=(0, 1)) -> alt.Chart:
    """Grouped columns for two series on one axis, the value on each cap."""
    base = alt.Chart(df).encode(
        x=alt.X(f"{cat}:N", title=None, sort=None, axis=alt.Axis(labelAngle=0, labelColor=INK, labelFontSize=13, labelLimit=240,
                                                                domain=False, ticks=False)),
        xOffset=alt.XOffset("series:N", sort=series),
        y=alt.Y(f"{val}:Q", title=None, scale=alt.Scale(domain=list(domain)), axis=alt.Axis(format=fmt, tickCount=3, domain=False, ticks=False)))
    cols = base.mark_bar(size=22, cornerRadiusEnd=4).encode(
        color=alt.Color("series:N", sort=series, scale=alt.Scale(domain=series, range=colors), legend=alt.Legend(title=None)),
        tooltip=[alt.Tooltip("series:N", title=" "), alt.Tooltip(f"{cat}:N", title=" "), alt.Tooltip(f"{val}:Q", format=fmt)])
    caps = base.mark_text(dy=-8, fontSize=12, fontWeight=700, color=INK).encode(text=alt.Text(f"{val}:Q", format=fmt))
    return cols + caps


def _history() -> alt.Chart | None:
    runs = [r for r in load_history() if r.get("timing_basis") == "brief"]
    if len(runs) < 2:
        return None
    series = ["Decisions right", "Questions match the key"]
    df = pd.DataFrame([{"run": f"Run {r['run']}", "series": s, "v": r.get(k), "what": (r.get("label") or r.get("change") or "")[:80]}
                       for r in runs for s, k in zip(series, ("decision_acc", "item_similarity_avg")) if r.get(k) is not None])
    order = [f"Run {r['run']}" for r in runs]
    base = alt.Chart(df).encode(
        x=alt.X("run:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, domain=False, ticks=False)),
        y=alt.Y("v:Q", title=None, scale=alt.Scale(domain=[0.4, 1]), axis=alt.Axis(format="%", tickCount=4, domain=False, ticks=False)),
        color=alt.Color("series:N", sort=series, scale=alt.Scale(domain=series, range=[DEEP, BLUE]), legend=alt.Legend(title=None)))
    tip = [alt.Tooltip("run:N", title="Run"), alt.Tooltip("series:N", title=" "), alt.Tooltip("v:Q", title="Score", format=".1%"),
           alt.Tooltip("what:N", title="What changed")]
    lines = base.mark_line(strokeWidth=2.5, interpolate="monotone")
    dots = base.mark_circle(size=110, stroke="#FFFFFF", strokeWidth=2, opacity=1).encode(tooltip=tip)
    return lines + dots


def _judge_bars(cal) -> alt.Chart:
    df = pd.DataFrame([
        {"who": "AI judge (Gemma 3 12B)", "v": cal["within_1"], "g": "AI"},
        {"who": "Two people, each other", "v": cal["people_vs_people"]["within_1"], "g": "ref"},
        {"who": "A judge that always says 5", "v": cal["always_5"]["within_1"], "g": "ref"},
    ])
    color = alt.Color("g:N", scale=alt.Scale(domain=["AI", "ref"], range=[BRIGHT, PALE]), legend=None)
    return _ranked(df, "who", "v", color, [alt.Tooltip("who:N", title=" "), alt.Tooltip("v:Q", title="Within 1 point", format=".0%")],
                   fmt=".0%")


BLIND = Path(__file__).resolve().parents[1] / "docs" / "results"


def load_blind() -> tuple[dict | None, int]:
    """(people's blind comparison from scripts/blind_sheet.py score, or None; number of pairs on the sheet)."""
    try:
        pairs = max(0, len((BLIND / "blind_sheet.csv").read_text(encoding="utf-8").splitlines()) - 1)
    except OSError:
        pairs = 0
    try:
        res = json.loads((BLIND / "blind_comparison.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = None
    if res and not (res.get("preferred", {}).get("bedrock", 0) + res.get("preferred", {}).get("template", 0)
                    + res.get("preferred", {}).get("same", 0)):
        res = None
    return res, pairs


def _blind():
    """People score Bedrock and template surveys side by side without knowing which is which (scripts/blind_sheet.py).
    It checks the AI judge's preference for Bedrock, which may only reward the longer questions."""
    res, pairs = load_blind()
    if not pairs and not res:
        return
    if not res:
        c = _card("blind", "People's blind comparison: Bedrock vs templates",
                  f"Scoring in progress: {pairs} pairs, each a Bedrock survey and a template survey for the same "
                  "conversation, in random order. People score both without knowing which is which.")
        c.caption("The AI judge prefers the Bedrock surveys, but they are about twice as long, and a judge may reward length. "
                  "This panel fills in when the scores are back (python scripts/blind_sheet.py score ...).")
        return
    pref, mean = res.get("preferred", {}), res.get("mean_score", {})
    b, t, same = pref.get("bedrock", 0), pref.get("template", 0), pref.get("same", 0)
    who = ", ".join(res.get("scorers") or []) or "the team"
    c = _card("blind", f"People's blind comparison: {res.get('verdict', '')}",
              f"{res.get('rows_scored', 0)} scored pairs from {who}; nobody knew which survey was which")
    rows = [{"metric": "Mean score (1-5)", "series": s, "v": mean.get(k)} for s, k in (("Bedrock", "bedrock"), ("Templates", "template"))
            if mean.get(k) is not None]
    if rows:
        _show(c, _paired(pd.DataFrame(rows), ["Bedrock", "Templates"], [DEEP, BLUE], "metric", fmt=".2f", domain=(0, 5)), 200)
    longer = res.get("longer_survey", {})
    lw, sw = longer.get("longer won", 0), longer.get("shorter won", 0)
    chars = res.get("avg_survey_chars", {})
    c.markdown(
        f"Picked as better: **Bedrock {b}**, **templates {t}**, same {same} (sign test p = {res.get('p_value_sign_test')}). "
        + (f"The longer survey won {lw} of {lw + sw} picks. " if lw + sw else "")
        + (f"Bedrock surveys average {chars.get('bedrock'):.0f} characters of questions, templates {chars.get('template'):.0f}."
           if chars.get("bedrock") and chars.get("template") else ""))


def _models(sweep) -> tuple[alt.Chart | None, dict | None]:
    ok = [m for m in sweep.get("models", []) if m.get("rank") and m.get("usd_per_1000_surveys") and m.get("rank_r") is not None]
    if not ok:
        return None, None
    pick_id = sweep.get("best_value") or sweep.get("most_accurate")
    df = pd.DataFrame([{"model": f"{m['provider']} {m['name']}", "cost": m["usd_per_1000_surveys"], "r": m["rank_r"],
                        "pick": m["model_id"] == pick_id, "secs": m.get("seconds_per_call")} for m in ok])
    base = alt.Chart(df).encode(
        x=alt.X("cost:Q", title="Cost per 1,000 surveys (USD, log scale)", scale=alt.Scale(type="log"),
                axis=alt.Axis(format="$,.2~f", values=[0.01, 0.1, 1, 10, 100], grid=False, domain=False, ticks=False)),
        y=alt.Y("r:Q", title="Follows the team's ranking (r)", scale=alt.Scale(domain=[-1, 1]),
                axis=alt.Axis(tickCount=5, domain=False, ticks=False)),
        tooltip=[alt.Tooltip("model:N", title="Model"), alt.Tooltip("cost:Q", title="Per 1,000 surveys", format="$,.4f"),
                 alt.Tooltip("r:Q", title="Ranking match", format=".2f"), alt.Tooltip("secs:Q", title="Seconds per survey", format=".2f")])
    others = base.transform_filter("!datum.pick").mark_circle(size=70, color=DEEP, opacity=.28)
    pick = base.transform_filter("datum.pick").mark_circle(size=260, color=BRIGHT, stroke="#FFFFFF", strokeWidth=2, opacity=1)
    label = base.transform_filter("datum.pick").mark_text(align="left", dx=12, fontSize=13, fontWeight=700, color=INK).encode(
        text="model:N")
    return others + pick + label, next((m for m in ok if m["model_id"] == pick_id), None)


def _costs(ledger: list, full: dict | None, n_conv: int, share: float):
    """A Bedrock cost calculator priced only from measured runs (P5's ledger, mel.evaluation.costs): pick how many
    conversations, the share that get a survey (default: the batch's own), the measured run to price from, and
    whether the AI judge counts; then cost per 1,000 surveys run by run. Nothing shows until a paid run is logged."""
    priced = [r for r in ledger if r.get("usd_per_survey") is not None and r.get("kind") in ("batch", "pilot", "partial")]
    if not priced:
        return
    c = _card("cost", "Bedrock cost calculator", "Priced from measured runs: writing, checking and judging; cached answers cost nothing")
    k = c.columns([1.1, 1, 1.9, 0.9], vertical_alignment="bottom")
    conv = k[0].number_input("Farmer conversations", 0, 100_000_000, n_conv, 1000, key="calc_conv",
                             help=f"Default: this season's pack, {n_conv:,} conversations")
    pct = k[1].slider("Share that get a survey", 0, 100, round(share * 100), key="calc_share", format="%d%%",
                      help=f"Default: what the agent decided on the pack ({share:.0%})")
    by_run = {r["run"]: r for r in priced}
    run = k[2].selectbox("Price from", list(reversed(by_run)), key="calc_basis",
                         format_func=lambda x: f"Run {x} · {by_run[x]['label'].split(':')[-1].strip()[:46]} · "
                                               f"${by_run[x]['usd_per_1000_surveys']:.2f} / 1,000",
                         help="Each measured run's full price per survey (cache hits priced from the tokens they took). "
                              "Run 2 had Bedrock Guardrails and the check model; the compact-writer runs did not.")
    judge = k[3].toggle("AI judge", value=True, key="calc_judge", help="Quality scoring with the AI judge (Gemma 3 12B)")
    r = by_run[run]
    parts = {p_: (v or {}).get("usd", 0) for p_, v in (r.get("by_purpose") or {}).items()}
    per = r["usd_per_survey"] * (1 - (0 if judge else parts.get("judge", 0) / (sum(parts.values()) or 1)))
    surveys = round(conv * pct / 100)
    cost = surveys * per
    money = lambda v: f"${v:,.2f}" if v >= 1 or v == 0 else f"${v:.4f}"
    c.markdown(_kpis([("Surveys written", f"{surveys:,}", f"{pct}% of {conv:,} conversations"),
                      ("Bedrock cost", money(cost), "Hindi and English, checks included"),
                      ("Per 1,000 conversations", money(cost / conv * 1000) if conv else "—", "the price of listening at scale"),
                      ("Per survey", f"${per:.4f}", f"run {run}, {r['surveys']:,} surveys measured")], "flat"),
               unsafe_allow_html=True)
    at = lambda n: money(n * pct / 100 * per)
    actual = (f"Full run, actual: <b>${(full.get('cost') or {}).get('spent_usd') or 0:.2f}</b> for {full['surveys']:,} surveys in "
              f"{full['seconds'] / 60:.0f} min" + (", stopped at the cap" if full.get("stopped_at_cap") else "") if full
              else "Full run: not run yet (python -m mel.agent.batch)")
    c.markdown(f'<div class="mel-d-body">At this rate: 100,000 conversations ≈ <b>{at(100_000)}</b> · 1 million ≈ '
               f'<b>{at(1_000_000)}</b>. {actual}. Basis: run {run}, ${r["usd_per_1000_surveys"]:.2f} per 1,000 surveys.</div>',
               unsafe_allow_html=True)
    if len(priced) >= 2:
        df = pd.DataFrame([{"run": f"Run {x['run']}", "what": x.get("label") or x.get("kind"), "v": x["usd_per_1000_surveys"],
                            "per": x["usd_per_survey"], "pick": x["run"] == run} for x in priced])
        base = alt.Chart(df).encode(
            x=alt.X("run:N", sort=list(df["run"]), title=None, axis=alt.Axis(labelAngle=0, domain=False, ticks=False)),
            y=alt.Y("v:Q", title=None, axis=alt.Axis(format="$,.2f", tickCount=4, domain=False, ticks=False)))
        tip = [alt.Tooltip("run:N", title="Run"), alt.Tooltip("what:N", title="What"),
               alt.Tooltip("v:Q", title="Per 1,000 surveys", format="$,.2f"), alt.Tooltip("per:Q", title="Per survey", format="$,.5f")]
        c.markdown('<div class="mel-d-lab">Cost per 1,000 surveys, run by run (the run priced from is larger)</div>',
                   unsafe_allow_html=True)
        _show(c, base.mark_line(strokeWidth=2, color=DEEP) + base.mark_circle(color=DEEP, stroke="#FFFFFF", strokeWidth=2, opacity=1)
              .encode(size=alt.condition("datum.pick", alt.value(170), alt.value(80)), tooltip=tip), 150)


def _surges(rows):
    """Each surge farmer's most recent surge insight, strongest first (the activity-attention highlight)."""
    latest = {}
    for i, o in rows:
        att = getattr(o["decision"], "attention", None) or {}
        if att.get("tier") != "surge":
            continue
        fid = i.get("farmer_id")
        if fid not in latest or (i.get("created_at") or "") > (latest[fid][0].get("created_at") or ""):
            latest[fid] = (i, o)
    return sorted(latest.values(), key=lambda io: (io[1]["decision"].attention["weight"], io[0].get("created_at", "")), reverse=True)


# ------------------------------------------------------------------------------------------------ the tab
def render(*, rows, admits, upcoming, evaluate_fn, rule_label, ch_name, channels):
    """Overview first: only the batch the app already ran, so it costs nothing. The golden-set evaluation
    (answer key + checks on every survey, both send-time rules) runs only when someone presses Run evaluation."""
    n = len(rows)
    surveyed = [(i, o) for i, o in rows if o["decision"].survey]
    rules = Counter(o["decision"].rule for _, o in rows)
    lim = Counter(d for d, _ in admits.values())
    out = lim.get("sent", 0) + lim.get("moved", 0)
    adapted = sum(any(s.get("_history") for s in o["surveys"].values()) for _, o in surveyed)
    high = sum(o["handoff"]["priority"] == "high" for _, o in surveyed)
    surges = _surges(rows)
    tiers = Counter((getattr(o["decision"], "attention", None) or {}).get("tier") for _, o in surveyed)
    share = lambda k: f"{k / max(len(surveyed), 1):.0%} of planned"

    from mel.evaluation.costs import load_costs
    ledger = load_costs()     # docs/results/cost_history.jsonl: one row per run that wrote surveys with Bedrock
    try:
        full = json.loads((Path(__file__).resolve().parents[1] / "docs" / "results" / "full_bedrock_run.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        full = None

    # ---- Overview
    _section(st, "Overview")
    # Left: a funnel, each step a subset of the one before. Right: traits of the planned surveys (same unit: surveys).
    _html('<div class="mel-kpi-row">' + _kpis([
        ("Conversations read", f"{n:,}", "every insight in the pack"),
        ("Surveys planned", f"{len(surveyed):,}", f"{len(surveyed) / max(n, 1):.0%} of conversations"),
        ("Going out", f"{out:,}", f"{out / max(len(surveyed), 1):.0%} of planned, after the weekly limit"),
    ], "funnel", "From conversation to survey") + _kpis([
        ("High priority", f"{high:,}", f"{share(high)} · skip the weekly limit"),
        ("Personalized", f"{adapted:,}", f"{share(adapted)} · use the farmer's history"),
        ("Rising activity", f"{tiers.get('surge', 0):,}", f"{share(tiers.get('surge', 0))} · from {len(surges):,} farmers on the rise"),
    ], title=f"Of the {len(surveyed):,} planned surveys") + "</div>")

    a, b = st.columns([2, 1], gap="small")
    with a:
        c = _card("weekly", "Surveys going out per week", "After the weekly limit")
        _show(c, _weekly(upcoming), 232)
    with b:
        c = _card("limit", "Weekly limit", f"What happened to the {len(surveyed):,} planned surveys")
        c.markdown(_segmented([("Sent as planned", lim.get("sent", 0)), ("Moved to a later week", lim.get("moved", 0)),
                               ("Merged into another", lim.get("merged", 0)), ("Skipped", lim.get("skipped", 0))], ORDINAL),
                   unsafe_allow_html=True)

    a, b = st.columns(2, gap="small")
    with a:
        c = _card("rules", "Survey decision by rule", f"All {n:,} conversations, by the rule that decided")
        df = pd.DataFrame([{"rule": f"{r}  {rule_label[r]}", "n": rules.get(r, 0), "share": rules.get(r, 0) / n,
                            "g": "Survey" if r == "R8" else "No survey"} for r in rule_label])
        color = alt.Color("g:N", scale=alt.Scale(domain=["Survey", "No survey"], range=[BRIGHT, DEEP]), legend=None)
        _show(c, _ranked(df, "rule", "n", color, [alt.Tooltip("rule:N", title="Rule"), alt.Tooltip("n:Q", title="Conversations", format=","),
                                                  alt.Tooltip("share:Q", title="Share", format=".1%")]), 270)
    with b:
        c = _card("crops", "Top crops and animals", "Conversations per crop or animal")
        crops = Counter((i.get("asset") or {}).get("name") for i, _ in rows if (i.get("asset") or {}).get("name"))
        cdf = pd.DataFrame([{"crop": str(k).title(), "n": v} for k, v in crops.most_common(8)])
        _show(c, _ranked(cdf, "crop", "n", alt.value(DEEP), [alt.Tooltip("crop:N", title="Crop or animal"),
                                                             alt.Tooltip("n:Q", title="Conversations", format=",")]), 270)

    a, b, d = st.columns(3, gap="small")
    with a:
        c = _card("channel", "First channel tried", "Surveys by the channel tried first")
        ch = Counter(o["handoff"]["channel_order"][0]["channel"] for _, o in surveyed)
        chdf = pd.DataFrame([{"channel": ch_name[x], "n": ch.get(x, 0)} for x in channels])
        _show(c, _ranked(chdf, "channel", "n", alt.value(DEEP), [alt.Tooltip("channel:N", title="Channel"),
                                                                 alt.Tooltip("n:Q", title="Surveys", format=",")]), 180)
    with b:
        c = _card("people", "Farmers", "Language and how serious the problem was")
        lang = Counter(i.get("conversation_language") for i, _ in rows)
        sev = Counter(str(i.get("severity") or "") for i, _ in rows)
        c.markdown('<div class="mel-d-lab">Language</div>' + _segmented(
            [("Hindi", lang.get("hi-IN", 0)), ("English", lang.get("en-IN", 0))], [DEEP, BLUE]), unsafe_allow_html=True)
        c.markdown('<div class="mel-d-lab">Severity</div>' + _segmented(
            [("Low", sev.get("low", 0)), ("Medium", sev.get("medium", 0)), ("High", sev.get("high", 0)),
             ("Critical", sev.get("critical", 0))], SEVERITY), unsafe_allow_html=True)
    with d:
        c = _card("attention", "Activity attention", "Planned surveys by the farmer's activity trend")
        c.markdown(_segmented([("Neutral", tiers.get("neutral", 0)), ("Steady-high, stepped down", tiers.get("steady_high", 0)),
                               ("Surge, rising", tiers.get("surge", 0))], [DEEP, BLUE, GOLD]), unsafe_allow_html=True)

    _costs(ledger, full, n, len(surveyed) / max(n, 1))

    # ---- Evaluation: nothing is scored until the button is pressed
    ran = st.session_state.get("dash_eval", False)
    _section(st, "Evaluation", "150-case answer key and checks on every survey" if ran else "Not run yet")
    if not ran:
        c = _card("eval_idle", "Golden-set evaluation")
        c.markdown('<div class="mel-d-body">Scores the agent\'s decisions, rules, channels and send windows against the '
                   f"150-case answer key and checks all {len(surveyed):,} surveys for format, safety and timing under both "
                   "send-time rules, then adds the AI judge, the judge model sweep and the people's blind comparison. "
                   "Nothing is scored until you run it.</div>", unsafe_allow_html=True)
        c.button("Run evaluation", key="dash_eval_run", type="primary", icon=":material/play_arrow:",
                 on_click=lambda: st.session_state.update(dash_eval=True))
        return
    _evaluation(evaluate_fn)


def _evaluation(evaluate_fn):
    ev, ak = evaluate_fn("brief"), evaluate_fn("answer_key")
    src, card = ev["full"] or ev["mock"], ev["card"]
    ak_src, ak_card = ak["full"] or ak["mock"], ak["card"]
    judge = load_summary()
    jrun, cal = judge.get("run") or {}, judge.get("calibration")
    files, worst = card["n_survey_files"], min(card["format_pass"], card["safety_pass"], card["timeliness_pass"])
    right = round(src["decision_acc"] * src["n"])
    _html(_kpis([
        ("Decisions right", _pct(src["decision_acc"]), f"{right} of {src['n']} answer-key cases"),
        ("Checks passed", _pct(worst), f"format, safety, timing; {files:,} survey files" if worst == 1 else "the strictest of the three"),
        ("AI judge relevance", f"{jrun['judge_relevance']:.2f} / 5" if jrun else "—",
         f"Gemma 3 12B, {jrun['n']} surveys" if jrun else "no judge run recorded"),
        ("Relevance score", f"{card['relevance_avg']:.2f}", "P4's 0 to 1 check, every survey"),
        ("Failing surveys sent", f"{card['failed_but_scheduled']}", "a failing survey is held back"),
        ("Batch time", f"{card['batch_seconds']:.0f} s", f"{card['s_per_survey'] * 1000:.1f} ms per survey"),
    ]))

    a, b = st.columns(2, gap="small")
    with a:
        c = _card("confusion", "Answer key vs agent", f"{right} of {src['n']} decisions right; the key down, the agent across")
        _show(c, _confusion(src), 290)
    with b:
        c = _card("timing", "Send timing: brief vs answer key",
                  f"{card['timeliness_pass']:.0%} on time with the brief's rule; the key's own times only "
                  f"{_pct(ak_card['timeliness_pass'])}")
        tdf = pd.DataFrame([
            {"metric": "On time", "series": "Brief timing (ours)", "v": card["timeliness_pass"]},
            {"metric": "On time", "series": "Answer-key timing", "v": ak_card["timeliness_pass"]},
            {"metric": "Same window as the key", "series": "Brief timing (ours)", "v": src["window_acc"]},
            {"metric": "Same window as the key", "series": "Answer-key timing", "v": ak_src["window_acc"]}])
        _show(c, _paired(tdf, ["Brief timing (ours)", "Answer-key timing"], [DEEP, BLUE], "metric"), 290)

    a, b = st.columns(2, gap="small")
    with a:
        hist = _history()
        if hist is not None:
            runs = [r for r in load_history() if r.get("timing_basis") == "brief"]
            c = _card("history", "Run history",
                      f"Decisions right {_pct(runs[0]['decision_acc'])} → {_pct(runs[-1]['decision_acc'])}; hover a dot for what changed")
            _show(c, hist, 240)
    with b:
        if cal:
            c = _card("judge", "Can we trust the AI judge?",
                      "Share of the 20 hand-scored surveys within 1 point of a person")
            _show(c, _judge_bars(cal), 150)

    sweep = load_models()
    chart, pick = _models(sweep)
    a, b = st.columns([1.6, 1], gap="small")
    if chart is not None:
        n_ok = sum(1 for m in sweep.get("models", []) if m.get("rank"))
        with a:
            c = _card("models", f"Judge model sweep: {n_ok} Bedrock models",
                      (f"Pick: {pick['provider']} {pick['name']}, ${pick['usd_per_1000_surveys']:.2f} per 1,000 surveys. " if pick else "")
                      + "Up is closer to the team's scores, left is cheaper")
            _show(c, chart, 280)
    with b:
        _blind()
