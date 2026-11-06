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
import hashlib
from datetime import datetime, time, timedelta

from mel.config import IST, flag, outcome_codes
from mel.channels.render import choices, SPEECH_YES_NO
from mel.timing import parse_ist, fmt_ist, expires_at

SUCCESS_CASES = ("completed", "partial", "negative_outcome")
# Minutes after the window opens (07:00) that each channel first sends. app is first;
# whatsapp/telegram go an hour later; web and voice three hours later. Matches the grid.
SEND_OFFSET_H = {"app": 0, "web": 3, "whatsapp": 1, "telegram": 1, "voice": 3}
SHEET = ("app", "web")

# Whether the `late` flag may be written onto records. Off by default so records stay
# valid against today's response.schema.json; P1 adds the field, then this turns on.
_EMIT_LATE = flag("MEL_RESPONSE_LATE_FIELD")


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
    # A persona that sometimes reports the advice failed (see PERSONAS["sometimes_fails"]).
    # Other personas never reach this, so their records are unchanged.
    if reports_advice_failure(persona, sid, seed):
        bad = advice_failure_answer(items)
        if bad is not None:
            plan[items[bad[0]]["item_id"]] = bad[1]
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
        # A retry on the same channel gets its own key (suffix -a<attempt>), so attempt 2 never
        # overwrites attempt 1. First attempts keep the plain key the 183 reference records use.
        "response_key": f"rk-{sid}-{channel}-{case}" + (f"-a{attempt}" if attempt > 1 else ""),
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
    if _EMIT_LATE and late:
        # Only a late answer carries the field (`late: true`). Normal records never get
        # `late: false`, so they stay identical to the 183 reference records once the
        # optional field is in the schema.
        rec["late"] = True
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
    # Never answers anywhere: each channel is delivered but unanswered. The scheduler waits that
    # channel's wait_hours, then falls back to the next one, until the last channel or the send
    # window runs out. App's no-answer code is push_not_opened (window_expired is not an app
    # code in outcome_codes.json); every other channel reports window_expired.
    "never_answers": {"per_channel": {"app": "push_not_opened"}, "fallback_case": "window_expired",
                      "unreachable": set()},
    # Opts out on the first channel -> the whole hand-off stops immediately.
    "opts_out_first": {"per_channel": {}, "fallback_case": "farmer_opted_out", "unreachable": set()},
    # Cannot be reached on voice at all (no phone): that channel is skipped.
    "no_voice": {"per_channel": {}, "fallback_case": "completed", "unreachable": {"voice"}},
    # Answers on the first channel, but SOMETIMES says the advice did not work: on about a
    # quarter of surveys (`advice_fails` = 0.25) it picks the survey's advice_did_not_work answer,
    # which routes the record to the follow-up queue. Which surveys is fixed by
    # `reports_advice_failure()`: a hash of (seed, survey_id), so the same seed always gives the
    # same failures. `advice_fails_for` can list survey_ids that always fail (explicit scenario).
    "sometimes_fails": {"per_channel": {}, "fallback_case": "completed", "unreachable": set(),
                        "advice_fails": 0.25, "advice_fails_for": frozenset()},
}


def reports_advice_failure(persona_name: str, survey_id: str, seed: int = 0) -> bool:
    """Does this persona say the advice failed on this survey? Deterministic and independent of
    Python's per-process hash: sha256 of "seed:survey_id" read as a fraction in [0, 1),
    compared with the persona's `advice_fails` rate. A survey in `advice_fails_for` always fails.
    Personas without `advice_fails` never report failure (their behaviour is unchanged)."""
    p = PERSONAS.get(persona_name) or {}
    if survey_id in p.get("advice_fails_for", ()):
        return True
    rate = p.get("advice_fails")
    if not rate:
        return False
    digest = hashlib.sha256(f"{seed}:{survey_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64 < float(rate)


def is_late(record: dict, expires: str) -> bool:
    """Was this answer late? True when the record holds accepted answers and its answer time is
    strictly after `expires` (the hand-off's expires_at). Exactly at expiry is not late.

    Works with today's schema (no `late` field needed): lateness is derived from the record's
    own `timestamps.answered` and the hand-off. This is how P3 counts late answers until P1
    decides how a stored record marks them (docs/h4_schema_change_request_late.md)."""
    ts = (record.get("timestamps") or {}).get("answered")
    return bool(record.get("answers")) and ts is not None and parse_ist(ts) > parse_ist(expires)


def advice_failure_answer(items: list[dict]):
    """(index, value) of the survey's first answer that means "the advice did not work": an
    option whose follow_up is advice_did_not_work, or the follow-up threshold of a scale whose
    follow_up_reason is advice_did_not_work. None if the survey has no such answer."""
    for k, it in enumerate(items):
        if it["type"] == "survey-scale":
            if it.get("follow_up_reason") == "advice_did_not_work" and it.get("follow_up_at_or_below") is not None:
                return k, it["follow_up_at_or_below"]
            continue
        for o in it.get("options", []):
            if o.get("follow_up") == "advice_did_not_work":
                return k, o["value"]
    return None

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


def case_for_channel(persona_name: str, channel: str) -> str | None:
    """Public: the simulate() case a named persona produces on a channel, or None if the
    persona cannot be reached there (the broadcaster skips that channel). Lets the season
    scheduler drive one channel step at a time with the same persona behaviour that
    simulate_handoff() uses for a whole-walk."""
    p = PERSONAS.get(persona_name)
    if p is None:
        raise ValueError(f"unknown persona {persona_name!r}; known: {sorted(PERSONAS)}")
    return _case_for_channel(p, channel)


# Re-exported so the season driver can apply the same stop/continue rules per step.
STOP_DECISIONS = frozenset({"none", "give_up"})
CONTINUE_DECISIONS = frozenset({"fall_back_to_next_channel"})

# ------------------------------------------------------------ attempt timing (shared rules)
# Outcomes that mean "delivered, but no answer came". Per schedule_handoff.schema.json
# channel_order: "If no answer comes within wait_hours, try the next." So on a channel that
# is not the last, these fall back after that channel's wait_hours instead of giving up.
NO_ANSWER_CODES = frozenset({"window_expired", "push_not_opened"})
# One try plus one retry on the same channel, then fall back (as simulate_handoff always did).
MAX_ATTEMPTS_PER_CHANNEL = 2


def next_step(handoff: dict, channel: str, attempt: int, record: dict):
    """What the broadcaster does after `record`, and how long it waits first.

    Returns (action, delay): action is "stop", "retry" (same channel) or "fallback" (next
    channel); delay is a timedelta, or None for "stop".
      * opt-out, or a none/give_up outcome that is not a no-answer -> stop.
      * retry_same_channel -> retry after retry_after_minutes, at most
        MAX_ATTEMPTS_PER_CHANNEL tries on one channel; then fall back.
      * fall_back_to_next_channel -> fall back after retry_after_minutes (these are delivery
        failures: the farmer never got the survey, so there is no answer to wait for).
      * a no-answer outcome (NO_ANSWER_CODES) -> fall back after the channel's wait_hours. The
        last channel has wait_hours null, so there it stops.
    """
    if record.get("failure_code") == "farmer_opted_out":
        return "stop", None
    decision = record["retry_decision"]
    after = timedelta(minutes=record.get("retry_after_minutes") or 0)
    if decision == "retry_same_channel":
        return ("retry", after) if attempt < MAX_ATTEMPTS_PER_CHANNEL else ("fallback", after)
    if decision in CONTINUE_DECISIONS:
        return "fallback", after
    if record.get("failure_code") in NO_ANSWER_CODES:
        wait = next((s.get("wait_hours") for s in handoff["channel_order"] if s["channel"] == channel), None)
        return ("fallback", timedelta(hours=wait)) if wait else ("stop", None)
    return "stop", None


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def earliest_send(handoff: dict, when: datetime):
    """The first instant at or after `when` that a send is allowed, or None if there is none.

    A send must be inside the day's send_hours and inside the send window
    [not_before, not_after] (schedule_handoff.schema.json: "The scheduler must not send
    outside it"). A time after send hours moves to the next day's opening hour. If that lands
    after not_after (or after expires_at), no further send is possible: None."""
    sh = handoff["send_hours"]
    start, end = _hm(sh["from"]), _hm(sh["to"])
    when = when.astimezone(IST)
    nb = parse_ist(handoff["send_window"]["not_before"])
    if when < nb:
        when = nb
    t = when.time().replace(tzinfo=None)
    if t < start:
        when = datetime.combine(when.date(), start, IST)
    elif t > end:
        when = datetime.combine(when.date() + timedelta(days=1), start, IST)
    if when > parse_ist(handoff["send_window"]["not_after"]) or when > parse_ist(handoff["expires_at"]):
        return None
    return when


def simulate_handoff(handoff: dict, persona: str = "default", seed: int = 0,
                     reachability=None) -> list[dict]:
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
    # Channels in channel_order the farmer can be reached on; order preserved. A channel is
    # skipped when the persona cannot be reached there, or when farmer data (an optional
    # mel.channels.FarmerReachability) explicitly says so. No data means reachable.
    def ok(ch):
        if reachability is not None and not reachability.reachable(survey["farmer_id"], ch):
            return False
        return _case_for_channel(p, ch) is not None
    reachable = [s["channel"] for s in handoff["channel_order"] if ok(s["channel"])]
    records: list[dict] = []
    send_at = None  # first attempt: the window opening plus the channel's usual offset
    for i, channel in enumerate(reachable):
        case = _case_for_channel(p, channel)
        attempt = 1
        while True:
            rec = simulate(survey, channel, case, seed=seed, persona=persona, attempt=attempt,
                           send_at=fmt_ist(send_at) if send_at else None)
            records.append(rec)
            action, delay = next_step(handoff, channel, attempt, rec)
            if action == "stop":
                return records  # answered, declined, opted out, or nothing left to try
            if action == "fallback" and i == len(reachable) - 1:
                return records  # no reachable channel left to fall back to
            # The next attempt waits `delay`, then must fit send hours and the send window.
            nxt = earliest_send(handoff, parse_ist(rec["timestamps"]["sent"]) + delay)
            if nxt is None:
                return records  # the send window closes before the next attempt
            send_at = nxt
            if action == "retry":
                attempt += 1
                continue
            break  # fall back to the next reachable channel
    return records


# ------------------------------------------------------- app/web "submit once" sheet
def simulate_sheet(survey: dict, channel: str, answered_item_ids: list[str],
                   closed: bool = False, submit_at: str | None = None, seed: int = 0,
                   answers: dict | None = None) -> dict:
    """Model the brief's app/web bottom sheet: the farmer taps through the steps and the
    answers are submitted ONCE, when they finish or close the sheet, keeping whatever was
    answered so far. `channel` must be "app" or "web".

      answered_item_ids : the item_ids the farmer actually answered, in order. The sheet
                          submits exactly these; any later items are skipped (closed early)
                          or simply absent (finished with fewer answers).
      closed            : True if the farmer closed/swiped the sheet before the last step
                          (status partial, sheet_outcome closed_partway); False if they
                          went through to the end (completed/negative_outcome, finished).
      answers           : optional {item_id: value} the farmer actually tapped (the Survey Studio
                          tap-through passes them). Answered items without a value here get the
                          persona's answer, as before.
      submit_at         : optional IST timestamp the submission happened at. If it is after
                          the survey's expires_at the answers are still kept, and the record is
                          flagged `late: true` (only emitted when MEL_RESPONSE_LATE_FIELD=1,
                          because response.schema.json has no `late` field yet). An answer
                          exactly at expires_at is not late.

    Answered items may skip a middle question (q1 and q3): every given answer is kept. Items
    before the last answered one that were not answered are `skipped`; the step showing when
    the farmer closed is `skipped`; later steps are `not_reached`.

    Raises ValueError for input that cannot be submitted unambiguously: an unknown item_id, the
    same item_id twice, or closed=True with every item answered (that is a finished sheet).

    Returns one response record, exactly as if a single submit call carried the answers.
    """
    if channel not in SHEET:
        raise ValueError(f"simulate_sheet is app/web only, not {channel!r}")
    items = survey["items"]
    ids = [it["item_id"] for it in items]
    given = list(answered_item_ids)
    unknown = [i for i in given if i not in ids]
    if unknown:
        raise ValueError(f"unknown item_id(s) {unknown}; the survey has {ids}")
    if len(set(given)) != len(given):
        raise ValueError(f"item_id answered twice in {given}; a sheet submits each answer once")
    if closed and len(given) == len(ids):
        raise ValueError("closed=True but every item was answered: that is a finished sheet (closed=False)")
    answered = [i for i in ids if i in set(given)]          # item order, whatever the tap order
    n, all_answered = len(items), len(answered) == len(items)

    values = {i: (answers or {}).get(i, _good_value(items[ids.index(i)])) for i in answered}
    # Every answered entry is encoded exactly as a full submission would encode it.
    full = simulate(survey, channel, "completed", seed=seed, answers=values)

    if all_answered:
        rec = full                                           # finished: completed / negative_outcome
    else:
        # Fields that describe the attempt (keys, timestamps, retry, cap) come from the matching
        # case; the items and answers come from what the farmer actually gave.
        rec = simulate(survey, channel, "sheet_closed_partway" if closed else "partial", seed=seed, answers=values)
        last = max((ids.index(i) for i in answered), default=-1)
        new_items = []
        for k, it in enumerate(items):
            if it["item_id"] in values:
                new_items.append(next(e for e in full["items"] if e["item_id"] == it["item_id"]))
                continue
            e = _blank(it)
            if k < last or (closed and k == last + 1):
                e.update(result="skipped", attempts=1)       # shown but not answered
            new_items.append(e)
        reasons = sorted({r for i in answered if (r := _follow_up(items[ids.index(i)], values[i]))})
        rec.update(
            items=new_items,
            answers={i: full["answers"][i] for i in answered},
            status="negative_outcome" if reasons else "partial",
            complete=False,
            needs_follow_up=bool(reasons),
            follow_up_reasons=reasons,
            sheet_outcome="closed_partway" if closed else "finished",
            raw_event=f"Close tapped at step {min(last + 2, n)} of {n}" if closed else None,
            farmerchat_reply={"http_status": 201, "outcome": "accepted"} if answered else None,
        )

    # One submission timestamp for the whole sheet.
    if submit_at:
        rec["timestamps"]["answered"] = submit_at
        rec["recorded_at"] = submit_at
    rec.pop("late", None)
    at = parse_ist(rec["timestamps"]["answered"]) if rec["timestamps"].get("answered") else None
    if _EMIT_LATE and answered and at is not None and at > parse_ist(expires_at(survey["send_window"])):
        rec["late"] = True                                   # kept, and marked late
    return rec
