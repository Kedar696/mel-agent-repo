"""Fasal Pulse visual theme. Owner: UI/UX design (C).

`apply_theme()` injects the app's global CSS once per run: palette variables, type scale, surfaces (the ivory
page, the deep-green insight card), tabs, metrics, controls, motion and the narrow-screen rules.
`.streamlit/config.toml` carries the same palette for the parts of Streamlit that CSS cannot reach (widget
colours, fonts, radii). `docs/uiux-design.md` explains the choices and the channel references.

Design notes
- Northern India, rabi season: wheat-straw ivory page, one strong surface in deep leaf green, marigold only
  where attention is earned (the "why" line, follow-up flags, focus rings), clay only for warnings.
- Mukta (Ek Type) carries Hindi and English in one family; system Devanagari fonts are the fallback.
- Body 17px, labels never under 13px, no uppercase micro-labels, no drop shadows: hierarchy comes from size,
  weight and the ivory / sandstone / paper surface steps.
- Selector policy: Streamlit parts are addressed by their stable `data-testid` attributes (1.66 renders tabs,
  button groups and selects with React Aria, so `role` and `data-variant` help too), never by generated
  class names. Button rules are light (border, weight, height, focus); a preview that
  needs its own look scopes rules under its keyed container (`.st-key-... [data-testid=...]`), which beats
  these by specificity without `!important`.
"""
import streamlit as st

# Hex values for Python callers (chart colours, st.bar_chart(color=...)). Same values as the CSS variables.
PALETTE = {
    "ivory": "#F7F3E8", "sand": "#EEE7D7", "paper": "#FFFDF8", "line": "#DED6C3",
    "ink": "#1E2A22", "muted": "#5F6B62",
    "green": "#2A6B4A", "green_deep": "#1E5A3F", "green_ink": "#174A33", "green_soft": "#E3EFE4",
    "marigold": "#E3A51F", "marigold_ink": "#8A5A0C", "marigold_soft": "#FBEFD0",
    "clay": "#A4422E", "clay_soft": "#F7E4DE", "slate": "#5D6A62",
}

CSS = """
:root{
  --mel-ivory:#F7F3E8;--mel-sand:#EEE7D7;--mel-paper:#FFFDF8;--mel-line:#DED6C3;--mel-line-strong:#C9BFA6;
  --mel-ink:#1E2A22;--mel-ink-soft:#44524A;--mel-muted:#5F6B62;
  --mel-green:#2A6B4A;--mel-green-deep:#1E5A3F;--mel-green-ink:#174A33;--mel-green-soft:#E3EFE4;--mel-green-pale:#BFDCC6;
  --mel-marigold:#E3A51F;--mel-marigold-pale:#F6D37C;--mel-marigold-soft:#FBEFD0;--mel-marigold-ink:#8A5A0C;
  --mel-clay:#A4422E;--mel-clay-soft:#F7E4DE;--mel-slate:#5D6A62;--mel-slate-soft:#ECEAE2;
  --mel-wa:#075E54;--mel-wa-bar:#008069;--mel-wa-bg:#ECE5DD;--mel-wa-in:#FFFFFF;--mel-wa-out:#DCF8C6;--mel-wa-link:#027EB5;
  --mel-tg:#2AABEE;--mel-tg-bar:#517DA2;--mel-tg-bg:#E6EBEE;--mel-tg-in:#FFFFFF;--mel-tg-out:#EFFDDE;--mel-tg-link:#168ACD;
  --mel-font:"Mukta","Kohinoor Devanagari","Devanagari Sangam MN","Nirmala UI","Noto Sans Devanagari","Noto Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mel-mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --mel-fs-body:17px;--mel-fs-small:14px;--mel-fs-label:13px;--mel-fs-lead:19px;
  --mel-lh:1.55;--mel-lh-hi:1.65;
  --mel-r-card:14px;--mel-r-ctl:10px;--mel-r-pill:999px;
  --mel-t-fast:140ms;--mel-t-base:220ms;--mel-ease:cubic-bezier(.2,.7,.2,1);
  --mel-gap:12px;
}

/* ---- page ---------------------------------------------------------------- */
[data-testid="stAppViewContainer"]{background:var(--mel-ivory);color:var(--mel-ink)}
[data-testid="stHeader"]{background:var(--mel-ivory)}
[data-testid="stDecoration"]{display:none}
[data-testid="stAppDeployButton"]{display:none}  /* deployment-only chrome; the menu stays for settings and rerun */
[data-testid="stMainBlockContainer"]{max-width:1380px;padding-left:max(16px,2.5vw);padding-right:max(16px,2.5vw)}
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{line-height:var(--mel-lh)}
[data-testid="stMarkdownContainer"] p:lang(hi){line-height:var(--mel-lh-hi)}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{font-size:var(--mel-fs-small);color:var(--mel-muted);line-height:1.5}
[data-testid="stHeading"] h1,[data-testid="stHeading"] h2,[data-testid="stHeading"] h3{letter-spacing:0;color:var(--mel-ink)}
[data-testid="stHeading"] h2{margin-top:.6rem}
[data-testid="stWidgetLabel"] p{font-size:15px;font-weight:500;color:var(--mel-ink-soft)}
a{color:var(--mel-green)}
.mel-lead{font-size:var(--mel-fs-lead);line-height:1.5;color:var(--mel-ink-soft);margin:0 0 12px}
.mel-note{font-size:var(--mel-fs-small);color:var(--mel-muted);line-height:1.5}
.mel-hi{line-height:var(--mel-lh-hi)}

/* ---- masthead, report title line, section labels ---------------------------- */
.mel-mast{display:flex;align-items:baseline;justify-content:space-between;gap:6px 24px;flex-wrap:wrap;padding:4px 0 12px;border-bottom:1px solid var(--mel-line)}
.mel-mast .mel-brand{font-size:26px;font-weight:700;color:var(--mel-green-ink);line-height:1.1;letter-spacing:0}
.mel-mast .mel-brand span{font-size:17px;font-weight:500;color:var(--mel-muted);margin-left:10px}
.mel-mast .mel-tag{font-size:14px;color:var(--mel-muted)}
.mel-report{display:flex;align-items:flex-end;justify-content:space-between;gap:6px 24px;flex-wrap:wrap;padding:14px 0 12px;border-bottom:1px solid var(--mel-line);margin:2px 0 14px;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
.mel-report .mel-kicker{font-size:13px;font-weight:600;color:var(--mel-green-ink);margin-bottom:2px}
.mel-report .mel-kicker.own{color:var(--mel-marigold-ink)}
.mel-report h2{font-size:24px;font-weight:600;margin:0;line-height:1.25;color:var(--mel-ink);letter-spacing:0}
.mel-report .mel-sum{font-size:15px;line-height:1.45;color:var(--mel-ink-soft);max-width:560px;text-align:right}
.mel-sec{font-size:13px;font-weight:600;color:var(--mel-muted);margin:0 0 8px}
.mel-source{padding:0 0 8px;font-size:17px;line-height:1.4}
.mel-source .mel-k{margin-bottom:6px}
.mel-source b{color:var(--mel-marigold-ink);font-weight:600;margin-right:8px}

/* ---- tabs (Streamlit 1.66: stTabs > [role=tablist] > stTab; panels stTabPanel) ------ */
[data-testid="stTabs"] [role="tablist"]{gap:4px;border-bottom:1px solid var(--mel-line)}
[data-testid="stTab"]{padding:10px 16px;border-radius:10px 10px 0 0;color:var(--mel-muted);transition:color var(--mel-t-fast),background var(--mel-t-fast),box-shadow var(--mel-t-fast)}
[data-testid="stTab"] p{font-size:17px;font-weight:500}
[data-testid="stTab"]:hover{color:var(--mel-ink);box-shadow:inset 0 -3px 0 var(--mel-line-strong)}
[data-testid="stTab"][aria-selected="true"]{color:var(--mel-green-ink);box-shadow:inset 0 -3px 0 var(--mel-green)}
[data-testid="stTab"][aria-selected="true"] p{font-weight:600}
[data-testid="stTabPanel"]{padding-top:18px}
[data-testid="stTabPanel"]>div{animation:mel-rise var(--mel-t-base) var(--mel-ease) both}

/* ---- metrics, expanders, alerts ------------------------------------------ */
[data-testid="stMetric"]{background:var(--mel-paper);border:1px solid var(--mel-line);border-radius:var(--mel-r-card);padding:14px 16px 12px;min-height:8rem}
[data-testid="stMetricLabel"] p{font-size:var(--mel-fs-small);color:var(--mel-muted);font-weight:500}
[data-testid="stMetricValue"]{color:var(--mel-ink)}
[data-testid="stMetricDelta"]{font-size:var(--mel-fs-label);color:var(--mel-muted)}
[data-testid="stExpander"] details{background:var(--mel-paper);border-color:var(--mel-line);border-radius:var(--mel-r-card)}
[data-testid="stExpander"] summary{padding:12px 16px}
[data-testid="stExpander"] summary:hover{color:var(--mel-green-ink)}
[data-testid="stAlert"]{border-radius:var(--mel-r-card)}

/* ---- controls (kept light on purpose; see selector policy above) ---------- */
[data-testid="stBaseButton-secondary"]{border:1px solid var(--mel-line-strong);background:var(--mel-paper);color:var(--mel-ink);font-weight:600;min-height:44px;padding:8px 16px;transition:background var(--mel-t-fast),border-color var(--mel-t-fast),color var(--mel-t-fast),transform var(--mel-t-fast)}
[data-testid="stBaseButton-secondary"]:hover{border-color:var(--mel-green);color:var(--mel-green-ink);background:var(--mel-green-soft)}
[data-testid="stBaseButton-secondary"]:active{transform:scale(.985)}
[data-testid="stBaseButton-primary"]{background:var(--mel-green);border-color:var(--mel-green);font-weight:600;min-height:44px;transition:background var(--mel-t-fast),transform var(--mel-t-fast)}
[data-testid="stBaseButton-primary"]:hover{background:var(--mel-green-ink);border-color:var(--mel-green-ink)}
[data-testid="stBaseButton-primary"]:active{transform:scale(.985)}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"]{min-height:40px}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] span{font-size:15px;font-weight:500}
[data-testid="stAppViewContainer"] button:focus-visible,[data-testid="stAppViewContainer"] [role="tab"]:focus-visible,[data-testid="stAppViewContainer"] summary:focus-visible{outline:3px solid var(--mel-marigold);outline-offset:2px;box-shadow:none}

/* icon-only Restart in the Survey Studio settings bar: st.button(key="studio_restart", icon=...). The label
   "Restart survey" stays in the accessibility tree but is clipped off screen; the Material icon is what shows. */
.st-key-studio_restart button{width:40px;min-width:40px;min-height:40px;padding:0;justify-content:center;gap:0}
.st-key-studio_restart button [data-testid="stMarkdownContainer"]{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.st-key-studio_restart button [data-testid="stIconMaterial"],.st-key-studio_restart button span[class*="material-symbols"]{font-size:22px;margin:0}

/* ---- mel-* surfaces (same class names as before, larger scale) ------------ */
.mel-card{background:var(--mel-paper);border:1px solid var(--mel-line);border-radius:var(--mel-r-card);padding:18px 20px;margin-bottom:var(--mel-gap);color:var(--mel-ink);font-size:16px;line-height:1.5;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
.mel-card b{font-weight:600}
.mel-k{font-size:var(--mel-fs-label);font-weight:600;letter-spacing:0;text-transform:none;color:var(--mel-muted);margin-bottom:4px}
.mel-badge{display:inline-block;border-radius:var(--mel-r-pill);font-size:13px;font-weight:600;line-height:1.3;padding:4px 11px;margin-right:4px;background:var(--mel-green-soft);color:var(--mel-green-ink);vertical-align:middle}
.mel-badge.amber{background:var(--mel-marigold-soft);color:var(--mel-marigold-ink)}
.mel-badge.red{background:var(--mel-clay-soft);color:var(--mel-clay)}
.mel-badge.slate{background:var(--mel-slate-soft);color:var(--mel-slate)}
.mel-rule{display:grid;grid-template-columns:40px 180px 1fr 44px;gap:12px;align-items:center;font-size:15px;margin:9px 0}
.mel-id{font-family:var(--mel-mono);font-size:13px;background:var(--mel-sand);border-radius:6px;padding:2px 7px;color:var(--mel-ink-soft)}
.mel-track{height:10px;border-radius:10px;background:var(--mel-sand);overflow:hidden}
.mel-fill{height:100%;border-radius:10px;background:var(--mel-line-strong);transition:width var(--mel-t-base) var(--mel-ease)}
.mel-fill.green{background:var(--mel-green)}.mel-fill.amber{background:var(--mel-marigold)}.mel-fill.red{background:var(--mel-clay)}

/* the one strong surface: the selected insight */
.mel-insight{background:var(--mel-green-deep);color:#F2F8F2;border-radius:var(--mel-r-card);padding:24px 24px 20px;margin-bottom:var(--mel-gap);font-size:17px;line-height:1.6;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
.mel-insight>div:first-child,.mel-insight .mel-eyebrow{font-size:13px!important;letter-spacing:0!important;text-transform:none!important;color:var(--mel-green-pale)!important;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.mel-insight h3{color:#fff;margin:10px 0 18px;font-size:24px;line-height:1.3;font-weight:600;letter-spacing:0}
.mel-insight .f{border-top:1px solid rgba(255,255,255,.18);padding:14px 0;font-size:18px;line-height:1.6}
.mel-insight .f span{display:block;color:var(--mel-green-pale);text-transform:none;letter-spacing:0;font-size:13px;font-weight:600;margin-bottom:4px}
.mel-meta{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px;border-top:1px solid rgba(255,255,255,.18);padding-top:14px;font-size:15px}
.mel-meta span{display:block;color:var(--mel-green-pale);text-transform:none;letter-spacing:0;font-size:13px;font-weight:600}
.mel-why{border-top:1px solid rgba(255,255,255,.18);margin-top:16px;padding-top:14px;color:var(--mel-marigold-pale);font-size:15px;font-weight:600}
.mel-why p{color:#DCEBDD;margin:6px 0 0;font-size:16px;font-weight:400;line-height:1.55}

/* guard checks */
.mel-chk{font-size:14px;color:var(--mel-green-ink);margin-right:14px}.mel-chk.bad{color:var(--mel-clay)}

/* scheduler hand-off strip */
.mel-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:18px 24px;align-items:start;font-size:15px}
.mel-strip b{font-size:16px!important;font-weight:600}
.mel-tl{position:relative;height:10px;background:var(--mel-sand);border-radius:6px;margin:10px 0 6px}
.mel-tl i{position:absolute;top:0;height:10px;border-radius:6px}.mel-tl i.w{background:var(--mel-green)}.mel-tl i.x{background:var(--mel-marigold)}
.mel-tlab{display:flex;justify-content:space-between;gap:8px 12px;flex-wrap:wrap;color:var(--mel-muted);font-size:13px;white-space:nowrap}
.mel-ch b{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:6px;background:var(--mel-green-soft);color:var(--mel-green-ink);font-size:13px;margin-right:4px}
.mel-ch small{color:var(--mel-muted);margin:0 6px;font-size:13px}

/* scheduling plan (right column): one card, sections separated by a hairline */
.mel-plan{background:var(--mel-paper);border:1px solid var(--mel-line);border-radius:var(--mel-r-card);padding:18px 20px;margin-bottom:var(--mel-gap);color:var(--mel-ink);font-size:16px;line-height:1.5;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
.mel-plan>b,.mel-plan>div:first-child b{font-size:17px}
.mel-sub{padding:14px 0 0;margin-top:14px;border-top:1px solid var(--mel-line)}
.mel-plan>.mel-sub:first-child,.mel-plan>div:first-child+.mel-sub,.mel-sub.first{border-top:0;margin-top:10px;padding-top:0}
.mel-sub .mel-k{margin-bottom:5px}
.mel-sub b{font-size:16px;font-weight:600}
.mel-sub .mel-note{margin-top:4px}
.mel-sub .mel-tl{margin-top:8px}
.mel-sub .mel-badge{margin-top:2px}
.mel-strip>div{min-width:0}
.mel-strip .mel-note{margin-top:4px}

/* the band at the top of the insight card: eyebrow + severity on the left, ids on the right */
.mel-insight-top{display:flex;justify-content:space-between;align-items:center;gap:8px 12px;flex-wrap:wrap;margin-bottom:12px;font-size:13px;font-weight:600;color:var(--mel-green-pale)}
.mel-insight-top .mel-id{background:rgba(255,255,255,.14);color:#F2F8F2}
.mel-insight .mel-insight-top{padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,.18)}

/* ---- motion -------------------------------------------------------------- */
@keyframes mel-rise{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){
  .mel-card,.mel-insight,.mel-plan,.mel-report,[data-testid="stTabPanel"]>div{animation:none}
  .mel-fill,[data-testid="stTab"],[data-testid="stBaseButton-secondary"],[data-testid="stBaseButton-primary"]{transition:none}
  [data-testid="stBaseButton-secondary"]:active,[data-testid="stBaseButton-primary"]:active{transform:none}
}

/* ---- narrow screens ------------------------------------------------------ */
@media (max-width:760px){
  [data-testid="stMainBlockContainer"]{padding-left:16px;padding-right:16px}
  [data-testid="stTab"]{padding:8px 10px}
  [data-testid="stTab"] p{font-size:15px}
  .mel-rule{grid-template-columns:40px 1fr 44px}.mel-rule .mel-track{grid-column:1/-1}
  .mel-insight{padding:18px}.mel-insight .f{font-size:17px}.mel-insight h3{font-size:22px}
  .mel-strip{grid-template-columns:1fr;gap:14px}
  .mel-plan{padding:16px}
  .mel-report .mel-sum{text-align:left;max-width:none}
  .mel-mast .mel-brand{font-size:22px}
}
"""


def apply_theme() -> None:
    """Inject the global theme CSS. Call once near the top of the app, after `st.set_page_config`."""
    st.markdown("<style>" + CSS + "</style>", unsafe_allow_html=True)
