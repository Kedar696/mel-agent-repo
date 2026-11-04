"""Simulated farmer answers -> response.schema.json records. Owner: P3.

Two entry points, both deterministic and reproducible:

  simulate(survey, channel, case, seed=0)
      One answer record for one channel and one case. `case` is a success case
      (completed / partial / negative_outcome), a sheet case (sheet_closed_partway /
      sheet_interrupted, app+web only) or any failure code in
      config/rules/outcome_codes.json. Reproduces the pack's reference grid in
      data/mock/outcomes/ exactly (field for field) for the default persona.

  simulate_handoff(handoff, persona="default", seed=0)
      Walks the hand-off's channel_order the way the broadcaster would: it skips
      channels the persona cannot be reached on, respects send hours / send window /
      expiry, and after each attempt stops or falls back to the next channel
      according to the retry_decision in outcome_codes.json. Returns the list of
      answer records produced, one per channel actually tried. Keeps simulate()
      underneath for single records (H+4 decision, docs/h4_interface_decisions.md row 15).

The farmer is modelled by a fixed *persona* rather than seeded randomness, so the
records are byte-for-byte reproducible and match the reference grid. `seed` is kept
in the signature (and mixed into answer choice only when a persona asks for a random
pick) so the Studio can still explore variations without breaking the contract.

Lateness: the brief says answers that arrive after expires_at are kept but marked
`late`. response.schema.json currently forbids extra fields, so a `late` flag can only
be emitted once P1 adds it (see docs/h4_schema_change_request_late.md). Until then the
flag is computed internally and only attached when MEL_RESPONSE_LATE_FIELD=1, so every
record this module emits by default stays schema-valid.
"""
import os
from datetime import timedelta

from mel.config import outcome_codes
from mel.channels.render import choices, SPEECH_YES_NO
from mel.timing import parse_ist, fmt_ist, expires_at

SUCCESS_CASES = ("completed", "partial", "negative_outcome")
# Minutes after the window opens (07:00) that each channel first sends. app is first;
# whatsapp/telegram go an hour later; web and voice three hours later. Matches the grid.
SEND_OFFSET_H = {"app": 0, "web": 3, "whatsapp": 1, "telegram": 1, "voice": 3}
SHEET = ("app", "web")

# Whether the `late` flag may be written onto records. Off by default so records stay
# valid against today's response.schema.json; P1 adds the field, then this turns on.
_EMIT_LATE = os.environ.get("MEL_RESPONSE_LATE_FIELD") == "1"


def cases_for(channel: str) -> list[str]:
    """Every case worth simulating on a channel, mirroring the reference grid."""
    oc = outcome_codes()
    na = oc.get("not_applicable", {})
    out = ["completed", "negative_outcome"]
    out += list(oc["sheet_cases"]) if channel in SHEET else ["partial"]
    out += [k for k, v in oc["failures"].items() if channel in v["channels"] and f"{channel}/{k}" not in na]
    return out


# --------------------------------------------------------------------------- persona
def _follow_up(item: dict, value) -> str | None:
    """The follow_up reason an answer carries, or None."""
    if item["type"] == "survey-scale":
        lim = item.get("follow_up_at_or_below")
        return item.get("follow_up_reason") if lim is not None and value is not None and value <= lim else None
    return next((o.get("follow_up") for o in item.get("options", []) if o["value"] == value), None)


def _good_value(item: dict):
    """The persona's default (non-follow-up) answer to one item.

    Options: the first option that carries no follow_up. Scale: the top of the scale
    (the most positive answer, which never trips follow_up_at_or_below)."""
    if item["type"] == "survey-scale":
        return item["scale_max"]
    for o in item["options"]:
        if not o.get("follow_up"):
            return o["value"]
    return item["options"][0]["value"]


def _bad_value(item: dict):
    """The persona's follow-up answer to one item, or None if the item has none.

    Options: the first option that carries a follow_up. Scale: the bottom of the scale
    (<= follow_up_at_or_below), only if the item defines a follow-up threshold."""
    if item["type"] == "survey-scale":
        return item["scale_min"] if item.get("follow_up_at_or_below") is not None else None
    return next((o["value"] for o in item["options"] if o.get("follow_up")), None)


def _answer_plan(items: list[dict], negative_at: int | None) -> dict:
    """{item_id: value} the persona would give if it answered every item.

    Every item gets its good value. For negative_outcome the item at index `negative_at`
    (the survey's anchor) gets its bad value instead, if it can carry one; failing that,
    the nearest later item that can. This reproduces the grid: confirm survey -> q1 'no',
    single-select survey -> q3 'same', scale survey -> q3 (scale_min)."""
    plan = {it["item_id"]: _good_value(it) for it in items}
    if negative_at is not None:
        order = [negative_at] + [k for k in range(len(items)) if k != negative_at]
        for k in order:
            bad = _bad_value(items[k])
            if bad is not None:
                plan[items[k]["item_id"]] = bad
                break
    return plan


# ------------------------------------------------------------------ channel encoding
def _encode(channel: str, sid: str, item: dict, value, idx: int) -> tuple[str, str]:
    """(raw_input, input_kind) for an accepted answer on a channel."""
    if channel in SHEET:
        return str(value), "sheet_tap"
    if channel == "whatsapp":
        # <=3 choices ride reply buttons; more use the list picker.
        kind = "button_reply" if len(choices(item)) <= 3 else "list_reply"
        return f"{sid}|{item['item_id']}|{value}", kind
    if channel == "telegram":
        return f"mel|{sid}|{item['item_id']}|{value}", "callback_data"
    # voice: a scale is its number; other taps are the 1-based keypad digit.
    # (A yes/no confirm is handled as speech by _answered_entry.)
    if item["type"] == "survey-scale":
        return str(value), "keypad"
    return str(idx), "keypad"


def _voice_speech_word(item: dict, value, lang: str) -> str:
    """The spoken word the voice persona uses for a confirm answer (हाँ / नहीं)."""
    return SPEECH_YES_NO[lang]["yes" if value == "yes" else "no"][0]


# ------------------------------------------------------------------------ one record
def _blank(item: dict) -> dict:
    return {"item_id": item["item_id"], "item_type": item["type"], "result": "not_reached",
            "value": None, "raw_input": None, "input_kind": None, "attempts": 0}


def _answered_entry(channel, sid, item, value, lang) -> dict:
    idx = next(i for i, (_, cv) in enumerate(choices(item), 1) if cv == value)
    raw, kind = _encode(channel, sid, item, value, idx)
    if channel == "voice" and item["type"] == "survey-confirm":
        raw, kind = _voice_speech_word(item, value, lang), "speech"
    e = _blank(item)
    e.update(result="answered", value=value, raw_input=raw, input_kind=kind, attempts=1)
    return e


# Free-text / invalid raw inputs the persona produces, per failing case.
_INVALID_RAW = {
    "free_text_instead_of_choice": ("पता नहीं, कल बताऊँगा", "free_text", 1),
    "speech_not_understood": ("हम्म... शायद", "speech", 2),
}


def simulate(survey: dict, channel: str, case: str = "completed", seed: int = 0,
answers: dict | None = None, attempt: int = 1, persona: str = "default",
             send_at: str | None = None) -> dict:
    """send_at: P2's recommended send time (decision.send_time["send_at"]) for the first channel.
    Without it the send goes out at the window opening plus a fixed per-channel offset."""
    oc = outcome_codes()
    fail = oc["failures"].get(case)
    sheet_case = oc["sheet_cases"].get(case)
    sid, items, lang = survey["survey_id"], survey["items"], survey["language"]
    n = len(items)
    window = survey["send_window"]
    exp = expires_at(window)

    t0 = (parse_ist(send_at) if send_at else
          parse_ist(window["not_before"]) + timedelta(hours=SEND_OFFSET_H[channel]))
    ts = {"sent": fmt_ist(t0),
          "delivered": fmt_ist(t0 + timedelta(minutes=1)),
          "opened": fmt_ist(t0 + timedelta(minutes=20)),
          "answered": fmt_ist(t0 + timedelta(minutes=25))}

    # The survey's "anchor" item (confirm surveys -> q1, single-select/scale -> q3) is the
    # one the grid demonstrates each question type on, and it is where several cases focus:
    # the single answer in `partial`, the invalid tap in free_text, the discarded tap in
    # stale/duplicate/identity cases, and the follow-up answer in negative_outcome.
    anchor_id = _anchor_item_id(survey)
    anchor = next((k for k, it in enumerate(items) if it["item_id"] == anchor_id), n - 1)

    # The full set of answers the persona would give, before the case trims them.
    plan = _answer_plan(items, anchor if case == "negative_outcome" else None)
    if answers:  # caller override (used by simulate_handoff / Studio)
        plan.update(answers)

    recs = [_blank(it) for it in items]
    accepted: dict = {}
    reasons: list[str] = []

    def accept(k):
        it = items[k]
        recs[k] = _answered_entry(channel, sid, it, plan[it["item_id"]], lang)
        accepted[it["item_id"]] = plan[it["item_id"]]
        if r := _follow_up(it, plan[it["item_id"]]):
            reasons.append(r)

    # ---- decide which items are answered and how the attempt ends ----
    if case in ("completed", "negative_outcome"):
        for k in range(n):
            accept(k)
    elif case in ("sheet_closed_partway", "sheet_interrupted"):
        # The farmer answers every step but the last, then closes / is interrupted.
        for k in range(n - 1):
            accept(k)
        recs[n - 1].update(result="skipped", attempts=1)
    elif case == "partial":
        # The farmer answers only the anchor question and skips the others.
        for k in range(n):
            if k == anchor:
                accept(k)
            else:
                recs[k].update(result="skipped", attempts=1)
    elif case == "sheet_dismissed":
        recs[0].update(result="skipped", attempts=1)
    elif case == "free_text_instead_of_choice":
        # Items before the anchor are answered; the farmer types free text on the anchor;
        # items after it are never reached.
        for k in range(anchor):
            accept(k)
        raw, kind, att = _INVALID_RAW[case]
        recs[anchor].update(result="invalid", raw_input=raw, input_kind=kind, attempts=att)
    elif case in ("keypad_out_of_range", "speech_not_understood"):
        # Voice. Items before the anchor are answered; the anchor is the invalid one;
        # items after it are answered afterwards (the call moves on).
        for k in range(n):
            if k == anchor:
                if case == "keypad_out_of_range":
                    raw = str(len(choices(items[k])) + 2)  # a digit with no option behind it
                    recs[k].update(result="invalid", raw_input=raw, input_kind="keypad", attempts=2)
                else:
                    raw, kind, att = _INVALID_RAW[case]
                    recs[k].update(result="invalid", raw_input=raw, input_kind=kind, attempts=att)
            else:
                accept(k)
    elif case == "voice_call_dropped":
        # Answers before the drop are kept; the remaining item(s) are never reached.
        # The call drops on the anchor item.
        for k in range(anchor):
            accept(k)
    elif case in ("survey_closed", "survey_replaced", "duplicate_answer", "identity_mismatch"):
        # A tap arrives but is not stored. The reference puts the discarded answer on the
        # anchor item; the others are never reached.
        it = items[anchor]
        recs[anchor] = _answered_entry(channel, sid, it, plan[it["item_id"]], lang)
        recs[anchor]["result"] = "discarded"
    elif case == "window_expired":
        # Delivered / waiting, but no answer before the window closed. On channels that
        # actually presented the first question (whatsapp, telegram, voice) that step is
        # shown-but-unanswered (skipped); on web the sheet never opened (no notifications),
        # so nothing was shown and every item stays not_reached.
        if channel != "web":
            recs[0].update(result="skipped", attempts=1)
    # delivery_failed cases that never reach the farmer leave every item not_reached.

    # ---- status / retry / cap ----
    if fail:
        status, code = fail["status"], case
        retry, retry_after, cap = fail["retry_decision"], fail["retry_after_minutes"], fail["counts_toward_cap"]
    elif sheet_case:
        status, code = ("negative_outcome" if reasons else sheet_case["status"]), None
        retry, retry_after, cap = "none", None, True
    else:
        status = "negative_outcome" if reasons else ("completed" if len(accepted) == n else "partial")
        code, retry, retry_after, cap = None, "none", None, True

    stored = status not in ("stale", "duplicate", "identity_mismatch")

    # ---- timestamps per case ----
    undelivered = status == "delivery_failed" and case != "voice_call_dropped"
    if undelivered:
        ts.update(delivered=None, opened=None, answered=None)
    if channel == "telegram":
        ts["opened"] = None  # no read receipts
    if case == "duplicate_answer":
        ts["answered"] = fmt_ist(t0 + timedelta(minutes=27))
    if case == "voice_call_dropped":
        ts["answered"] = ts["answered"] if accepted else None
    if case == "window_expired":
        ts["answered"] = None
        if channel == "web":
            ts["opened"] = None
    if case == "push_not_opened":
        ts["opened"] = None
        ts["answered"] = None
    if case == "survey_closed":
        # A tap one day after the survey already expired.
        ts["answered"] = fmt_ist(parse_ist(exp) + timedelta(days=1))

    # ---- recorded_at ----
    if case in ("push_not_opened", "window_expired"):
        recorded = exp
    elif case == "survey_closed":
        recorded = ts["answered"]
    elif case == "sheet_interrupted":
        recorded = fmt_ist(parse_ist(ts["answered"]) + timedelta(days=1))  # sent at next open
    elif undelivered or case == "voice_call_dropped":
        recorded = ts["answered"] or fmt_ist(t0 + timedelta(minutes=2))
    else:
        recorded = ts["answered"]

    # ---- sheet outcome (app/web only) ----
    sheet_outcome = None
    if channel in SHEET:
        sheet_outcome = (sheet_case or {}).get("sheet_outcome") or {
            "sheet_dismissed": "dismissed", "farmer_opted_out": "dismissed",
            "push_token_invalid": "never_opened", "client_cannot_render": "never_opened",
            "push_not_opened": "never_opened", "window_expired": "never_opened",
        }.get(case, "finished")

    # ---- farmerchat answer-store reply ----
    # The store only replies once answers are actually submitted. That happens when the
    # attempt is over (retry none / give_up) and at least one answer was accepted. A case
    # that will retry on the same channel (free_text) has not submitted yet, so no reply.
    reply = None
    if case == "duplicate_answer":
        reply = {"http_status": 200, "outcome": "duplicate"}
    elif case == "survey_replaced":
        reply = {"http_status": 404, "outcome": "unknown_flow"}
    elif stored and accepted and retry in ("none", "give_up"):
        reply = {"http_status": 201, "outcome": "accepted"}

    # ---- answered_by ----
    if case == "identity_mismatch":
        answered_by = "F-000999"
    elif undelivered or case in ("push_not_opened", "window_expired") or (case == "voice_call_dropped" and not accepted):
        answered_by = None
    else:
        answered_by = survey["farmer_id"]

    # ---- raw_event (channel event that is not an answer) ----
    raw_event = _raw_event(case, channel, sid, n)

    delivery_attempt = 3 if case == "voice_no_answer" else attempt
    late = stored and ts["answered"] is not None and parse_ist(ts["answered"]) > parse_ist(exp)

    rec = {
        "response_key": f"rk-{sid}-{channel}-{case}",
        "survey_id": sid, "farmer_id": survey["farmer_id"],
        "source_insight_ids": survey["source_insight_ids"],
        "channel": channel, "language": lang,
        "question_type": _question_type(survey),
        "status": status, "failure_code": code, "sheet_outcome": sheet_outcome,
        "answers": accepted if stored else {},
        "items": recs,
        "complete": len(accepted) == n and status in ("completed", "negative_outcome"),
        "delivery_attempt": delivery_attempt,
        "timestamps": ts, "recorded_at": recorded,
        "answered_by": answered_by,
        "raw_event": raw_event,
        "retry_decision": retry, "retry_after_minutes": retry_after,
        "counts_toward_cap": cap, "farmerchat_reply": reply,
        "needs_follow_up": bool(reasons) and stored,
        "follow_up_reasons": sorted(set(reasons)) if stored else [],
    }
    if _EMIT_LATE:
        rec["late"] = late
    return rec


def _question_type(survey: dict) -> str:
    """The grid labels every record of a survey with the survey's 'anchor' question type,
    the one named in outcome_codes.json -> grid_anchor. The three anchor surveys showcase
    one type each (S-21102 -> confirm, S-20931 -> single-select, S-21310 -> scale) and
    that label is not derivable from item composition alone (two anchors share the same
    item types), so we resolve it from grid_anchor via the anchor item's type.

    For any other survey we fall back to its richest item type (scale > single-select >
    confirm), which is the natural generalisation and keeps the field populated."""
    sid = survey["survey_id"]
    anchor = _anchor_question_types().get(sid)
    if anchor:
        return anchor
    types = {it["type"] for it in survey["items"]}
    if "survey-scale" in types:
        return "survey-scale"
    if "survey-single-select" in types:
        return "survey-single-select"
    return "survey-confirm"


def _anchor_question_types() -> dict:
    """survey_id -> question_type, read once from the pack's grid_anchor scenarios."""
    global _ANCHOR_QT
    if _ANCHOR_QT is None:
        from mel.data import load_scenario
        _ANCHOR_QT = {}
        for qtype, a in outcome_codes()["grid_anchor"].items():
            s = load_scenario(a["scenario"])["surveys"]["hi-IN"]
            _ANCHOR_QT[s["survey_id"]] = qtype
    return _ANCHOR_QT


_ANCHOR_QT: dict | None = None


def _anchor_item_id(survey: dict) -> str:
    """The item_id outcome_codes.json -> grid_anchor uses for this survey's question type.
    For a confirm survey that is q1; for single-select/scale it is q3. Falls back to the
    last item for any survey not covered by the anchor map."""
    qt = _question_type(survey)
    return outcome_codes()["grid_anchor"].get(qt, {}).get("item_id") or survey["items"][-1]["item_id"]


def _raw_event(case: str, channel: str, sid: str, n: int) -> str | None:
    """The human-readable channel event the reference records carry for some cases."""
    last = n
    table = {
        "client_cannot_render": "this version cannot show the survey sheet",
        "push_token_invalid": "push service: UNREGISTERED",
        "push_not_opened": "notification delivered, never tapped",
        "tg_bot_blocked": "Telegram 403: bot was blocked by the user",
        "wa_session_window_closed": "WhatsApp error 131047: more than 24 hours since the farmer's last message",
        "wa_undelivered": "WhatsApp status failed: 131026 message undeliverable",
        "voice_busy": "line busy",
        "voice_no_answer": "no answer on try 3 of 3",
        "voice_call_dropped": "call ended during the question",
    }
    if case in table:
        return table[case]
    if case == "farmer_opted_out":
        return {"app": "tapped Do not ask me again in the sheet",
                "web": "tapped Do not ask me again in the sheet",
                "whatsapp": "STOP", "telegram": "/stop",
                "voice": "pressed 9 at the opening (no more calls)"}[channel]
    if case == "farmer_declined":
        return {"whatsapp": f"{sid}|later", "telegram": f"mel|{sid}|later",
                "voice": "pressed 2 at the opening (not now)"}.get(channel)
    if case == "sheet_dismissed":
        return f"sheet swiped down at step 1 of {n}"
    if case == "sheet_closed_partway":
        return f"Close tapped at step {last} of {n}"
    if case == "sheet_interrupted":
        where = "app closed by the phone" if channel == "app" else "browser tab closed"
        kept = "Answers kept on the phone and sent at next open" if channel == "app" \
            else "Answers kept in the browser and sent at next visit"
        return f"{where} at step {last} of {n}. {kept}"
    return None


# --------------------------------------------------------------- hand-off simulation
# A persona says, per channel, what happens when the broadcaster tries that channel.
# "case" is any case simulate() understands; "unreachable" channels are skipped entirely
# (as the brief's broadcaster skips a channel the farmer cannot be reached on).
#
# The default persona answers on the first channel it is reachable on. Extra personas make
# the walk exercise fall-back and stop/continue handling without seeded randomness.
PERSONAS: dict[str, dict] = {
    # Answers completely on the very first channel tried.
    "default": {"per_channel": {}, "fallback_case": "completed", "unreachable": set()},
    # App push address is dead -> fall back; then completes on the next channel.
    "app_push_dead": {"per_channel": {"app": "push_token_invalid"},
                      "fallback_case": "completed", "unreachable": set()},
    # Never answers anywhere: every channel reports window_expired, so the walk runs to the end.
    "never_answers": {"per_channel": {}, "fallback_case": "window_expired", "unreachable": set()},
    # Opts out on the first channel -> the whole hand-off stops immediately.
    "opts_out_first": {"per_channel": {}, "fallback_case": "farmer_opted_out", "unreachable": set()},
    # Cannot be reached on voice at all (no phone): that channel is skipped.
    "no_voice": {"per_channel": {}, "fallback_case": "completed", "unreachable": {"voice"}},
}

# After a record, should the broadcaster move to the next channel, or stop?
_CONTINUE = {"fall_back_to_next_channel"}
_STOP = {"none", "give_up"}  # done, for good or ill
# retry_same_channel means try the same channel again; for a reproducible walk we treat a
# repeated same-channel failure as exhausted after one retry and then fall back.


def _case_for_channel(persona: dict, channel: str) -> str | None:
    """The case this persona produces on a channel, or None if unreachable."""
    if channel in persona["unreachable"]:
        return None
    return persona["per_channel"].get(channel, persona["fallback_case"])


def simulate_handoff(handoff: dict, persona: str = "default", seed: int = 0) -> list[dict]:
    """Walk a hand-off's channel_order the way the broadcaster would and return the answer
    records produced, one per channel actually attempted.

    Rules, following the brief and outcome_codes.json:
      * Try channels in channel_order. Skip a channel the persona cannot be reached on.
      * Every record is produced inside the send window and send hours by simulate(), which
        already stamps the right send time per channel; expiry is honoured because
        simulate() marks window_expired / survey_closed with the window's expires_at.
      * After each record, stop when retry_decision is none/give_up (the survey is finished
        on this channel, answered or declined), and move to the next channel when it is
        fall_back_to_next_channel. retry_same_channel retries once on the same channel and
        then falls back.
      * An opt-out (farmer_opted_out) stops the whole walk: the farmer gets nothing more.

    Deterministic and reproducible: the persona fixes behaviour; `seed` is accepted for
    interface compatibility and only used if a persona asks for a random pick (none do yet).
    """
    p = PERSONAS.get(persona)
    if p is None:
        raise ValueError(f"unknown persona {persona!r}; known: {sorted(PERSONAS)}")
    survey = handoff["survey"]
    records: list[dict] = []
    for step in handoff["channel_order"]:
        channel = step["channel"]
        case = _case_for_channel(p, channel)
        if case is None:
            continue  # broadcaster skips an unreachable channel
        attempts_left = 2  # one try, plus one retry_same_channel at most
        while attempts_left:
            rec = simulate(survey, channel, case, seed=seed, persona=persona)
            records.append(rec)
            decision = rec["retry_decision"]
            if rec["failure_code"] == "farmer_opted_out":
                return records  # stop everything, for good
            if decision in _STOP:
                # Finished on this channel, for good or ill (answered, declined, expired,
                # or a terminal invalid): the broadcaster does not try further channels.
                return records
            if decision == "retry_same_channel":
                attempts_left -= 1
                continue  # same channel again
            if decision in _CONTINUE:
                break  # move to the next channel in the order
            break
    return records


# ------------------------------------------------------- app/web "submit once" sheet
def simulate_sheet(survey: dict, channel: str, answered_item_ids: list[str],
                   closed: bool = False, submit_at: str | None = None, seed: int = 0) -> dict:
    """Model the brief's app/web bottom sheet: the farmer taps through the steps and the
    answers are submitted ONCE, when they finish or close the sheet, keeping whatever was
    answered so far. `channel` must be "app" or "web".

      answered_item_ids : the item_ids the farmer actually answered, in order. The sheet
                          submits exactly these; any later items are skipped (closed early)
                          or simply absent (finished with fewer answers).
      closed            : True if the farmer closed/swiped the sheet before the last step
                          (status partial, sheet_outcome closed_partway); False if they
                          went through to the end (completed/negative_outcome, finished).
      submit_at         : optional IST timestamp the submission happened at. If it is after
                          the survey's expires_at the record is flagged `late` (only emitted
                          when MEL_RESPONSE_LATE_FIELD=1; see the module docstring).

    Returns one response record, exactly as if a single submit call carried the answers.
    """
    if channel not in SHEET:
        raise ValueError(f"simulate_sheet is app/web only, not {channel!r}")
    items = survey["items"]
    ids = [it["item_id"] for it in items]
    answered = [i for i in answered_item_ids if i in ids]
    finished_all = len(answered) == len(items) and not closed
    case = "completed" if finished_all else "sheet_closed_partway"

    # Start from the persona's answers but keep only the ones the farmer gave.
    rec = simulate(survey, channel, case, seed=seed,
                   answers={i: _good_value(next(it for it in items if it["item_id"] == i)) for i in answered})

    # Trim to exactly the answered set (submit once, retaining given answers).
    keep = set(answered)
    new_items = []
    for it in items:
        if it["item_id"] in keep:
            new_items.append(next(r for r in rec["items"] if r["item_id"] == it["item_id"]))
        else:
            e = _blank(it)
            # Items the farmer saw but did not answer before closing are 'skipped';
            # items never shown are 'not_reached'. Everything after the last answered
            # step counts as not shown.
            last_answered_pos = max((ids.index(i) for i in answered), default=-1)
            e["result"] = "skipped" if ids.index(it["item_id"]) < last_answered_pos else \
                ("skipped" if (closed and ids.index(it["item_id"]) == last_answered_pos + 1) else "not_reached")
            if e["result"] == "skipped":
                e["attempts"] = 1
            new_items.append(e)
    rec["items"] = new_items
    rec["answers"] = {i: v for i, v in rec["answers"].items() if i in keep}
    rec["complete"] = finished_all and rec["status"] in ("completed", "negative_outcome")

    # One submission timestamp for the whole sheet.
    if submit_at:
        rec["timestamps"]["answered"] = submit_at
        rec["recorded_at"] = submit_at
        late = parse_ist(submit_at) > parse_ist(expires_at(survey["send_window"]))
        if late:
            # After expiry the brief says late answers are kept but marked; the sheet is
            # 'stale' from FarmerChat's point of view (survey_closed) yet the answers are
            # retained.
            if _EMIT_LATE:
                rec["late"] = True
    return rec
