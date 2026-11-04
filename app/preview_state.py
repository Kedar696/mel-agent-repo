"""Interactive channel preview, part 1: the farmer's taps as a small state machine, plus the answer
record P3's simulator builds from those taps. Owner: P5 (app). No Streamlit here, so tests can drive
the whole flow headlessly; app/channel_preview.py draws it.

Grounded in mel/channels/render.py (WhatsApp template Start / Not now, <=3 reply buttons vs a list
picker, Telegram inline keyboards, the app/web bottom sheet, the voice keypad) and in
mel/simulator/simulate.py (cases, timestamps, raw events). Nothing here invents a farmer answer: a
record only ever carries what was tapped or typed on the screen.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mel.channels.render import UI, choices
from mel.simulator import simulate, simulate_sheet
from mel.simulator.simulate import SEND_OFFSET_H
from mel.timing import fmt_ist, parse_ist

SHEET = ("app", "web")
CHAT = ("whatsapp", "telegram")
OPENING = ("whatsapp", "voice")  # a Start / Not now moment before question 1 (template message, IVR greeting)
STOP_WORD = {"whatsapp": "STOP", "telegram": "/stop"}  # typed by the farmer to opt out (outcome_codes.json)
WA_MAX_BUTTONS = 3  # WhatsApp allows 3 reply buttons; longer lists open a picker (render._whatsapp)
OPEN_MIN, LAST_MIN = 20, 25  # P3's timeline: opened 20 min after the send, last answer at 25 min
ENDINGS = ("finished", "closed", "dismissed", "declined", "opted_out", "free_text", "dropped")


@dataclass
class PreviewState:
    """Where the farmer is in one survey attempt on one channel."""
    channel: str
    ids: tuple                      # item ids in survey order
    values: dict                    # item id -> the values its buttons carry
    stage: str = "question"         # invite | question | picker | ended
    step: int = 0                   # index of the question on screen
    taps: dict = field(default_factory=dict)  # item id -> value, in tap order (never a default)
    ending: str | None = None       # one of ENDINGS once stage == "ended"
    ended_from: str | None = None   # the stage the farmer was in when it ended
    typed: str | None = None        # the message the farmer typed instead of tapping
    rev: int = 0                    # bumps on every change, so the screen can animate only what is new

    @classmethod
    def new(cls, survey: dict, channel: str) -> "PreviewState":
        items = survey["items"]
        return cls(channel, tuple(it["item_id"] for it in items),
                   {it["item_id"]: tuple(v for _, v in choices(it)) for it in items},
                   stage="invite" if channel in OPENING else "question")

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def current(self) -> str | None:
        """Item id on screen, or None when none is."""
        return self.ids[self.step] if self.stage in ("question", "picker") else None

    @property
    def done(self) -> bool:
        return self.stage == "ended"

    @property
    def started(self) -> bool:
        """Anything to start over from."""
        return self.done or bool(self.taps) or self.stage != ("invite" if self.channel in OPENING else "question")

    # ---- transitions. Each one ignores a tap that no longer fits the screen (a double click, or a click
    # from before a rerun), so one tap advances exactly one question.
    def _go(self, stage: str):
        self.stage, self.rev = stage, self.rev + 1

    def _end(self, how: str):
        self.ending, self.ended_from = how, self.stage
        self._go("ended")

    def start(self):
        """WhatsApp Start; the IVR greeting ends."""
        if self.stage == "invite":
            self._go("question")

    def decline(self):
        """WhatsApp Not now; key 2 on the call."""
        if self.stage == "invite":
            self._end("declined")

    def answer(self, item_id: str, value):
        if self.current == item_id and value in self.values[item_id]:
            self.taps[item_id] = value
            self.step += 1
            self._end("finished") if self.step >= self.n else self._go("question")

    def open_picker(self):
        if self.stage == "question":
            self._go("picker")

    def close_picker(self):
        if self.stage == "picker":
            self._go("question")

    def close(self):
        """Close or swipe the sheet down: the answers so far are sent (brief: submit once)."""
        if not self.done:
            self._end("closed" if self.taps else "dismissed")

    def opt_out(self):
        """Do not ask me again, STOP, /stop, key 9: no more surveys for this farmer."""
        if not self.done:
            self._end("opted_out")

    def send_text(self, text: str):
        """The farmer types instead of tapping. The channel's stop word opts out; anything else is
        free_text_instead_of_choice, and the question is sent again with its buttons."""
        text = (text or "").strip()
        if not text or self.done:
            return
        if text.upper() == STOP_WORD.get(self.channel, "").upper():
            self.opt_out()
        else:
            self.typed = text
            self._end("free_text")

    def hang_up(self):
        if not self.done:
            self._end("dropped")

    def reset(self):
        self.step, self.taps, self.ending, self.ended_from, self.typed = 0, {}, None, None, None
        self._go("invite" if self.channel in OPENING else "question")


# ------------------------------------------------------------------------------------------ time
def send_time(survey: dict, channel: str, send_at: str | None = None) -> datetime:
    """P2's recommended time when the caller has one (first channel), else P3's fallback: the window
    opening plus the channel's fixed offset. The same rule simulate() applies, so record and screen agree."""
    if send_at:
        return parse_ist(send_at)
    return parse_ist(survey["send_window"]["not_before"]) + timedelta(hours=SEND_OFFSET_H[channel])


def open_time(t0: datetime) -> datetime:
    return t0 + timedelta(minutes=OPEN_MIN)


def tap_time(t0: datetime, k: int, n: int) -> datetime:
    """When the k-th of n answers (1-based) lands: spread over the farmer's five minutes so the last
    one is exactly P3's `answered` stamp."""
    return t0 + timedelta(minutes=LAST_MIN - ((n - k) * (LAST_MIN - OPEN_MIN)) // n)


def label_for(item: dict, value) -> str:
    return next((l for l, v in choices(item) if v == value), str(value))


# ---------------------------------------------------------------------------------------- record
def build_record(survey: dict, channel: str, state: PreviewState, send_at: str | None = None) -> dict | None:
    """The response.schema.json record for a finished attempt, built by P3's simulator from the real
    taps; None while the farmer is still answering."""
    if not state.done:
        return None
    at = fmt_ist(send_time(survey, channel, send_at))
    taps = dict(state.taps)
    # Every item answered, the tapped ones with their real values encoded for the channel. The
    # finished record itself, and the source of the answered entries for every partial ending.
    full = simulate(survey, channel, "completed", answers=taps, send_at=at)
    how = state.ending
    if how == "finished":
        return full
    if how == "closed":  # P3's submit-once sheet: keeps the given answers, marks the step shown as skipped
        rec = simulate_sheet(survey, channel, list(taps), closed=True, answers=taps)
        rec.update(timestamps=full["timestamps"], recorded_at=full["recorded_at"],
                   raw_event=f"Close tapped at step {len(taps) + 1} of {state.n}")
        return rec
    case = {"dismissed": "sheet_dismissed", "declined": "farmer_declined", "opted_out": "farmer_opted_out",
            "free_text": "free_text_instead_of_choice", "dropped": "voice_call_dropped"}[how]
    base = simulate(survey, channel, case, send_at=at)
    if how in ("dismissed", "declined"):  # nothing was answered: P3's record is already exact
        return base
    return _reseat(base, full, survey, state)


def _reseat(base: dict, full: dict, survey: dict, state: PreviewState) -> dict:
    """P3's partial cases place the given answers around the survey's anchor question (the reference
    grid's convention). The preview knows exactly which questions the farmer reached, so keep the
    real taps, mark the question on screen truthfully and leave the rest not_reached. This mirrors
    simulate()'s own bookkeeping; a simulate(..., reached=, invalid_at=) parameter from P3 would
    replace it."""
    taps, how = state.taps, state.ending
    on_screen = state.ended_from in ("question", "picker")
    shown = {"free_text": "invalid", "opted_out": "skipped", "dropped": "not_reached"}[how]
    items = []
    for k, (item_id, entry) in enumerate(zip(state.ids, base["items"])):
        if item_id in taps:
            items.append(full["items"][k])
            continue
        e = {**entry, "result": "not_reached", "value": None, "raw_input": None, "input_kind": None, "attempts": 0}
        if k == state.step and (on_screen or how == "free_text"):
            e["result"] = shown
            if shown == "invalid":
                e.update(raw_input=state.typed, input_kind="free_text", attempts=1)
            elif shown == "skipped":
                e["attempts"] = 1
        items.append(e)
    rec = {**base, "items": items, "answers": {i: taps[i] for i in state.ids if i in taps}, "complete": False,
           "needs_follow_up": full["needs_follow_up"], "follow_up_reasons": full["follow_up_reasons"],
           # FarmerChat's store answers once answers are submitted and the attempt is over (simulate.py).
           "farmerchat_reply": ({"http_status": 201, "outcome": "accepted"}
                                if taps and base["retry_decision"] in ("none", "give_up") else None)}
    if how == "dropped":  # a cut call has an answer event only if something was answered before the cut
        ts = {**base["timestamps"], "answered": full["timestamps"]["answered"] if taps else None}
        # Nothing answered: the cut is logged two minutes after the farmer picked up (`opened`), never
        # before it (the reference record stamps sent+2, which predates its own opened time).
        cut = fmt_ist(parse_ist(ts["opened"] or ts["sent"]) + timedelta(minutes=2))
        rec.update(timestamps=ts, answered_by=survey["farmer_id"] if taps else None,
                   recorded_at=ts["answered"] or cut)
    return rec


# ------------------------------------------------------------------------------------- chat log
def _msg(who, text, at, **extra):
    return {"who": who, "text": text, "at": at, **extra}


def chat_log(survey: dict, channel: str, state: PreviewState, t0: datetime,
             follow_up: bool = False) -> tuple[list[dict], dict | None]:
    """WhatsApp / Telegram: the messages so far (oldest first) and the question on screen now, each
    with its IST time. Bot messages keep the buttons the farmer saw (`buttons`, or `picker` for a
    WhatsApp list). A WhatsApp tap comes back as the farmer's message; a Telegram tap edits the
    question (`answer`), as bots do. `follow_up` picks the closing line."""
    u, items, taps = UI[survey["language"]], survey["items"], state.taps
    n, opened = len(items), open_time(t0)
    last = tap_time(t0, n, n)  # P3 stamps every final event (last answer, Not now, STOP, typed text) here
    log = []
    if channel == "whatsapp":
        log.append(_msg("bot", u["invite"], t0, buttons=[u["start"], u["later"]]))
        if state.stage == "invite":
            return log, None
        if state.ended_from == "invite":  # Not now, STOP, or typed at the template
            text = {"declined": u["later"], "opted_out": STOP_WORD[channel]}.get(state.ending, state.typed)
            log.append(_msg("farmer", text, last))
            return log, None
        log.append(_msg("farmer", u["start"], opened))
        q_at = opened
    else:
        log.append(_msg("bot", u["invite"], t0))
        q_at = t0
    current = None
    for k, it in enumerate(items):
        ch = choices(it)
        picker = channel == "whatsapp" and len(ch) > WA_MAX_BUTTONS
        shown = dict(buttons=[l for l, _ in ch], picker=picker)
        if k < state.step:
            label, t = label_for(it, taps[it["item_id"]]), tap_time(t0, k + 1, n)
            if channel == "whatsapp":
                log += [_msg("bot", it["prompt"], q_at, **shown), _msg("farmer", label, t)]
            else:
                log.append(_msg("bot", it["prompt"], q_at, answer=label, **shown))
            q_at = t
        elif k == state.step:
            if state.done:  # ended on this question: STOP / typed message
                log.append(_msg("bot", it["prompt"], q_at, **shown))
                text = STOP_WORD[channel] if state.ending == "opted_out" else state.typed
                log.append(_msg("farmer", text, last))
            else:
                current = {"item": it, "text": it["prompt"], "at": q_at, "choices": ch, "picker": picker}
            break
    if state.ending == "finished":
        log.append(_msg("bot", u["closing_fu"] if follow_up else u["thanks"], last))
    return log, current
