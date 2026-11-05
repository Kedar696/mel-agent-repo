"""Interactive channel preview, part 2: the phone on screen. Owner: P5 (app).

    render_channel_preview(survey, channel, *, key, send_at=None) -> dict | None

Draws ONE phone in the caller's container (WhatsApp, Telegram, the app/web bottom sheet or a voice
call) with the controls the farmer really has, one question at a time. Returns P3's answer record
once the attempt ends (finished, closed, not now, opted out, typed instead, hung up), else None.
`key` must be stable per insight / channel / language / history setting; `send_at` is P2's time for
the first channel (otherwise the send window gives the fallback). Looks follow the real apps and the
payloads in mel/channels/render.py; nothing is sent anywhere.

Styling: the keyed container (`.st-key-<slug>`) is the phone, so widget rules are generated per
channel under that class; the HTML the preview writes sits inside `<div class="mel-pv mel-pv-wa">`
(or -tg / -app / -web / -voice), so bubble rules hang off those. Nothing targets the rest of the app.
"""
import hashlib
import re
from datetime import datetime
from html import escape

import streamlit as st

from mel.channels.render import UI, choices, render
from mel.timing import parse_ist
from app.display_time import format_clock, format_date
from app.theme import MARK
from app.preview_state import (PreviewState, SHEET, build_record, chat_log, label_for, open_time, send_time,
                               tap_time)

# Device chrome in the farmer's language (the survey language is the farmer's conversation language).
# Clocks and dates on the phone are US style in Eastern Time (app/display_time.py); the state machine's
# IST instants are unchanged underneath.
CHROME = {
    "hi-IN": dict(message="संदेश", business="बिज़नेस अकाउंट", bot="बॉट", edited="संपादित", call="इनकमिंग कॉल…",
                  answer="उठाएँ", declinecall="काटें", missed="कॉल नहीं उठाई",
                  key="दबाएँ", listen="सुनते रहें", nomore="और कॉल नहीं", hang="कॉल काटें", skipped="छोड़ दिया",
                  notice="🔒 यह बिज़नेस इस चैट को मैनेज करने के लिए Meta की सुरक्षित सेवा का उपयोग करता है।"),
    "en-IN": dict(message="Message", business="Business account", bot="bot", edited="edited", call="Incoming call…",
                  answer="Answer", declinecall="Decline", missed="No answer",
                  key="Press", listen="Keep listening", nomore="No more calls", hang="End call",
                  skipped="Skipped",
                  notice="🔒 This business uses a secure service from Meta to manage this chat."),
}
FOOT = {  # what the preview says under the phone once the attempt ends (the record itself is the caller's)
    "finished": "Finished: every question answered.",
    "closed": "Sheet closed part-way; the answers given were sent.",
    "dismissed": "No answers given; nothing was sent.",
    "declined": "The farmer said not now.",
    "opted_out": "Opted out: no more surveys for this farmer.",
    "free_text": "Typed instead of tapping: the question goes out again with its buttons.",
    "dropped": "Call cut off; answers before the cut are kept and FarmerChat calls back.",
    "missed": "The call rang out; the scheduler moves on to the next channel.",
}
# The call timer ticks in real time between taps and re-syncs to the simulated clock at every tap, so what is
# on screen never contradicts the record. Installed once per page through the same JavaScript hook the
# dashboard's count-up uses.
_TIMER_JS = """<script>
(() => {
  if (window.__melPvTimer) return;
  window.__melPvTimer = true;
  const pad = n => String(n).padStart(2, '0');
  setInterval(() => document.querySelectorAll('.mel-pv-timer[data-live]').forEach(el => {
    if (!el.dataset.t0) el.dataset.t0 = Date.now();
    const s = (+el.dataset.start) + Math.floor((Date.now() - +el.dataset.t0) / 1000);
    el.textContent = pad(Math.floor(s / 60)) + ':' + pad(s % 60);
  }), 1000);
})();
</script>"""
KIND = {"whatsapp": "mel-pv-wa", "telegram": "mel-pv-tg", "app": "mel-pv-app", "web": "mel-pv-app mel-pv-web",
        "voice": "mel-pv-voice"}

# Common: the frame (keyed container) and everything inside the preview's own HTML.
_CSS = """
/* One phone for every channel: 378 x 700 (the width follows the column on narrow screens). The header
   stays put, the screen (.mel-pv-body) scrolls inside, the live controls stay pinned below it. */
.st-key-__S__{box-sizing:border-box;width:100%;max-width:378px;height:var(--mel-pv-h,700px);flex:0 0 auto;margin:0 auto;border:9px solid #0d130f;border-radius:34px;overflow:hidden;
  box-shadow:0 22px 44px -26px rgba(13,19,15,.6);gap:0;display:flex;flex-direction:column}
.st-key-__S__>*{flex:0 0 auto;min-height:0;animation:mel-pv-enter-__S__ .24s ease-out both}
.st-key-__S__>[data-testid="stLayoutWrapper"]{max-height:55%;overflow-y:auto}
.st-key-__S__ [data-testid="stElementContainer"]:has(.mel-pv-body),
.st-key-__S__ [data-testid="stElementContainer"]:has(.mel-pv-body) [data-testid="stMarkdown"],
.st-key-__S__ [data-testid="stElementContainer"]:has(.mel-pv-body) [data-testid="stMarkdown"]>div,
.st-key-__S__ [data-testid="stElementContainer"]:has(.mel-pv-body) [data-testid="stMarkdownContainer"]{flex:1 1 0;min-height:0;display:flex;flex-direction:column;width:100%}
.mel-pv-body{flex:1 1 0;min-height:0;overflow-y:auto;overscroll-behavior:contain;display:flex;flex-direction:column-reverse}
/* the keyframe name carries the phone's key, so the entrance replays on a channel or language switch only */
@keyframes mel-pv-enter-__S__{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.st-key-__S__>*{animation:none}}
.st-key-__S__ [data-testid="stVerticalBlock"]{gap:0}
.st-key-__S__ [data-testid="stMarkdownContainer"]{margin-bottom:0}
.st-key-__S__ [data-testid="stMarkdownContainer"] p{margin:0}
.st-key-__S__ button:focus-visible{outline:2px solid #1d7a4c;outline-offset:-2px}
.mel-pv{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans","Noto Sans Devanagari",sans-serif}
.mel-pv-sb{display:flex;justify-content:space-between;align-items:center;padding:7px 18px 3px;font-size:12.5px;font-weight:600}
.mel-pv-sb svg{vertical-align:-2px;margin-left:5px}
.mel-pv-bar{display:flex;align-items:center;gap:10px;padding:8px 10px 9px;color:#fff}
.mel-pv-wa .mel-pv-sb,.mel-pv-wa .mel-pv-bar{background:#008069;color:#fff}
.mel-pv-tg .mel-pv-sb,.mel-pv-tg .mel-pv-bar{background:#517da2;color:#fff}
.mel-pv-app .mel-pv-sb{background:#032e15;color:#fff}
.mel-pv-app .mel-pv-fcbar{display:flex;align-items:center;justify-content:space-between;padding:8px 12px 12px;color:#fff;
  background:linear-gradient(180deg,#032e15 0%,#0a5a2e 100%)}
.mel-pv-app .mel-pv-fcbar .mel-pv-btn{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:50%;background:rgba(0,0,0,.35)}
.mel-pv-app .mel-pv-fcbar .mel-pv-pill{display:inline-flex;align-items:center;gap:6px;background:rgba(0,0,0,.35);border-radius:999px;padding:6px 12px;font-size:13px;font-weight:600}
.mel-pv-app .mel-pv-fcbrand{display:flex;align-items:center;gap:7px;font-size:15px;font-weight:700}
.mel-pv-app .mel-pv-fcbrand .mel-mark{font-size:22px;line-height:1}
.mel-pv-voice .mel-pv-sb{color:#eaf3ec}
.mel-pv-av{width:36px;height:36px;border-radius:50%;background:#dfe5e7;color:#1f3b2c;display:grid;place-items:center;font-weight:800;font-size:16px;flex:none}
.mel-pv-tg .mel-pv-av{background:#e7f0fb;color:#2b5f8f}
.mel-pv-bar .mel-pv-name{font-weight:600;font-size:15.5px;line-height:1.15}.mel-pv-bar .mel-pv-sub{font-size:12px;opacity:.85}
.mel-pv-bar .mel-pv-ic{margin-left:auto;display:flex;gap:18px;align-items:center;padding-right:4px}
.mel-pv-chat{padding:6px 10px 12px;gap:3px}
.mel-pv-chat.live{padding-bottom:0}
.mel-pv-chip{align-self:center;background:#fff;color:#54656f;font-size:12px;padding:5px 12px;border-radius:8px;margin:6px 0 4px;box-shadow:0 1px .5px rgba(11,20,26,.13)}
.mel-pv-tg .mel-pv-chip{background:rgba(66,89,107,.62);color:#fff;border-radius:14px;box-shadow:none}
.mel-pv-note{align-self:center;background:#ffeecd;color:#54656f;font-size:12px;line-height:1.4;padding:6px 12px;border-radius:8px;margin:0 8px 6px;text-align:center}
.mel-pv-row{display:flex;padding:1px 0}.mel-pv-row.out{justify-content:flex-end}
.mel-pv-bub{position:relative;max-width:84%;background:#fff;border-radius:7.5px;padding:6px 8px 6px 9px;font-size:15px;line-height:1.42;color:#111b21;box-shadow:0 1px .5px rgba(11,20,26,.13)}
.mel-pv-wa .mel-pv-row.in .mel-pv-bub{border-top-left-radius:0}.mel-pv-wa .mel-pv-row.out .mel-pv-bub{background:#d9fdd3;border-top-right-radius:0}
.mel-pv-wa .mel-pv-row.in .mel-pv-bub::before{content:"";position:absolute;top:0;left:-8px;border:8px solid transparent;border-top-color:#fff;border-right-color:#fff;border-radius:0 0 0 4px}
.mel-pv-wa .mel-pv-row.out .mel-pv-bub::before{content:"";position:absolute;top:0;right:-8px;border:8px solid transparent;border-top-color:#d9fdd3;border-left-color:#d9fdd3;border-radius:0 0 4px 0}
.mel-pv-tg .mel-pv-bub{border-radius:16px;padding:7px 10px}.mel-pv-tg .mel-pv-row.in .mel-pv-bub{border-bottom-left-radius:4px}
.mel-pv-tg .mel-pv-row.out .mel-pv-bub{background:#effdde;border-bottom-right-radius:4px}
.mel-pv-meta{float:right;margin:8px -2px -4px 10px;font-size:11px;color:#667781;line-height:1}
.mel-pv-tg .mel-pv-meta{color:#8d9aa3}.mel-pv-tg .mel-pv-row.out .mel-pv-meta{color:#5db052}
.mel-pv-meta .mel-pv-tick{color:#53bdeb;letter-spacing:-3px;margin-left:3px}
.mel-pv-wabtns{clear:both;margin:7px -8px -6px -9px;border-top:1px solid #e9edef}
.mel-pv-wabtns span{display:block;text-align:center;color:#027eb5;font-weight:500;font-size:14.5px;padding:9px 6px;border-top:1px solid #e9edef;opacity:.5}
.mel-pv-wabtns span:first-child{border-top:0}
.mel-pv-bub.open{border-bottom-left-radius:0;border-bottom-right-radius:0;box-shadow:none;width:84%;max-width:84%;padding-bottom:9px}
.mel-pv-tg .mel-pv-bub.open{border-radius:16px;border-bottom-left-radius:4px}
.mel-pv-tgkb{display:flex;flex-wrap:wrap;gap:3px;margin:3px 0 2px;max-width:84%}
.mel-pv-tgkb span{flex:1 1 auto;text-align:center;background:rgba(66,89,107,.5);color:#fff;font-size:14px;padding:8px 10px;border-radius:6px;opacity:.6}
.mel-pv-tgans{margin-top:6px;padding-top:6px;border-top:1px solid #eef1f3;color:#3a7a3a;font-weight:600}
.mel-pv-new{animation:mel-pv-in .22s ease-out}
@keyframes mel-pv-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes mel-pv-up{from{transform:translateY(16px);opacity:.6}to{transform:none;opacity:1}}
@media (prefers-reduced-motion:reduce){.mel-pv-new,.mel-pv-sheet{animation:none!important}}
.mel-pv-sheet{background:#fff;border-radius:16px 16px 0 0;box-shadow:0 -4px 18px rgba(0,0,0,.18);animation:mel-pv-up .25s ease-out}
.mel-pv-sheet-h{padding:8px 16px 4px;text-align:center}
.mel-pv-handle{width:34px;height:4px;border-radius:2px;background:#d1d7db;margin:0 auto 8px}
.mel-pv-sheet-t{font-weight:600;font-size:15px;color:#111b21}
.mel-pv-sheet-s{font-size:12.5px;color:#667781;padding:6px 16px 2px;text-align:left}
.mel-pv-appchat{padding:10px 12px 0;min-height:90px;flex:1 1 auto}
.mel-pv-push{background:#fff;border-radius:14px;padding:10px 12px;font-size:13.5px;line-height:1.4;color:#1a2a20;box-shadow:0 2px 10px rgba(16,34,25,.12)}
.mel-pv-push b{display:block;font-size:12px;color:#55665c;font-weight:600;margin-bottom:2px}
.mel-pv-dim{height:60px;background:linear-gradient(rgba(16,34,25,0),rgba(16,34,25,.32))}
.mel-pv-sheet.app{padding:10px 16px 2px;margin-top:-2px;animation:none}
.mel-pv-sheet.app.slide{animation:mel-pv-up .32s ease-out}
.mel-pv-sheet .mel-pv-title{font-size:13px;color:#55665c;margin-bottom:6px}
.mel-pv-steps{display:flex;gap:4px;margin:4px 0 10px}.mel-pv-steps i{flex:1;height:4px;border-radius:2px;background:#dfe6e0}.mel-pv-steps i.on{background:var(--mel-green,#266b4a)}
.mel-pv-done{font-size:13.5px;color:#55665c;padding:3px 0;border-bottom:1px solid #eef1ee}.mel-pv-done b{color:#1a2a20;font-weight:600}.mel-pv-done em{font-style:normal;color:#8a968e}
.mel-pv-q{font-size:18px;font-weight:700;line-height:1.35;color:#1a2a20;margin:8px 0 10px}
.mel-pv-thanks{font-size:17px;line-height:1.45;color:#1a2a20;padding:14px 0 18px}
.mel-pv-web .mel-pv-sb{background:#e9ecef;color:#3a4a40;font-weight:500;padding:8px 12px}
.mel-pv-web .mel-pv-tab{background:#fff;border-radius:8px 8px 0 0;padding:4px 12px;font-size:12.5px}
.mel-pv-web .mel-pv-url{background:#fff;border-radius:16px;padding:4px 12px;font-size:12.5px;color:#55665c;margin:0 12px 8px}
.mel-pv-call{color:#eaf3ec;padding:8px 18px 14px;text-align:center}
.mel-pv-call .mel-pv-av{width:72px;height:72px;font-size:30px;margin:14px auto 10px;background:#2f6b4a;color:#fff}
.mel-pv-call.ringing .mel-pv-av{animation:mel-pv-ring 1.4s ease-out infinite}
@keyframes mel-pv-ring{from{box-shadow:0 0 0 0 rgba(255,255,255,.35)}to{box-shadow:0 0 0 22px rgba(255,255,255,0)}}
@media (prefers-reduced-motion:reduce){.mel-pv-call.ringing .mel-pv-av{animation:none}}
.mel-pv-call .mel-pv-name{font-size:22px;font-weight:600}.mel-pv-call .mel-pv-sub{font-size:13.5px;opacity:.75;margin-top:2px}
.mel-pv-callid{flex:0 0 auto}
.mel-pv-cap{text-align:left;background:rgba(255,255,255,.07);border-radius:14px;padding:10px 12px;margin-top:16px;min-height:150px;flex:1 0 auto;font-size:14.5px;line-height:1.45}
.mel-pv-cap p{margin:0 0 7px;opacity:.62}.mel-pv-cap p.me{text-align:right;color:#ffd887}.mel-pv-cap p.now{opacity:1}
.st-key-__S__-foot{max-width:378px;margin:10px auto 0;text-align:center}
.st-key-__S__-foot p{font-size:14px;color:var(--mel-muted,#5d6a62);margin:0 0 6px}
.st-key-__S__-foot button{border-radius:20px;min-height:2.1rem}
"""
# Per channel: the phone's background and how Streamlit's own widgets (the live controls) are dressed.
_ACT = """
.st-key-__S__-act{padding:0 10px 8px}
.st-key-__S__-act button{width:100%;min-height:2.55rem;border:0;border-radius:0;transition:background .15s}
.st-key-__S__-act button p{font-size:15px;font-weight:500}
.st-key-__S__ [data-testid="stChatInput"]{background:#fff;border-radius:24px;border:0;margin:6px 10px 10px;width:auto;box-shadow:0 1px .5px rgba(11,20,26,.13)}
.st-key-__S__ [data-testid="stChatInput"]>div{background:#fff;border-radius:24px;border:0}
.st-key-__S__ [data-testid="stChatInput"] textarea{font-size:15px;padding-left:16px}
"""
_WIDGETS = {
    "whatsapp": _ACT + """
.st-key-__S__{background:#efeae2}
.st-key-__S__-act{width:calc((100% - 20px) * .84 + 20px)}
.st-key-__S__-act button{background:#fff;color:#027eb5;border-top:1px solid #e9edef;box-shadow:0 1px .5px rgba(11,20,26,.13)}
.st-key-__S__-act button:hover{background:#f5f6f6;color:#027eb5}
.st-key-__S__-act [data-testid="stVerticalBlock"]>div:last-child button{border-radius:0 0 7.5px 7.5px}
.st-key-__S__-pick{background:#fff;padding:0 6px 10px}
.st-key-__S__-pick [data-testid="stVerticalBlock"]{gap:0}
.st-key-__S__-pick button{width:100%;min-height:2.6rem;border:0;border-radius:8px;background:#fff;color:#111b21;justify-content:flex-start;padding-left:12px}
.st-key-__S__-pick button:hover{background:#f0f2f5;color:#111b21}
.st-key-__S__-pick button [data-testid="stMarkdownContainer"]{width:100%;text-align:left}
.st-key-__S__-pick button p{font-size:15px}
.st-key-__S__-pick button p::before{content:"";display:inline-block;width:16px;height:16px;border:2px solid #8696a0;border-radius:50%;vertical-align:-3px;margin-right:12px}
.st-key-__S__-pickx{background:#fff;padding:0 6px 10px}
.st-key-__S__-pickx button{width:100%;border:0;border-radius:8px;background:#fff;color:#667781;min-height:2.4rem}
.st-key-__S__-pickx button:hover{background:#f0f2f5;color:#111b21}
.st-key-__S__ [data-testid="stChatInputSubmitButton"] svg{fill:#008069;color:#008069}
""",
    "telegram": _ACT + """
.st-key-__S__{background:linear-gradient(165deg,#d9e5ef,#d8e6d9 55%,#e9e2d3)}
.st-key-__S__-act{width:calc((100% - 20px) * .84 + 20px);padding-top:8px}
.st-key-__S__ .st-key-__S__-act,.st-key-__S__-act [data-testid="stVerticalBlock"]{gap:8px}
.st-key-__S__-act [data-testid="stHorizontalBlock"]{gap:8px}
.st-key-__S__-act button{background:rgba(66,89,107,.62);color:#fff;border-radius:6px;min-height:2.4rem}
.st-key-__S__-act button:hover{background:rgba(66,89,107,.8);color:#fff}
.st-key-__S__-act button p{color:#fff}
.st-key-__S__ [data-testid="stChatInputSubmitButton"] svg{fill:#517da2;color:#517da2}
""",
    "app": _ACT + """
.st-key-__S__{background:#f4f6f3}
.st-key-__S__-act{background:#fff;padding:0 16px 14px}
.st-key-__S__ .st-key-__S__-act,.st-key-__S__-act [data-testid="stVerticalBlock"]{gap:8px}
.st-key-__S__-act button{border:1.5px solid #c9d8cc;border-radius:12px;background:#fbfdfb;color:#1a2a20;min-height:2.7rem}
.st-key-__S__-act button:hover{border-color:var(--mel-green,#266b4a);background:#eef6ef;color:#1a2a20}
.st-key-__S__-act [data-testid="stHorizontalBlock"]{margin-top:4px}
.st-key-__S__-act [data-testid="stHorizontalBlock"] button{border:0;background:transparent;color:#55665c;min-height:2.2rem}
.st-key-__S__-act [data-testid="stHorizontalBlock"] button p{font-size:13.5px}
""",
    "voice": _ACT + """
.st-key-__S__{background:#102219}
.st-key-__S__-act{padding:4px 18px 16px}
.st-key-__S__-act [data-testid="stHorizontalBlock"]{gap:8px;margin-top:8px}
.st-key-__S__ .st-key-__S__-act,.st-key-__S__-act [data-testid="stVerticalBlock"]{gap:8px}
.st-key-__S__-act button{background:rgba(255,255,255,.13);color:#fff;border-radius:14px;min-height:3.2rem;white-space:normal}
.st-key-__S__-act button:hover{background:rgba(255,255,255,.24);color:#fff}
.st-key-__S__-act button [data-testid="stMarkdownContainer"],.st-key-__S__-act button p{color:#fff;font-size:14.5px;white-space:normal;overflow:visible;text-overflow:clip}
.st-key-__S__-act [data-testid="stHorizontalBlock"] button p{font-size:24px;font-weight:500}
.st-key-__S__-hang{padding:0 18px 18px}
.st-key-__S__-hang button{width:100%;background:#d4423a;color:#fff;border:0;border-radius:28px;min-height:2.9rem}
.st-key-__S__-hang button:hover{background:#b9352e;color:#fff}
.st-key-__S__-hang button p{color:#fff}
.st-key-__S__-ring{padding:4px 18px 18px}
.st-key-__S__-ring [data-testid="stHorizontalBlock"]{gap:14px}
.st-key-__S__-ring button{width:100%;border:0;border-radius:30px;min-height:3.4rem;color:#fff}
.st-key-__S__-ring button p{color:#fff;font-size:15.5px;font-weight:600}
.st-key-__S__-ring [data-testid="stHorizontalBlock"]>div:first-child button{background:#d4423a}
.st-key-__S__-ring [data-testid="stHorizontalBlock"]>div:first-child button:hover{background:#b9352e;color:#fff}
.st-key-__S__-ring [data-testid="stHorizontalBlock"]>div:last-child button{background:#2f9e5a}
.st-key-__S__-ring [data-testid="stHorizontalBlock"]>div:last-child button:hover{background:#27874c;color:#fff}
""",
}
_WIDGETS["web"] = _WIDGETS["app"]

_SVG = {
    "signal": '<svg width="15" height="12" viewBox="0 0 15 12" fill="currentColor"><rect x="0" y="8" width="3" height="4" rx=".5"/><rect x="4" y="5" width="3" height="7" rx=".5"/><rect x="8" y="2.5" width="3" height="9.5" rx=".5"/><rect x="12" y="0" width="3" height="12" rx=".5"/></svg>',
    "wifi": '<svg width="15" height="12" viewBox="0 0 16 12" fill="currentColor"><path d="M8 11.3 1.6 4.9a9 9 0 0 1 12.8 0L8 11.3zm0-2.8 3.3-3.3a4.6 4.6 0 0 0-6.6 0L8 8.5z"/></svg>',
    "battery": '<svg width="22" height="12" viewBox="0 0 24 12" fill="none" stroke="currentColor"><rect x=".5" y=".5" width="20" height="11" rx="2.5"/><rect x="2.5" y="2.5" width="14" height="7" rx="1" fill="currentColor" stroke="none"/><rect x="21.5" y="3.5" width="2" height="5" rx="1" fill="currentColor" stroke="none"/></svg>',
    "back": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M15 5l-7 7 7 7"/></svg>',
    "video": '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M4 6h11a2 2 0 0 1 2 2v2.5l4-2.5v8l-4-2.5V16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/></svg>',
    "phone": '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/></svg>',
    "more": '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>',
}


# ---------------------------------------------------------------------------------------- helpers
def _slug(key: str) -> str:
    """A CSS-safe, collision-free class suffix for the caller's key."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-")[:48] + "-" + hashlib.md5(key.encode()).hexdigest()[:6]


def _clock(dt: datetime) -> str:
    return format_clock(dt)  # "9:30 PM", Eastern Time


def _status_bar(dt: datetime) -> str:
    return (f'<div class="mel-pv-sb"><span>{format_clock(dt)}</span>'
            f'<span>{_SVG["signal"]}{_SVG["wifi"]}{_SVG["battery"]}</span></div>')


def _app_bar(sub: str, icons: tuple = ("video", "phone", "more")) -> str:
    return (f'<div class="mel-pv-bar">{_SVG["back"]}<div class="mel-pv-av">F</div>'
            f'<div><div class="mel-pv-name">FarmerChat</div><div class="mel-pv-sub">{escape(sub)}</div></div>'
            f'<div class="mel-pv-ic">{"".join(_SVG[i] for i in icons)}</div></div>')


def _html(kind: str, inner: str, cls: str = ""):
    """`cls` "mel-pv-head" pins the block at the top of the phone; "mel-pv-body" makes it the screen
    that scrolls, laid out bottom-up (column-reverse) so its FIRST child is what sits at the bottom."""
    st.markdown(f'<div class="mel-pv {cls} {kind}">{inner}</div>', unsafe_allow_html=True)


def _do(state: PreviewState, method: str, *args):
    getattr(state, method)(*args)


def _typed(state: PreviewState, wkey: str):
    state.send_text(st.session_state.get(wkey) or "")


def _bubble(m: dict, channel: str, lang: str, new: bool, open_: bool = False) -> str:
    """One message. `open_`: the message whose buttons are live right now (they are real widgets
    drawn under it), so it shows no static copy of them."""
    out = m["who"] == "farmer"
    tick = '<span class="mel-pv-tick">✓✓</span>' if out else ""
    edited = f'{escape(CHROME[lang]["edited"])} ' if m.get("answer") else ""
    meta = f'<div class="mel-pv-meta">{edited}{_clock(m["at"])}{tick}</div>'
    body = f'<span>{escape(m["text"])}</span>'
    if m.get("answer"):  # Telegram: the bot edited the question to show the tap and dropped its keyboard
        body += f'<div class="mel-pv-tgans">✓ {escape(m["answer"])}</div>'
    bub = f'<div class="mel-pv-bub{" open" if open_ else ""}">{body}{meta}'
    past = m.get("buttons") and not open_ and not m.get("answer")  # buttons the farmer saw earlier: inert
    if past and channel == "whatsapp":
        labels = [f'☰ {UI[lang]["choose"]}'] if m.get("picker") else m["buttons"]
        bub += '<div class="mel-pv-wabtns">' + "".join(f"<span>{escape(l)}</span>" for l in labels) + "</div>"
    bub += "</div>"
    if past and channel == "telegram":
        bub = (f'<div style="display:flex;flex-direction:column">{bub}<div class="mel-pv-tgkb">'
               + "".join(f"<span>{escape(l)}</span>" for l in m["buttons"]) + "</div></div>")
    return f'<div class="mel-pv-row {"out" if out else "in"}{" mel-pv-new" if new else ""}">{bub}</div>'


def _choice_buttons(state, key, item, chs, cols=None):
    targets = st.columns(len(chs)) if cols else [st] * len(chs)
    for col, (label, value) in zip(targets, chs):
        col.button(label, key=f"{key}|{item['item_id']}|{value}", on_click=_do,
                   args=(state, "answer", item["item_id"], value), width="stretch")


# ---------------------------------------------------------------------------------- channels
def _chat(survey, channel, state, key, slug, t0, rec, fresh):
    lang, u, c, kind = survey["language"], UI[survey["language"]], CHROME[survey["language"]], KIND[channel]
    log, cur = chat_log(survey, channel, state, t0, follow_up=bool(rec and rec["needs_follow_up"]))
    now = (cur or log[-1])["at"]
    invite_live = channel == "whatsapp" and state.stage == "invite"
    _html(kind, _status_bar(now) + _app_bar(c["business"] if channel == "whatsapp" else c["bot"],
                                            ("video", "phone", "more") if channel == "whatsapp" else ("more",)),
          "mel-pv-head")
    n_new = 2 if fresh and state.started else 0  # the farmer's tap and the reply it brought
    shown = list(log) + ([{"who": "bot", "text": cur["text"], "at": cur["at"]}] if cur else [])
    msgs, day = [], None
    for i, m in enumerate(shown):
        if format_date(m["at"]) != day:  # every calendar day of the chat, in the phone's zone, gets a date chip
            day = format_date(m["at"])
            msgs.append(f'<div class="mel-pv-chip">{escape(day)}</div>')
            if channel == "whatsapp" and len(msgs) == 1:
                msgs.append(f'<div class="mel-pv-note">{escape(c["notice"])}</div>')
        if cur and i == len(shown) - 1:
            msgs.append(_bubble(m, channel, lang, new=fresh, open_=channel == "whatsapp"))
        else:
            msgs.append(_bubble(m, channel, lang, new=i >= len(log) - n_new and not cur,
                                open_=invite_live and i == len(log) - 1))
    # newest first: the screen is laid out bottom-up, so it opens on the latest message, never clipped
    _html(kind, "".join(reversed(msgs)), f'mel-pv-body mel-pv-chat{" live" if cur or invite_live else ""}')

    if invite_live:  # the template's quick replies
        with st.container(key=f"{slug}-act"):
            st.button(u["start"], key=f"{key}|start", on_click=_do, args=(state, "start"), width="stretch")
            st.button(u["later"], key=f"{key}|later", on_click=_do, args=(state, "decline"), width="stretch")
    elif state.stage == "picker":  # WhatsApp list message: the picker sheet
        _html(kind, f'<div class="mel-pv-sheet"><div class="mel-pv-sheet-h"><div class="mel-pv-handle"></div>'
                    f'<div class="mel-pv-sheet-t">{escape(u["choose"])}</div></div>'
                    f'<div class="mel-pv-sheet-s">{escape(u["pick_one"])}</div></div>')
        with st.container(key=f"{slug}-pick"):
            _choice_buttons(state, key, cur["item"], cur["choices"])
        with st.container(key=f"{slug}-pickx"):
            st.button("✕", key=f"{key}|pickx", on_click=_do, args=(state, "close_picker"), width="stretch")
    elif cur:
        it = cur["item"]
        with st.container(key=f"{slug}-act"):
            if cur["picker"]:
                st.button(f'☰ {u["choose"]}', key=f"{key}|pick", on_click=_do, args=(state, "open_picker"),
                          width="stretch")
            else:  # Telegram puts the scale's numbers in one row (render._telegram); other choices stack
                _choice_buttons(state, key, it, cur["choices"], cols=channel == "telegram" and it["type"] == "survey-scale")
    if not state.done:
        wkey = f"{key}|typed"
        st.chat_input(c["message"], key=wkey, on_submit=_typed, args=(state, wkey), max_chars=200)


def _sheet(survey, channel, state, key, slug, t0, rec, fresh):
    lang, u, c, kind = survey["language"], UI[survey["language"]], CHROME[survey["language"]], KIND[channel]
    sheet, items, n = render(survey, channel)["sheet"], survey["items"], state.n
    now = open_time(t0) if not state.taps else tap_time(t0, len(state.taps), n)
    if channel == "web":
        head = ('<div class="mel-pv-sb"><span>● ● ●</span><span class="mel-pv-tab">FarmerChat</span><span></span></div>'
                '<div class="mel-pv-url">🔒 FarmerChat web chat</div>')
    else:
        # The real FarmerChat app header: forest green, a round menu button, the mark and wordmark, a dark pill
        head = (_status_bar(now) + '<div class="mel-pv-fcbar"><span class="mel-pv-btn">&#9776;</span>'
                f'<span class="mel-pv-fcbrand">{MARK}FarmerChat</span><span class="mel-pv-pill">&#9728; 35°</span></div>')
    push = (f'<div class="mel-pv-push"><b>FarmerChat · {_clock(t0)}</b>{escape(u["invite"])}</div>'
            if channel == "app" else "")
    _html(kind, head, "mel-pv-head")
    chat = f'<div class="mel-pv-appchat">{push}</div>'
    if state.done and state.ending != "finished":  # closed, dismissed, opted out: the sheet is gone
        _html(kind, chat, "mel-pv-body")
        return
    done_rows = "".join(f'<div class="mel-pv-done">{escape(sheet["steps"][k]["step_label"])} &nbsp; '
                        + (f'<b>{escape(label_for(it, state.taps[it["item_id"]]))}</b>' if it["item_id"] in state.taps
                           else f'<em>{escape(c["skipped"])}</em>') + '</div>'
                        for k, it in enumerate(items[:state.step]))
    if state.done:  # finished: the thank-you step
        thanks = u["closing_fu"] if rec and rec["needs_follow_up"] else sheet["thank_you"]
        body = f'<div class="mel-pv-thanks">{escape(thanks)}</div>'
    else:
        step, bars = sheet["steps"][state.step], "".join(f'<i class="{"on" if k <= state.step else ""}"></i>' for k in range(n))
        body = (f'<div class="mel-pv-steps">{bars}</div>{done_rows}'
                f'<div class="mel-pv-title" style="margin-top:8px">{escape(step["step_label"])}</div>'
                f'<div class="mel-pv-q{" mel-pv-new" if fresh else ""}">{escape(step["question"])}</div>')
    slide = " slide" if fresh and not state.started else ""
    # bottom-up: the sheet sits at the bottom, the dimmed chat above it fills whatever is left
    _html(kind, f'<div class="mel-pv-sheet app{slide}"><div class="mel-pv-handle"></div>'
                f'<div class="mel-pv-title">{escape(sheet["title"])}</div>{body}</div>'
                f'<div class="mel-pv-dim"></div>{chat}', "mel-pv-body")
    if state.done:
        _html(kind, '<div style="background:#fff;height:14px"></div>')
        return
    it = items[state.step]
    with st.container(key=f"{slug}-act"):
        _choice_buttons(state, key, it, choices(it))
        # Skip leaves this step unanswered; P3's simulate_sheet keeps every answer given around it.
        b1, b2 = st.columns(2)
        b1.button(sheet["close_label"], key=f"{key}|close", on_click=_do, args=(state, "close"), width="stretch")
        b2.button(sheet["skip_label"], key=f"{key}|skip", on_click=_do, args=(state, "skip"), width="stretch")


def _voice(survey, channel, state, key, slug, t0, rec, fresh):
    lang, u, c, kind = survey["language"], UI[survey["language"]], CHROME[survey["language"]], KIND[channel]
    vo, items = render(survey, "voice"), survey["items"]
    ringing = state.stage == "ringing"
    lines = [] if ringing or state.ending == "missed" else [("bot", vo["opening"], state.stage == "invite")]
    for k, it in enumerate(items):
        if k < state.step:
            v = state.taps[it["item_id"]]
            kp = next(kk for kk, vv in vo["items"][k]["keypad"].items() if vv == v)
            lines += [("bot", vo["items"][k]["say"], False), ("me", f'{c["key"]} {kp}: {label_for(it, v)}', False)]
        elif k == state.step and state.stage == "question":  # the greeting stands alone until Keep listening
            lines.append(("bot", vo["items"][k]["say"], True))
    if state.done:
        said = {"finished": vo["closing_if_follow_up"] if rec and rec["needs_follow_up"] else vo["closing"],
                "declined": f'{c["key"]} 2: {u["later"]}', "opted_out": f'{c["key"]} 9: {c["nomore"]}',
                "dropped": f'📵 {c["hang"]}', "missed": f'📵 {c["missed"]}'}[state.ending]
        lines.append(("bot" if state.ending == "finished" else "me", said, True))
    # The phone's clock: the call rings at the send time, is picked up at `opened`, and the timer runs from
    # there: live between taps (the script re-syncs it at every tap) and frozen at recorded_at once it is over.
    opened = open_time(t0)
    if ringing:
        now = t0
    elif state.done:
        now = parse_ist(rec["recorded_at"])
    else:
        now = tap_time(t0, len(state.taps), state.n) if state.taps else opened
    secs = max(0, int((now - opened).total_seconds()))
    live = not ringing and not state.done
    if ringing or state.ending == "missed":
        sub = escape(c["call"] if ringing else c["missed"])
    else:
        sub = (f'<span class="mel-pv-timer" data-start="{secs}"{" data-live=\"1\"" if live else ""}>'
               f'{secs // 60:02d}:{secs % 60:02d}</span>')
    cap = "".join(f'<p class="{w}{" now" if now else ""}{" mel-pv-new" if now and fresh else ""}">'
                  f'{"🔈 " if w == "bot" else ""}{escape(t)}</p>' for w, t, now in lines)
    _html(kind, _status_bar(now), "mel-pv-head")
    _html(kind, f'<div class="mel-pv-cap">{cap}</div><div class="mel-pv-callid"><div class="mel-pv-av">F</div>'
                f'<div class="mel-pv-name">FarmerChat</div><div class="mel-pv-sub">{sub}</div></div>',
          f"mel-pv-body mel-pv-call{' ringing' if ringing else ''}")
    if live:
        st.html(_TIMER_JS, unsafe_allow_javascript=True)
    if state.done:
        return
    if ringing:  # a real incoming-call screen: Decline (the call rings out) or Answer (the greeting plays)
        with st.container(key=f"{slug}-ring"):
            b1, b2 = st.columns(2)
            b1.button(f'📵 {c["declinecall"]}', key=f"{key}|miss", on_click=_do, args=(state, "miss"), width="stretch")
            b2.button(f'📞 {c["answer"]}', key=f"{key}|pickup", on_click=_do, args=(state, "pick_up"), width="stretch")
        return
    with st.container(key=f"{slug}-act"):
        if state.stage == "invite":
            st.button(f'▶ {c["listen"]}', key=f"{key}|start", on_click=_do, args=(state, "start"), width="stretch")
            b1, b2 = st.columns(2)
            b1.button("2", key=f"{key}|later", on_click=_do, args=(state, "decline"), width="stretch", help=u["later"])
            b2.button("9", key=f"{key}|opt", on_click=_do, args=(state, "opt_out"), width="stretch", help=c["nomore"])
        else:
            # A dial pad: digits only, as on a phone; the spoken line says which digit means what.
            it, keys = items[state.step], vo["items"][state.step]["keypad"]
            cols = st.columns(min(len(keys), 3))
            for i, (kp, value) in enumerate(keys.items()):
                cols[i % len(cols)].button(kp, key=f"{key}|{it['item_id']}|{value}", on_click=_do,
                                           args=(state, "answer", it["item_id"], value), width="stretch",
                                           help=label_for(it, value))
    with st.container(key=f"{slug}-hang"):
        st.button(f'📵 {c["hang"]}', key=f"{key}|hang", on_click=_do, args=(state, "hang_up"), width="stretch")


# ------------------------------------------------------------------------------------- public
def render_channel_preview(survey: dict, channel: str, *, key: str, send_at: str | None = None,
                           restart: bool = False, show_restart: bool = True) -> dict | None:
    """One live phone for `survey` on `channel`; see the module docstring.
    `restart=True` (e.g. the app's own Restart button on this run) puts the phone back to its first
    screen before anything is drawn; `show_restart=False` hides the preview's own Start over button."""
    slug = _slug(key)
    skey = f"mel_preview|{key}"
    state = st.session_state.get(skey)
    ids = tuple(it["item_id"] for it in survey["items"])
    if not isinstance(state, PreviewState) or state.ids != ids or state.channel != channel:
        state = st.session_state[skey] = PreviewState.new(survey, channel)
    if restart:
        state.reset()
    rec = build_record(survey, channel, state, send_at)
    t0 = send_time(survey, channel, send_at)
    fresh = st.session_state.get(skey + "|seen") != state.rev  # something changed since the last draw
    st.session_state[skey + "|seen"] = state.rev
    with st.container(key=slug):
        # The phone's styles ride inside the phone, so nothing sits above it: its top lines up with whatever
        # the caller puts beside it (the Survey demo's agent panel).
        st.markdown(f"<style>{(_CSS + _WIDGETS[channel]).replace('__S__', slug)}</style>", unsafe_allow_html=True)
        draw = _chat if channel in ("whatsapp", "telegram") else _sheet if channel in SHEET else _voice
        draw(survey, channel, state, key, slug, t0, rec, fresh)
    with st.container(key=f"{slug}-foot"):
        if state.done:
            skipped = state.n - len(state.taps) if state.ending == "finished" else 0
            foot = f"Finished: {len(state.taps)} answered, {skipped} skipped." if skipped else FOOT[state.ending]
            st.markdown(f"<p>{escape(foot)}</p>", unsafe_allow_html=True)
        if state.started and show_restart:
            st.button("Start over", key=f"{key}|reset", on_click=_do, args=(state, "reset"))
    return rec
