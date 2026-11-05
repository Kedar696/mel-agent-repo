"""The Dashboard tab, top to bottom: what the agent did with the whole participant pack, shown mostly as charts.

Every number is computed live: the batch the rest of the app uses (the pack through run_pipeline with history
and attention on, then P3's weekly limit) and mel.evaluation (answer key, scorecard, the committed judge files).
Charts follow the dataviz method: one hero figure, stat tiles, ranked bars instead of pies, validated colours,
a tooltip on every mark, and the numbers behind every chart in the details at the bottom.
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

# Feather icons (MIT), drawn with the current text colour.
_ICONS = {
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "check": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "award": '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
    "message": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "filter": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
}


def icon(name: str) -> str:
    return ('<svg class="mel-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>')


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


# ------------------------------------------------------------------------------------------------ sections
def _headline(n, surveyed, card, src, adapted, jrun):
    secs, ms = card["batch_seconds"], card["s_per_survey"] * 1000
    right = round(src["decision_acc"] * src["n"])
    files = card["n_survey_files"]
    worst = min(card["format_pass"], card["safety_pass"], card["timeliness_pass"])
    # The three pass/fail gates as one measured count (all three are exact on this run), next to the two graded
    # scores that are not pass/fail: the AI judge's 1-5 relevance and P4's 0-1 relevance score.
    checks = ((f"{files:,} / {files:,}", "pass every check") if worst == 1 else (_pct(worst), "pass the strictest check"))
    tiles = [
        ("target", _pct(src["decision_acc"]), "decisions right", f"{right} of {src['n']} answer-key cases", src["decision_acc"]),
        ("check", *checks, "format, safety and timing, Hindi and English", worst),
        ("shield", f"{jrun['judge_relevance']:.2f} / 5", "relevance, AI judge",
         f"Gemma 3 12B on Amazon Bedrock, {jrun['n']} surveys", jrun["judge_relevance"] / 5) if jrun else
        ("shield", f"{card['safety_pass']:.0%}", "safe", "no new advice, no personal data", card["safety_pass"]),
        ("clock", f"{card['relevance_avg']:.2f}", "relevance score", "P4's 0 to 1 check on every survey", card["relevance_avg"]),
        ("users", f"{adapted:,}", "personalized", "by the farmer's own history", adapted / max(len(surveyed), 1)),
        ("award", f"{card['failed_but_scheduled']}", "failing surveys scheduled", "a survey that fails a check is held back", None),
    ]
    tile_html = "".join(
        f'<div class="mel-d-tile">{icon(ic)}<div class="v{" sm" if len(v) > 9 else ""}"><span class="mel-count">{escape(v)}</span></div>'
        f'<div class="l">{escape(label)}</div><div class="n">{escape(note)}</div>'
        + (f'<div class="mel-d-meter"><i style="width:{share * 100:.1f}%"></i></div>' if share is not None else "")
        + "</div>" for ic, v, label, note, share in tiles)
    _html(f'<div class="mel-d-top"><div class="mel-d-hero">{icon("zap")}'
          f'<div><div class="mel-d-fig"><span class="mel-count">{secs:.0f}</span><small>s</small></div>'
          f'<div class="mel-d-cap">to read {n:,} conversations and write {len(surveyed):,} surveys</div>'
          f'<div class="mel-d-sub">{ms:.1f} ms per survey, Hindi and English</div></div></div>'
          f'<div class="mel-d-tiles">{tile_html}</div></div>')


def _flow(n, surveyed, lim):
    out = lim.get("sent", 0) + lim.get("moved", 0)
    steps = [("message", f"{n:,}", "conversations read"),
             ("filter", f"{len(surveyed):,}", f"worth a follow-up ({len(surveyed) / n:.0%})"),
             ("send", f"{out:,}", "go out within the weekly limit")]
    arrow = '<div class="mel-d-arrow">→</div>'
    _html('<div class="mel-d-flow">' + arrow.join(
        f'<div class="mel-d-step">{icon(ic)}<div><div class="v"><span class="mel-count">{v}</span></div>'
        f'<div class="l">{escape(label)}</div></div></div>' for ic, v, label in steps) + "</div>")


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
def render(*, rows, admits, upcoming, n_valid, n_files, evaluate_fn, rule_label, ch_name, channels, table, short):
    n = len(rows)
    surveyed = [(i, o) for i, o in rows if o["decision"].survey]
    rules = Counter(o["decision"].rule for _, o in rows)
    lim = Counter(d for d, _ in admits.values())
    ev, ak = evaluate_fn("brief"), evaluate_fn("answer_key")
    src, card = ev["full"] or ev["mock"], ev["card"]
    ak_src, ak_card = ak["full"] or ak["mock"], ak["card"]
    adapted = sum(any(s.get("_history") for s in o["surveys"].values()) for _, o in surveyed)

    # 1. Speed and quality at a glance, then the flow from conversation to farmer
    _headline(n, surveyed, card, src, adapted, load_summary().get("run"))
    _flow(n, surveyed, lim)

    # 2. What it decided and where the surveys go
    a, b = st.columns([1.3, 1], gap="medium")
    with a:
        c = _card("rules", "Why a survey, or not", f"Every one of the {n:,} conversations, by the rule that decided it")
        df = pd.DataFrame([{"rule": f"{r}  {rule_label[r]}", "n": rules.get(r, 0), "share": rules.get(r, 0) / n,
                            "g": "Survey" if r == "R8" else "No survey"} for r in rule_label])
        color = alt.Color("g:N", scale=alt.Scale(domain=["Survey", "No survey"], range=[BRIGHT, DEEP]), legend=None)
        _show(c, _ranked(df, "rule", "n", color, [alt.Tooltip("rule:N", title="Rule"), alt.Tooltip("n:Q", title="Conversations", format=","),
                                                  alt.Tooltip("share:Q", title="Share", format=".1%")]), 300)
    with b:
        c = _card("limit", "One survey per farmer per week", f"What the weekly limit did with the {len(surveyed):,} surveys")
        c.markdown(_segmented([("Sent as planned", lim.get("sent", 0)), ("Moved to a later week", lim.get("moved", 0)),
                               ("Merged into another survey", lim.get("merged", 0)), ("Skipped", lim.get("skipped", 0))], ORDINAL),
                   unsafe_allow_html=True)
        high = sum(o["handoff"]["priority"] == "high" for _, o in surveyed)
        c.markdown(f'<div class="mel-d-note"><b class="mel-count">{high:,}</b> high-priority surveys skip the limit</div>',
                   unsafe_allow_html=True)
        c2 = _card("channel", "First channel tried")
        ch = Counter(o["handoff"]["channel_order"][0]["channel"] for _, o in surveyed)
        chdf = pd.DataFrame([{"channel": ch_name[x], "n": ch.get(x, 0)} for x in channels])
        _show(c2, _ranked(chdf, "channel", "n", alt.value(DEEP), [alt.Tooltip("channel:N", title="Channel"),
                                                                  alt.Tooltip("n:Q", title="Surveys", format=",")]), 170)

    c = _card("weekly", "Surveys going out, week by week", "Rabi season, after the weekly limit")
    _show(c, _weekly(upcoming), 240)

    a, b, d = st.columns(3, gap="medium")
    with a:
        c = _card("crops", "Top crops and animals")
        crops = Counter((i.get("asset") or {}).get("name") for i, _ in rows if (i.get("asset") or {}).get("name"))
        cdf = pd.DataFrame([{"crop": str(k).title(), "n": v} for k, v in crops.most_common(8)])
        _show(c, _ranked(cdf, "crop", "n", alt.value(DEEP), [alt.Tooltip("crop:N", title="Crop or animal"),
                                                             alt.Tooltip("n:Q", title="Conversations", format=",")]), 260)
    with b:
        c = _card("people", "Who the farmers are")
        lang = Counter(i.get("conversation_language") for i, _ in rows)
        sev = Counter(str(i.get("severity") or "") for i, _ in rows)
        c.markdown('<div class="mel-d-lab">Language</div>' + _segmented(
            [("Hindi", lang.get("hi-IN", 0)), ("English", lang.get("en-IN", 0))], [DEEP, BLUE]), unsafe_allow_html=True)
        c.markdown('<div class="mel-d-lab">How serious</div>' + _segmented(
            [("Low", sev.get("low", 0)), ("Medium", sev.get("medium", 0)), ("High", sev.get("high", 0)),
             ("Critical", sev.get("critical", 0))], SEVERITY), unsafe_allow_html=True)
    with d:
        c = _card("attention", "Rising farmers get attention first")
        tiers = Counter((getattr(o["decision"], "attention", None) or {}).get("tier") for _, o in surveyed)
        c.markdown(_segmented([("Neutral", tiers.get("neutral", 0)), ("Steady-high, stepped down", tiers.get("steady_high", 0)),
                               ("Surge, rising", tiers.get("surge", 0))], [DEEP, BLUE, GOLD]), unsafe_allow_html=True)
        surges = _surges(rows)
        c.markdown(f'<div class="mel-d-big"><span class="mel-count">{len(surges):,}</span>'
                   f'<small>farmers on the rise this season</small></div>', unsafe_allow_html=True)

    # 3. Proof: the answer key, the timing choice, the hill-climb, the AI judge
    st.header("How we know it works")
    a, b = st.columns([1.1, 1], gap="medium")
    with a:
        right = round(src["decision_acc"] * src["n"])
        c = _card("confusion", f"{right} of {src['n']} answer-key decisions right", "The answer key down, the agent across")
        _show(c, _confusion(src), 300)
    with b:
        c = _card("timing", f"{card['timeliness_pass']:.0%} on time with the brief's timing",
                  f"The answer key's own send times are on time for only {_pct(ak_card['timeliness_pass'])} of surveys")
        tdf = pd.DataFrame([
            {"metric": "On time", "series": "Brief timing (ours)", "v": card["timeliness_pass"]},
            {"metric": "On time", "series": "Answer-key timing", "v": ak_card["timeliness_pass"]},
            {"metric": "Same window as the key", "series": "Brief timing (ours)", "v": src["window_acc"]},
            {"metric": "Same window as the key", "series": "Answer-key timing", "v": ak_src["window_acc"]}])
        _show(c, _paired(tdf, ["Brief timing (ours)", "Answer-key timing"], [DEEP, BLUE], "metric"), 260)

    a, b = st.columns([1.3, 1], gap="medium")
    with a:
        hist = _history()
        if hist is not None:
            runs = [r for r in load_history() if r.get("timing_basis") == "brief"]
            c = _card("history", f"Every change measured: {_pct(runs[0]['decision_acc'])} → {_pct(runs[-1]['decision_acc'])} decisions right",
                      "Each recorded run on the answer key; hover a dot for what changed")
            _show(c, hist, 260)
    judge = load_summary()
    cal = judge.get("calibration")
    with b:
        if cal:
            c = _card("judge", "The AI judge agrees with people more than people agree with each other",
                      "Share of the 20 hand-scored surveys within 1 point of a person")
            _show(c, _judge_bars(cal), 150)
            jrun = judge.get("run") or {}
            if jrun:
                c.markdown(f'<div class="mel-d-big"><span class="mel-count">{jrun["judge_relevance"]:.2f}</span><small>/ 5 average '
                           f'relevance on all {jrun["n"]} answer-key surveys</small></div>', unsafe_allow_html=True)

    sweep = load_models()
    chart, pick = _models(sweep)
    if chart is not None:
        n_ok = sum(1 for m in sweep.get("models", []) if m.get("rank"))
        title = (f"Best value of {n_ok} Bedrock models: {pick['provider']} {pick['name']}, ${pick['usd_per_1000_surveys']:.2f} per 1,000 surveys"
                 if pick else f"{n_ok} Bedrock models tried as the judge")
        c = _card("models", title, "Up is closer to the team's own scores, left is cheaper")
        _show(c, chart, 300)

    # 4. The numbers behind the charts
    st.header("Details")
    with st.expander(f"Highlighted farmers ({len(surges):,})"):
        reason = {"quiet_then_high_weight": "Quiet, then urgent", "activity_jump": "Activity jump"}
        if surges:
            table(pd.DataFrame([{
                "Farmer": i.get("farmer_id"), "Crop / animal": (i.get("asset") or {}).get("name"),
                "Why": reason.get(o["decision"].attention["reason"], o["decision"].attention["reason"]),
                "Weight": o["decision"].attention["weight"], "What we noticed": o["decision"].attention["explanation"],
                "When": short(i["created_at"]) if i.get("created_at") else "—"} for i, o in surges[:50]]),
                width="stretch", hide_index=True, height=260)
        else:
            st.caption("No surge farmers in this run.")
    with st.expander(f"Answer-key misses ({len(src['misses'])})"):
        if src["misses"]:
            table(pd.DataFrame(src["misses"]), width="stretch", hide_index=True)
        else:
            st.caption("No misses: every decision and rule matches.")
    with st.expander("Numbers behind the charts"):
        table(pd.DataFrame([{"Rule": r, "What it means": rule_label[r], "Conversations": rules.get(r, 0),
                             "Share": _pct(rules.get(r, 0) / n)} for r in rule_label]), width="stretch", hide_index=True)
        table(pd.DataFrame([{"Check": k, "Brief timing (ours)": a_, "Answer-key timing": b_} for k, a_, b_ in (
            ("Decisions right", _pct(src["decision_acc"]), _pct(ak_src["decision_acc"])),
            ("Rule right", _pct(src["rule_acc"]), _pct(ak_src["rule_acc"])),
            ("First channel right", _pct(src["channel_acc"]), _pct(ak_src["channel_acc"])),
            ("Same window as the key", _pct(src["window_acc"]), _pct(ak_src["window_acc"])),
            ("Questions match the key", f"{src['item_similarity_avg']:.2f}", f"{ak_src['item_similarity_avg']:.2f}"),
            ("Well-formed", _pct(card["format_pass"]), _pct(ak_card["format_pass"])),
            ("Safe", _pct(card["safety_pass"]), _pct(ak_card["safety_pass"])),
            ("On time", _pct(card["timeliness_pass"]), _pct(ak_card["timeliness_pass"])),
            ("Relevance (P4 score, 0 to 1)", f"{card['relevance_avg']:.2f}", f"{ak_card['relevance_avg']:.2f}"),
            ("Surveys", f"{card['n_surveyed']:,}", f"{ak_card['n_surveyed']:,}"),
            ("Schema-valid files", f"{n_valid:,} / {n_files:,}", ""))]), width="stretch", hide_index=True)
    hist_rows = load_history()
    if hist_rows:
        with st.expander(f"All recorded runs ({len(hist_rows)})"):
            table(pd.DataFrame(hist_rows), width="stretch", hide_index=True)
    if sweep.get("models"):
        with st.expander(f"All judge models ({len(sweep['models'])})"):
            table(pd.DataFrame([{"Rank": m.get("rank") or "—", "Provider": m["provider"], "Model": m["name"],
                                 "Ranking match (r)": m.get("rank_r"), "Within 1 point": _pct(m.get("within_1")),
                                 "Average gap": m.get("mean_abs_diff"), "USD per 1,000 surveys": m.get("usd_per_1000_surveys"),
                                 "Seconds per survey": m.get("seconds_per_call"), "Result": m.get("status")} for m in sweep["models"]]),
                  width="stretch", hide_index=True)
    if cal:
        with st.expander("How to read the AI judge numbers"):
            st.markdown(
                f"- A judge that always said 5 would be within 1 point {_pct(cal['always_5']['within_1'])} of the time, because "
                "people mostly gave 4s and 5s. The stronger sign is the ranking: the AI follows the team's average "
                f"(r = {cal.get('rank_r', 0):.2f}) more closely than any one of us does.\n"
                "- Small sample: 20 surveys scored by hand. Details in `docs/results/judge_calibration.md`.")
    att_json = Path(__file__).resolve().parents[1] / "docs" / "results" / "activity_attention.json"
    if att_json.exists():
        am = json.loads(att_json.read_text(encoding="utf-8"))
        with st.expander("Activity attention, off vs on"):
            pdf = pd.DataFrame([{"priority": p.title(), "series": s, "v": am[k].get(p, 0)}
                                for p in ("high", "normal", "low") for s, k in (("Attention off", "priority_off"), ("Attention on", "priority_on"))])
            top = float(pdf["v"].max() or 1)
            _show(st, _paired(pdf, ["Attention off", "Attention on"], [BLUE, DEEP], "priority", fmt=",", domain=(0, top * 1.15)), 220)
            st.caption(am["reason"] + ". Decision, rule and send window are identical with attention off and on; only "
                       "priority, question count and the send moment change.")
    if src.get("item_similarities"):
        with st.expander(f"Question match per answer-key case (average {src['item_similarity_avg']:.2f})"):
            table(pd.DataFrame(src["item_similarities"]), width="stretch", hide_index=True)
    for title, ex in (("Surveys that failed format or safety", card.get("examples")),
                      ("Send windows that failed timeliness", card.get("timeliness_examples"))):
        if ex:
            with st.expander(f"{title} ({len(ex)})"):
                table(pd.DataFrame(ex), width="stretch", hide_index=True)
