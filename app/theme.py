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
import base64
from pathlib import Path
from urllib.parse import quote

import streamlit as st

# Hex values for Python callers (chart colours, st.bar_chart(color=...)). Same values as the CSS variables.
# FarmerChat's own palette (farmer.chat, 4 Nov): bright green for accents, deep green for actions, forest for
# the strong surfaces, mint sections, zinc grays, a yellow highlight. The variable names below are unchanged,
# so every mel-* surface in the app follows the retheme without edits.
PALETTE = {  # farmer.chat's own tokens (--p-green, --p-green-deep, --p-forest*, --p-ink, --p-body, --p-line, --p-mist, --p-sun, --p-red)
    "ivory": "#F1F7F2", "sand": "#E6EFE8", "paper": "#FFFFFF", "line": "#E4E4E7",
    "ink": "#09090B", "muted": "#52525C",
    "green": "#00832B", "green_deep": "#0B4524", "green_ink": "#032E15", "green_soft": "#E3F6E8",
    "marigold": "#F9FF47", "marigold_ink": "#6B6F00", "marigold_soft": "#FBFFD6",
    "clay": "#E5533D", "clay_soft": "#FCE7E3", "slate": "#52525C", "bright": "#00C950",
}
# FarmerChat's actual mark: the twelve leaf paths of the header logo on farmer.chat (viewBox 0 0 130 130).
_PETALS = (
    "M32.559 0C50.5408 0 65.118 14.5904 65.118 32.5885C47.1361 32.5885 32.559 17.9981 32.559 0Z",
    "M97.559 0C79.5771 0 65 14.5904 65 32.5885C82.9818 32.5885 97.559 17.9981 97.559 0Z",
    "M32.6769 65.059C14.6951 65.059 0.117981 50.4686 0.117981 32.4705C18.0998 32.4705 32.6769 47.0609 32.6769 65.059Z",
    "M65.118 32.4705C47.1361 32.4705 32.559 47.0609 32.559 65.059C50.5408 65.059 65.118 50.4686 65.118 32.4705Z",
    "M65 32.4704C82.9818 32.4704 97.559 47.0608 97.559 65.0589C79.5771 65.0589 65 50.4686 65 32.4704Z",
    "M97.441 65.059C115.423 65.059 130 50.4686 130 32.4705C112.018 32.4705 97.441 47.0609 97.441 65.059Z",
    "M32.559 64.9409C14.5772 64.9409 0 79.5312 0 97.5294C17.9818 97.5294 32.559 82.939 32.559 64.9409Z",
    "M32.559 64.9409C50.5408 64.9409 65.118 79.5312 65.118 97.5294C47.1361 97.5294 32.559 82.939 32.559 64.9409Z",
    "M97.559 64.941C79.5771 64.941 65 79.5314 65 97.5295C82.9818 97.5295 97.559 82.9391 97.559 64.941Z",
    "M97.441 64.9409C115.423 64.9409 130 79.5312 130 97.5294C112.018 97.5294 97.441 82.939 97.441 64.9409Z",
    "M65.118 97.4115C47.1361 97.4115 32.559 112.002 32.559 130C50.5408 130 65.118 115.41 65.118 97.4115Z",
    "M65 97.4113C82.9818 97.4113 97.559 112.002 97.559 130C79.5771 130 65 115.409 65 97.4113Z",
)
_PATHS = "".join(f'<path d="{d}"/>' for d in _PETALS)
# Inline, so it scales with the font size and takes the current text colour.
MARK = f'<svg class="mel-mark" viewBox="0 0 130 130" width="1em" height="1em" fill="currentColor" aria-hidden="true">{_PATHS}</svg>'
# The same mark in FarmerChat green, as a CSS image (the section-heading bullet).
_MARK_URI = "data:image/svg+xml," + quote(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 130 130" fill="#00C950">{_PATHS}</svg>')
# Fasal Pulse's icon (sprout and pulse line), cropped from the team logo posted in the team Discord on 3 Nov.
FP_ICON = "data:image/png;base64," + base64.b64encode((Path(__file__).parent / "assets" / "fasal-pulse-icon.png").read_bytes()).decode()
# The co-brand lockup used in the hero and the footer: FarmerChat × Fasal Pulse.
LOCKUP = (f'<span class="mel-lockup">{MARK}<b>FarmerChat</b><span class="mel-x">×</span>'
          f'<img class="mel-fp" src="{FP_ICON}" alt=""><b>Fasal Pulse</b></span>')

# Fasal Pulse's mascot, drawn from the user's Survey demo sketch (round face, two oval eyes) plus a sprout:
# a glossy mint seedling on the agent's panel. It looks around while the agent's lines appear, then smiles
# (`--t` on the parent sets when; see .mel-bot in CSS). Inline SVG, no image file.
MASCOT = (
    '<svg class="mel-bot" viewBox="0 0 120 120" width="78" height="78" aria-hidden="true">'
    '<defs><radialGradient id="melBotBody" cx="36%" cy="30%" r="78%">'
    '<stop offset="0" stop-color="#F6FFF8"/><stop offset=".55" stop-color="#A9EDBE"/>'
    '<stop offset="1" stop-color="#2DBE60"/></radialGradient></defs>'
    '<ellipse class="sh" cx="60" cy="113" rx="30" ry="4.5"/>'
    '<g class="b">'
    '<path d="M60 30V15" stroke="#00C950" stroke-width="3.5" stroke-linecap="round" fill="none"/>'
    '<path d="M60 19C52 8 40 9 37 15C45 21 53 22 60 19Z" fill="#00C950"/>'
    '<path d="M60 16C67 5 80 6 83 12C76 18 67 19 60 16Z" fill="#2EE36C"/>'
    '<path d="M60 27C88 27 104 47 104 71C104 95 86 109 60 109C34 109 16 95 16 71C16 47 32 27 60 27Z" fill="url(#melBotBody)"/>'
    '<ellipse cx="42" cy="47" rx="11" ry="6" fill="#fff" opacity=".75" transform="rotate(-28 42 47)"/>'
    '<g class="eyes"><ellipse class="e" cx="47" cy="69" rx="5.5" ry="8.5" fill="#0B4524"/>'
    '<ellipse class="e" cx="73" cy="69" rx="5.5" ry="8.5" fill="#0B4524"/>'
    '<circle cx="49" cy="65.5" r="1.8" fill="#fff"/><circle cx="75" cy="65.5" r="1.8" fill="#fff"/></g>'
    '<ellipse cx="37" cy="83" rx="5" ry="3" fill="#FF8F7A" opacity=".5"/>'
    '<ellipse cx="83" cy="83" rx="5" ry="3" fill="#FF8F7A" opacity=".5"/>'
    '<circle class="think" cx="60" cy="87" r="2.6" fill="#0B4524"/>'
    '<path class="smile" d="M53 85Q60 91 67 85" stroke="#0B4524" stroke-width="3" stroke-linecap="round" fill="none"/>'
    '</g></svg>')

CSS = """
:root{
  --mel-ivory:#F1F7F2;--mel-sand:#E6EFE8;--mel-paper:#FFFFFF;--mel-line:#E4E4E7;--mel-line-strong:#D4D4D8;
  --mel-ink:#09090B;--mel-ink-soft:#3F3F46;--mel-muted:#52525C;--mel-faint:#9F9FA9;
  --mel-green:#00832B;--mel-green-lift:#0B8F42;--mel-green-deep:#0B4524;--mel-green-ink:#032E15;--mel-forest-2:#08361B;--mel-green-soft:#E3F6E8;--mel-green-pale:#2EE36C;--mel-bright:#00C950;
  --mel-marigold:#F9FF47;--mel-marigold-pale:#F9FF47;--mel-marigold-soft:#FBFFD6;--mel-marigold-ink:#6B6F00;
  --mel-clay:#E5533D;--mel-clay-soft:#FCE7E3;--mel-slate:#52525C;--mel-slate-soft:#F4F4F5;
  --mel-wa:#075E54;--mel-wa-bar:#008069;--mel-wa-bg:#ECE5DD;--mel-wa-in:#FFFFFF;--mel-wa-out:#DCF8C6;--mel-wa-link:#027EB5;
  --mel-tg:#2AABEE;--mel-tg-bar:#517DA2;--mel-tg-bg:#E6EBEE;--mel-tg-in:#FFFFFF;--mel-tg-out:#EFFDDE;--mel-tg-link:#168ACD;
  --mel-font:"Inter","Noto Sans Devanagari","Kohinoor Devanagari","Devanagari Sangam MN","Nirmala UI","Noto Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mel-mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --mel-fs-body:17px;--mel-fs-small:14px;--mel-fs-label:13px;--mel-fs-lead:19px;
  --mel-lh:1.55;--mel-lh-hi:1.65;
  --mel-r-card:24px;--mel-r-ctl:16px;--mel-r-pill:999px;
  --mel-t-fast:140ms;--mel-t-base:220ms;--mel-ease:cubic-bezier(.2,.7,.2,1);
  --mel-gap:12px;
}

/* ---- page ---------------------------------------------------------------- */
[data-testid="stAppViewContainer"]{background:var(--mel-ivory);color:var(--mel-ink)}
[data-testid="stHeader"]{background:var(--mel-ivory)}
[data-testid="stDecoration"]{display:none}
[data-testid="stAppDeployButton"]{display:none}  /* deployment-only chrome; the menu stays for settings and rerun */
[data-testid="stMainBlockContainer"]{max-width:1180px;padding-left:max(16px,2.5vw);padding-right:max(16px,2.5vw)}
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{line-height:var(--mel-lh)}
[data-testid="stMarkdownContainer"] p:lang(hi){line-height:var(--mel-lh-hi)}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{font-size:var(--mel-fs-small);color:var(--mel-muted);line-height:1.5}
[data-testid="stHeading"] h1,[data-testid="stHeading"] h2,[data-testid="stHeading"] h3{letter-spacing:-.02em;color:var(--mel-ink);font-weight:700}
[data-testid="stHeading"] h2{margin-top:.8rem;font-size:1.7rem}
[data-testid="stHeading"] h2::before{content:"";display:inline-block;width:.78em;height:.78em;margin-right:12px;vertical-align:-.04em;background:url("__MARK_URI__") center/contain no-repeat}
[data-testid="stWidgetLabel"] p{font-size:15px;font-weight:500;color:var(--mel-ink-soft)}
a{color:var(--mel-green)}
.mel-lead{font-size:var(--mel-fs-lead);line-height:1.5;color:var(--mel-ink-soft);margin:0 0 12px}
.mel-note{font-size:var(--mel-fs-small);color:var(--mel-muted);line-height:1.5}
.mel-hi{line-height:var(--mel-lh-hi)}

/* ---- masthead (FarmerChat's green band and ✻ wordmark), report title line, section labels ---------- */
/* The hero, as on farmer.chat: bright green fading to deep green, white light rays from the top, the mark
   and wordmark top-left, a centred white headline, the nav inside the band. */
.mel-mast{position:relative;overflow:hidden;display:flex;flex-direction:column;gap:6px;padding:12px 26px 6px;margin-bottom:0;
  border-radius:var(--mel-r-card) var(--mel-r-card) 0 0;color:#fff;
  background:radial-gradient(ellipse 70% 90% at 50% -30%,rgba(255,255,255,.28),rgba(255,255,255,0) 60%),linear-gradient(180deg,#00C950 0%,#00A843 50%,#00832B 100%)}
.mel-mast::before{content:"";position:absolute;inset:-40% -10% auto;height:170%;pointer-events:none;
  background:conic-gradient(from 180deg at 50% 0%,rgba(255,255,255,0) 0 16%,rgba(255,255,255,.10) 18%,rgba(255,255,255,0) 21%,rgba(255,255,255,0) 30%,rgba(255,255,255,.12) 33%,rgba(255,255,255,0) 36%,rgba(255,255,255,0) 64%,rgba(255,255,255,.12) 67%,rgba(255,255,255,0) 70%,rgba(255,255,255,0) 79%,rgba(255,255,255,.10) 82%,rgba(255,255,255,0) 84%);
  animation:mel-rays 9s ease-in-out infinite alternate}
@keyframes mel-rays{from{transform:rotate(-2deg)}to{transform:rotate(2deg)}}
.mel-mast>*{position:relative}
.mel-mast .mel-brand{display:flex;align-items:center;gap:9px;font-size:19px;font-weight:700;color:#fff;line-height:1.1;letter-spacing:-.01em}
/* co-brand lockup: FarmerChat's mark and wordmark, a light ×, Fasal Pulse's icon on a white disc and its name */
.mel-lockup{display:inline-flex;align-items:center;flex-wrap:wrap;gap:9px;font-size:19px;letter-spacing:-.01em}
.mel-lockup b{font-weight:700}
.mel-lockup .mel-mark{font-size:24px;line-height:1;transition:transform .3s var(--mel-ease)}
.mel-lockup:hover .mel-mark{transform:rotate(90deg)}  /* as on farmer.chat */
.mel-lockup .mel-x{font-weight:400;opacity:.7;margin:0 4px}
.mel-lockup .mel-fp{width:30px;height:30px;border-radius:50%;background:#fff;padding:2px;box-shadow:0 1px 4px rgba(3,46,21,.25)}
.mel-mast .mel-head{text-align:center;padding:4px 0 2px}
.mel-mast .mel-title{font-size:30px;font-weight:700;line-height:1.02;letter-spacing:-.03em;color:#fff;margin:0;animation:mel-rise .5s var(--mel-ease) both}
.mel-mast .mel-tag{font-size:17px;color:rgba(255,255,255,.9);margin:8px 0 6px}
@media (prefers-reduced-motion:reduce){.mel-mast::before{animation:none}}
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
/* the nav lives inside the hero band: the tab list continues the green and closes the band's bottom corners */
[data-testid="stTabs"]{margin-top:-1rem}
[data-testid="stTabs"] [role="tablist"]{gap:6px;border-bottom:0;padding:6px 18px 18px;justify-content:center;background:#00832B;border-radius:0 0 var(--mel-r-card) var(--mel-r-card)}
[data-testid="stTab"]{padding:9px 18px;border-radius:var(--mel-r-pill);color:rgba(255,255,255,.88);transition:color var(--mel-t-fast),background var(--mel-t-fast)}
[data-testid="stTab"] p{font-size:15.5px;font-weight:600;color:inherit}
[data-testid="stTab"]:hover{color:#fff;background:rgba(255,255,255,.16)}
[data-testid="stTab"][aria-selected="true"]{color:var(--mel-green-ink);background:#fff}
[data-testid="stTab"][aria-selected="true"] p{font-weight:700;color:var(--mel-green-ink)}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],[data-testid="stTabs"] [data-baseweb="tab-border"]{display:none}
[data-testid="stTabPanel"]{padding-top:26px}
[data-testid="stTabPanel"]{padding-top:18px}
[data-testid="stTabPanel"]>div{animation:mel-rise var(--mel-t-base) var(--mel-ease) both}

/* ---- metrics, expanders, alerts ------------------------------------------ */
[data-testid="stMetric"]{background:var(--mel-paper);border:0;border-radius:var(--mel-r-card);padding:16px 18px 14px;min-height:8rem;box-shadow:0 4px 13px rgba(0,130,54,.08)}
[data-testid="stMetricLabel"] p{font-size:var(--mel-fs-small);color:var(--mel-muted);font-weight:500}
[data-testid="stMetricValue"]{color:var(--mel-ink)}
[data-testid="stMetricDelta"]{font-size:var(--mel-fs-label);color:var(--mel-muted)}
[data-testid="stExpander"] details{background:var(--mel-paper);border-color:var(--mel-line);border-radius:var(--mel-r-card)}
[data-testid="stExpander"] summary{padding:12px 16px}
[data-testid="stExpander"] summary:hover{color:var(--mel-green-ink)}
[data-testid="stAlert"]{border-radius:var(--mel-r-card)}

/* ---- controls (kept light on purpose; see selector policy above) ---------- */
[data-testid="stBaseButton-secondary"]{border:1.5px solid var(--mel-bright);border-radius:var(--mel-r-pill);background:var(--mel-paper);color:var(--mel-green-ink);font-weight:600;min-height:44px;padding:8px 18px;transition:background var(--mel-t-fast),border-color var(--mel-t-fast),color var(--mel-t-fast),transform var(--mel-t-fast)}
[data-testid="stBaseButton-secondary"]:hover{border-color:var(--mel-green);color:var(--mel-green-ink);background:var(--mel-green-soft)}
[data-testid="stBaseButton-secondary"]:active{transform:scale(.985)}
[data-testid="stBaseButton-primary"]{background:var(--mel-green-deep);border:1.5px solid var(--mel-marigold);border-radius:var(--mel-r-pill);color:#fff;font-weight:600;min-height:44px;padding:8px 20px;box-shadow:0 4px 13px rgba(0,130,54,.18);transition:background var(--mel-t-fast),transform var(--mel-t-fast)}
[data-testid="stBaseButton-primary"]:hover{background:var(--mel-green-ink);border-color:var(--mel-marigold)}
[data-testid="stBaseButton-primary"]:active{transform:scale(.985)}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"]{min-height:40px}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] span{font-size:15px;font-weight:500}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"]{background:var(--mel-green-soft);color:var(--mel-green-ink)}
[data-testid="stAppViewContainer"] button:focus-visible,[data-testid="stAppViewContainer"] [role="tab"]:focus-visible,[data-testid="stAppViewContainer"] summary:focus-visible{outline:3px solid var(--mel-bright);outline-offset:2px;box-shadow:none}

/* icon-only Restart in the Survey Studio settings bar: st.button(key="studio_restart", icon=...). The label
   "Restart survey" stays in the accessibility tree but is clipped off screen; the Material icon is what shows.
   The "What if…" popover (key="studio_whatif") is drawn the same way, its chevron hidden too. */
.st-key-studio_whatif button div[aria-hidden="true"]{display:none}
.st-key-studio_restart button,.st-key-studio_whatif button,.st-key-tts_toggle button{width:40px;min-width:40px;min-height:40px;padding:0;justify-content:center;gap:0}
.st-key-studio_restart button [data-testid="stMarkdownContainer"],.st-key-studio_whatif button [data-testid="stMarkdownContainer"],.st-key-tts_pill button [data-testid="stMarkdownContainer"]{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.st-key-studio_restart button [data-testid="stIconMaterial"],.st-key-studio_restart button span[class*="material-symbols"],.st-key-studio_whatif button [data-testid="stIconMaterial"]{font-size:22px;margin:0}
/* Read-aloud speaker beside Restart (sound_button): speaker tts_toggle + volume chevron tts_pop joined as one pill. */
.st-key-tts_toggle button{border-top-right-radius:0;border-bottom-right-radius:0}
.st-key-tts_pop button{min-height:40px;padding:0 8px;gap:0;margin-left:-1px;border-top-left-radius:0;border-bottom-left-radius:0}
.st-key-tts_toggle button [data-testid="stIconMaterial"]{font-size:22px;margin:0}

/* ---- mel-* surfaces (same class names as before, larger scale) ------------ */
.mel-card{background:var(--mel-paper);border:0;box-shadow:0 4px 13px rgba(0,130,54,.08);border-radius:var(--mel-r-card);padding:20px 22px;margin-bottom:var(--mel-gap);color:var(--mel-ink);font-size:16px;line-height:1.5;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
.mel-card b{font-weight:600}
.mel-k{font-size:var(--mel-fs-label);font-weight:600;letter-spacing:0;text-transform:none;color:var(--mel-muted);margin-bottom:4px}
.mel-badge{display:inline-block;border-radius:var(--mel-r-pill);font-size:13px;font-weight:600;line-height:1.3;padding:4px 11px;margin-right:4px;background:var(--mel-green-soft);color:var(--mel-green-ink);vertical-align:middle}
.mel-badge.amber{background:var(--mel-marigold-soft);color:var(--mel-marigold-ink)}
.mel-badge.red{background:var(--mel-clay-soft);color:var(--mel-clay)}
.mel-badge.slate{background:var(--mel-slate-soft);color:var(--mel-slate)}
.mel-rule{display:grid;grid-template-columns:40px 180px 1fr 44px;gap:12px;align-items:center;font-size:15px;margin:9px 0}
.mel-id{font-family:var(--mel-font);font-size:13px;font-weight:700;background:var(--mel-bright);border-radius:var(--mel-r-pill);padding:4px 9px;color:#fff;display:inline-block;min-width:32px;text-align:center}
.mel-track{height:10px;border-radius:10px;background:var(--mel-sand);overflow:hidden}
.mel-fill{height:100%;border-radius:10px;background:var(--mel-green);transition:width var(--mel-t-base) var(--mel-ease)}  /* no-survey rules: FarmerChat deep green, never gray */
.mel-fill.green{background:var(--mel-bright)}.mel-fill.amber{background:var(--mel-marigold)}.mel-fill.red{background:var(--mel-clay)}

/* the one strong surface: the selected insight, in FarmerChat's forest green (its app header colours) */
.mel-insight{background:linear-gradient(160deg,var(--mel-forest-2),var(--mel-green-ink));color:#F2F8F2;border-radius:var(--mel-r-card);padding:24px 24px 20px;margin-bottom:var(--mel-gap);font-size:17px;line-height:1.6;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
.mel-insight>div:first-child,.mel-insight .mel-eyebrow{font-size:13px!important;letter-spacing:0!important;text-transform:none!important;color:var(--mel-green-pale)!important;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.mel-insight h3{color:#fff;margin:10px 0 18px;font-size:24px;line-height:1.3;font-weight:600;letter-spacing:0}
.mel-insight .f{border-top:1px solid rgba(255,255,255,.18);padding:14px 0;font-size:18px;line-height:1.6}
.mel-insight .f span{display:block;color:var(--mel-green-pale);text-transform:none;letter-spacing:0;font-size:13px;font-weight:600;margin-bottom:4px}
.mel-why{border-top:1px solid rgba(255,255,255,.18);margin-top:16px;padding-top:14px;color:var(--mel-marigold-pale);font-size:15px;font-weight:600}
.mel-why p{color:#DCEBDD;margin:6px 0 0;font-size:16px;font-weight:400;line-height:1.55}

/* guard checks */
.mel-chk{font-size:14px;color:var(--mel-green-ink);margin-right:14px}.mel-chk.bad{color:var(--mel-clay)}

/* scheduler hand-off strip */
.mel-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:18px 24px;align-items:start;font-size:15px}
.mel-strip b{font-size:16px!important;font-weight:600}
.mel-route{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:4px}
.mel-route span{background:var(--mel-green-soft);color:var(--mel-green-ink);border-radius:var(--mel-r-pill);padding:3px 10px;font-size:14px;font-weight:600}
.mel-route small{color:var(--mel-muted);font-size:13px}

/* scheduling plan (right column): one card, sections separated by a hairline */
.mel-plan{background:var(--mel-paper);border:0;box-shadow:0 4px 13px rgba(0,130,54,.08);border-radius:var(--mel-r-card);padding:20px 22px;margin-bottom:var(--mel-gap);color:var(--mel-ink);font-size:16px;line-height:1.5;animation:mel-rise var(--mel-t-base) var(--mel-ease) both}
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

/* ---- footer: farmer.chat's forest band with the mark ------------------------ */
.mel-foot{display:flex;align-items:center;justify-content:space-between;gap:8px 20px;flex-wrap:wrap;margin-top:40px;padding:20px 26px;
  border-radius:var(--mel-r-card);background:var(--mel-green-ink);color:rgba(255,255,255,.9);font-size:14px}
.mel-foot .mel-lockup{color:#fff;font-size:16px}.mel-foot .mel-lockup .mel-mark{font-size:20px}.mel-foot .mel-lockup .mel-fp{width:26px;height:26px}

/* ---- Survey demo: the agent's view, styled like a Claude Code session (steps appear one by one; nothing
   replays while the farmer taps). Titles are larger and bolder than the text, as William asked. ---------- */
@property --mel-s{syntax:"<integer>";inherits:false;initial-value:0}
@property --mel-k{syntax:"<integer>";inherits:false;initial-value:0}
.mel-agent{background:#1A1A19;color:#C9C7BE;border-radius:16px;padding:16px 8px 12px 18px;font-family:var(--mel-mono);font-size:12.5px;line-height:1.55;
  height:700px;display:flex;flex-direction:column}
/* one fixed height, like a real terminal: column-reverse keeps the log pinned to its newest line while steps stream in;
   the auto margin keeps a short log at the top (and, unlike justify-content, never makes overflow unreachable) */
.mel-agent .scroll{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column-reverse;padding-right:10px;
  scrollbar-width:thin;scrollbar-color:#4A4944 transparent}
.mel-agent .scroll:focus-visible{outline:2px solid #4EBA65;outline-offset:2px;border-radius:6px}
.mel-agent .log{margin-bottom:auto}
.mel-agent .foot{flex:none}
.mel-agent .step{overflow:hidden;max-height:0;opacity:0;animation:mel-grow .5s var(--mel-ease) forwards;animation-delay:calc(var(--i) * .6s + .2s)}
.mel-agent .call{color:#F2F1EC;font-size:13px}
.mel-agent .call i{font-style:normal;color:#4EBA65;margin-right:8px}
.mel-agent .call b{font-weight:700}
.mel-agent .call em{font-style:normal;color:#9A9890}
.mel-agent .res{display:grid;grid-template-columns:24px 1fr;margin:3px 0 12px 4px}
.mel-agent .elbow{color:#6E6C66}
.mel-agent .kv{display:grid;grid-template-columns:104px 1fr;gap:4px 12px;margin:0}
.mel-agent .kv dt{font-size:14px;font-weight:700;color:#F2F1EC;line-height:1.4}
.mel-agent .kv dd{margin:0;font-size:12.5px;color:#B9B7AE;padding-top:1px}
.mel-agent .kv dd b{color:#F2F1EC;font-weight:600}
.mel-agent .kv small{color:#8A887F;font-size:11.5px}
.mel-agent .sev{font-weight:700}.mel-agent .sev.critical,.mel-agent .sev.high{color:#FF8A73}.mel-agent .sev.medium{color:#F2C14E}.mel-agent .sev.low{color:#9ED9A8}
.mel-agent .pass{color:#4EBA65;font-weight:700}.mel-agent .fail{color:#FF8A73;font-weight:700}
.mel-agent .status{display:grid;grid-template-columns:18px 1fr;align-items:baseline;color:#D97757;font-size:13px;margin-top:2px}
.mel-agent .status .run,.mel-agent .status .fin{grid-area:1/2}
.mel-agent .status em{font-style:normal;color:#8A887F}
.mel-agent .status i{font-style:normal}
.mel-agent .run{animation:mel-out .2s ease var(--t) forwards}
.mel-agent .fin{opacity:0;color:#9A9890;animation:mel-in .2s ease var(--t) forwards}
.mel-agent .spin::before{content:"✻";display:inline-block;animation:mel-spin .8s steps(1) var(--spins)}
.mel-agent .sec{animation:mel-sec var(--t) linear forwards;counter-reset:s var(--mel-s)}
.mel-agent .sec::after{content:counter(s)}
.mel-agent .tok{animation:mel-tok var(--t) ease-out forwards;counter-reset:k var(--mel-k)}
.mel-agent .tok::after{content:counter(k)}
.mel-agent .foot{display:flex;align-items:flex-end;gap:10px;margin-top:10px;font-family:var(--mel-font)}
.mel-agent .bubble{background:#fff;color:var(--mel-ink);border-radius:16px 16px 16px 4px;padding:8px 13px;font-size:14px;font-weight:600;
  margin-bottom:22px;opacity:0;animation:mel-in .35s ease var(--t) forwards}
@keyframes mel-grow{from{max-height:0;opacity:0}to{max-height:640px;opacity:1}}
@keyframes mel-spin{0%{content:"✢"}20%{content:"✳"}40%{content:"✶"}60%{content:"✻"}80%{content:"✽"}}
@keyframes mel-sec{to{--mel-s:var(--secs)}}
@keyframes mel-tok{to{--mel-k:var(--toks)}}
.mel-bot{display:block;overflow:visible;flex:none}
.mel-bot .sh{fill:#000;opacity:.25}
.mel-bot .b{animation:mel-bob 2.8s ease-in-out infinite}
.mel-bot .eyes{animation:mel-look 1s ease-in-out var(--m) both}
.mel-bot .e{transform-box:fill-box;transform-origin:center;animation:mel-blink 4.5s ease-in-out 1.2s infinite}
.mel-bot .smile{opacity:0;animation:mel-in .3s ease var(--t) forwards}
.mel-bot .think{animation:mel-out .2s ease var(--t) forwards}
@keyframes mel-in{to{opacity:1}}
@keyframes mel-out{to{opacity:0}}
@keyframes mel-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
@keyframes mel-look{0%,100%{transform:none}25%{transform:translateX(-3px)}75%{transform:translateX(3px)}}
@keyframes mel-blink{0%,93%,100%{transform:scaleY(1)}96%{transform:scaleY(.12)}}
.st-key-agent_head .mel-sec,.st-key-farmer_head .mel-sec{margin:0}
/* both view headers one height, so the agent's panel and the phone start level; the farmer's header spans the
   phone (378 px, centred like it), so its switch and Restart end at the phone's right edge */
.st-key-agent_head,.st-key-farmer_head{min-height:44px}
.st-key-farmer_head{width:100%;max-width:378px;margin-left:auto;margin-right:auto}
@media (min-width:900px){.mel-agent{min-height:700px;display:flex;flex-direction:column}.mel-agent .foot{margin-top:auto}}
.mel-lang{font-size:14px;font-weight:600;color:var(--mel-muted)}
.mel-empty{background:var(--mel-paper);border:1px dashed var(--mel-line-strong);border-radius:var(--mel-r-card);padding:48px 24px;text-align:center;color:var(--mel-muted)}
.mel-empty b{display:block;color:var(--mel-ink);font-size:18px;margin-bottom:6px}

/* ---- Dashboard: headline, donuts, weekly line, rule table ----------------- */
.mel-lede h2{font-size:32px;line-height:1.12;letter-spacing:-.02em;font-weight:700;color:var(--mel-ink);margin:0 0 12px;padding:0}
.mel-lede h2 .num{color:var(--mel-green)}
.mel-lede p{font-size:17px;line-height:1.55;color:var(--mel-ink-soft);margin:0 0 14px}
.mel-lede .stats{display:flex;flex-wrap:wrap;gap:8px}
.mel-pill{display:inline-block;border-radius:var(--mel-r-pill);background:var(--mel-green-soft);color:var(--mel-green-ink);font-size:13px;font-weight:600;padding:4px 12px}
.mel-chart-h{font-size:15px;font-weight:600;color:var(--mel-ink);margin:0}
.mel-chart-h small{display:block;font-size:13px;font-weight:400;color:var(--mel-muted)}
.mel-chart-h.gap{margin-top:28px}
.mel-legend{display:grid;gap:4px;font-size:13px;color:var(--mel-ink);max-width:220px;margin:-6px auto 0}
.mel-legend span{display:flex;align-items:center;gap:7px}
.mel-legend i{width:9px;height:9px;border-radius:50%;flex:none}
.mel-legend b{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums}
.mel-wrap{overflow-x:auto;margin-top:10px}
.mel-rtab{width:100%;min-width:760px;border-collapse:separate;border-spacing:0;background:var(--mel-paper);border:1px solid var(--mel-line);border-radius:16px;overflow:hidden;font-size:14px}
.mel-rtab th,.mel-rtab td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--mel-line)}
.mel-rtab tr:last-child td{border-bottom:0}
.mel-rtab th{background:var(--mel-sand);font-weight:700;color:var(--mel-ink)}
.mel-rtab td.rh{color:var(--mel-muted);font-weight:600;white-space:nowrap}
.mel-rtab td b{font-size:18px;font-weight:700;color:var(--mel-ink)}
.mel-rtab .r8{background:var(--mel-green-soft)}
@media (prefers-reduced-motion:reduce){
  .mel-agent .step{animation:none;max-height:none;opacity:1}
  .mel-agent .spin::before,.mel-agent .sec,.mel-agent .tok,.mel-bot .b,.mel-bot .eyes,.mel-bot .e{animation:none}
  .mel-agent .run{animation:none;opacity:0}
  .mel-agent .fin,.mel-agent .bubble,.mel-bot .smile{animation:none;opacity:1}
  .mel-bot .think{animation:none;opacity:0}
}
@media (max-width:760px){.mel-agent .kv{grid-template-columns:1fr;gap:0}.mel-lede h2{font-size:26px}}

/* ---- Survey demo guided flow: the step strip, one lit view at a time, the phone before the survey is sent ---- */
.mel-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:2px 0 14px}
.mel-steps .s{display:flex;gap:10px;align-items:flex-start;padding:10px 14px;border-radius:14px;background:var(--mel-paper);
  border:1px solid var(--mel-line);transition:border-color .3s,box-shadow .3s,opacity .3s}
.mel-steps .s>b{flex:none;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-size:13px;
  background:var(--mel-slate-soft);color:var(--mel-muted)}
.mel-steps .s span{display:block;font-weight:600;font-size:14px;line-height:1.35;color:var(--mel-ink-soft);padding-top:3px}
.mel-steps .s small{display:block;font-size:12.5px;color:var(--mel-green);margin-top:2px}
.mel-steps .s.now{border-color:var(--mel-bright);box-shadow:0 0 0 3px rgba(0,201,80,.18)}
.mel-steps .s.now>b{background:var(--mel-bright);color:#fff}
.mel-steps .s.done>b{background:var(--mel-green-soft);color:var(--mel-green)}
.mel-steps .s.skip{opacity:.5}
.mel-dim,.mel-lit{display:none}
[data-testid="stPopoverBody"]:has(.st-key-f_dec){width:min(560px,92vw)}  /* the Browse search panel: room for 2 filters a row */
.st-key-flow_agent,.st-key-flow_phone{transition:opacity .45s var(--mel-ease),filter .45s var(--mel-ease)}
.st-key-flow_agent:has(.mel-dim),.st-key-flow_phone:has(.mel-dim){opacity:.38;filter:saturate(.35)}
.st-key-term_box{border-radius:16px;transition:box-shadow .3s}
.st-key-flow_agent:has(.mel-lit) .st-key-term_box{box-shadow:0 0 0 3px var(--mel-bright),0 14px 34px rgba(0,201,80,.22)}
.st-key-term_box .mel-agent{border-radius:16px 16px 0 0}
/* the terminal's input line: Streamlit's chat input, dressed as the bottom row of the same terminal */
.st-key-term_box [data-testid="stChatInput"]{background:#1A1A19;border-radius:0 0 16px 16px;padding:0 10px 10px;margin:0}
.st-key-term_box [data-testid="stChatInput"]>div{background:#242422;border:1px solid #3A3935;border-radius:10px;box-shadow:none}
.st-key-term_box [data-testid="stChatInput"]>div:focus-within{border-color:#4EBA65}
.st-key-term_box [data-testid="stChatInput"] textarea{font-family:var(--mel-mono);font-size:13px;color:#F2F1EC;caret-color:#4EBA65;background:transparent}
.st-key-term_box [data-testid="stChatInput"] textarea::placeholder{color:#8A887F;opacity:1}
.st-key-term_box [data-testid="stChatInput"] button{background:transparent;color:#4EBA65}
.mel-agent .ask .call{color:#F2F1EC}.mel-agent .ask .call i{color:#D97757}
.mel-phone-wait{width:350px;max-width:100%;height:700px;margin:0 auto;border-radius:46px;border:9px solid #1A1A19;background:linear-gradient(180deg,#F4F4F5,#E6EAE7);
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;text-align:center;padding:24px;color:var(--mel-muted)}
.mel-phone-wait b{color:var(--mel-ink-soft);font-size:15px}
.mel-phone-wait span{font-size:13.5px;max-width:24ch}
.mel-agent .step.done{animation:none;max-height:none;opacity:1}
.mel-agent .think .call,.mel-agent .think .call i,.mel-agent .think .call em{color:#D97757;font-style:italic}
.mel-agent .think p{margin:0 0 5px;color:#A8A69D;font-style:italic;font-size:12.5px;line-height:1.5}
.mel-agent .qa{display:flex;justify-content:space-between;gap:12px;padding:2px 0 3px;border-bottom:1px dashed #3A3935}
.mel-agent .qa:last-child{border-bottom:0}
.mel-agent .qa span{color:#B9B7AE}.mel-agent .qa b{color:#F2F1EC;white-space:nowrap}
.mel-agent .warn{color:#F2C14E;font-weight:700}
@media (max-width:760px){.mel-steps{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){.st-key-flow_agent,.st-key-flow_phone,.mel-steps .s{transition:none}}

/* ---- Dashboard (app/dashboard.py): a security-console layout. Section bars, KPI strips split by hairlines,
   flat white widgets with a title bar, rows of equal height. ------------------------------------------------- */
.mel-dsec{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px;margin:14px 0 4px;padding-bottom:8px;border-bottom:1px solid var(--mel-line-strong)}
.mel-dsec b{font-size:22px;font-weight:700;letter-spacing:-.02em;line-height:1.2;color:var(--mel-ink)}
.mel-dsec span{font-size:13px;color:var(--mel-muted)}
.mel-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));background:var(--mel-paper);border:1px solid var(--mel-line);
  border-radius:10px;overflow:hidden;margin:0 0 4px}
.mel-kpis .k{padding:14px 18px 12px;box-shadow:-1px 0 0 var(--mel-line),0 -1px 0 var(--mel-line)}  /* hairlines; the outer ones are clipped */
.mel-kpis .l{font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mel-muted)}
.mel-kpis .v{font-size:30px;font-weight:700;letter-spacing:-.03em;line-height:1.15;margin-top:6px;color:var(--mel-ink);font-variant-numeric:tabular-nums}
.mel-kpis .n{font-size:12.5px;color:var(--mel-muted);margin-top:2px;line-height:1.35}
.mel-kpis .h{grid-column:1/-1;padding:9px 18px 8px;font-size:12.5px;font-weight:700;color:var(--mel-ink-soft)}
.mel-kpi-row{display:grid;grid-template-columns:1.2fr 1fr;gap:12px;margin:0 0 4px}
.mel-kpi-row .mel-kpis{margin:0}
.mel-kpis.funnel .k{position:relative}
.mel-kpis.funnel .k+.k::before{content:"→";position:absolute;left:-12px;top:50%;width:22px;height:22px;margin-top:-11px;
  border-radius:50%;background:var(--mel-paper);border:1px solid var(--mel-line);display:grid;place-items:center;font-size:12px;
  font-weight:700;color:var(--mel-green);z-index:1}
@media (max-width:1100px){.mel-kpi-row{grid-template-columns:1fr}}
.mel-kpis.flat{border:0;border-radius:0;margin:0 -16px}
.mel-kpis.flat .v{font-size:24px}
[data-testid="stLayoutWrapper"]:has(>[class*="st-key-dcard_"]):last-child{flex:1 1 auto}  /* last widget fills its column: rows line up */
[class*="st-key-dcard_"]{background:var(--mel-paper);border:1px solid var(--mel-line);border-radius:10px;padding:0 16px 10px;gap:8px;flex:1 1 auto}
[class*="st-key-dcard_"] [data-testid="stMarkdownContainer"]{margin-bottom:0}  /* Streamlit's -1rem would pull the chart over the title */
.mel-dh{font-size:14px;font-weight:700;color:var(--mel-ink);margin:0 -16px;padding:11px 16px 10px;border-bottom:1px solid var(--mel-line);line-height:1.35}
.mel-dh small{display:block;font-size:12.5px;font-weight:400;color:var(--mel-muted);margin-top:2px}
.mel-d-body{font-size:14px;line-height:1.5;color:var(--mel-ink-soft);padding-top:4px;max-width:90ch}
.mel-d-lab{font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mel-muted);margin-top:8px}
.mel-d-seg{display:flex;gap:2px;height:28px;margin:8px 0 10px}
.mel-d-seg>div{border-radius:4px;display:flex;align-items:center;padding:0 8px;font-size:13px;font-weight:700;min-width:0;overflow:visible}
.mel-d-key{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13.5px;color:var(--mel-ink-soft)}
.mel-d-key i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.mel-d-key b{color:var(--mel-ink);margin-left:6px}

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
  .mel-mast{padding:14px 16px 6px;gap:14px}.mel-mast .mel-title{font-size:30px}.mel-mast .mel-tag{font-size:15px}
  .mel-foot{padding:16px}
  [data-testid="stTabs"] [role="tablist"]{padding:4px 10px 12px;justify-content:flex-start}
  [data-testid="stMetric"]{min-height:0;padding:12px 16px}
}
"""


def apply_theme() -> None:
    """Inject the global theme CSS. Call once near the top of the app, after `st.set_page_config`."""
    st.markdown("<style>" + CSS.replace("__MARK_URI__", _MARK_URI) + "</style>", unsafe_allow_html=True)
