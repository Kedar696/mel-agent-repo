"""Simulated farmer answers -> response.schema.json records. Owner: P7.

simulate(survey, channel, case) where case is a success case (completed / partial / negative_outcome),
a sheet case (sheet_closed_partway / sheet_interrupted, app+web) or any failure code in
config/rules/outcome_codes.json. Compare with data/mock/outcomes/ for the reference grid.
"""
import random
from datetime import timedelta

from mel.config import outcome_codes
from mel.channels.render import choices
from mel.timing import parse_ist, fmt_ist

SUCCESS_CASES = ("completed", "partial", "negative_outcome")
SEND_OFFSET_H = {"app": 0, "web": 3, "whatsapp": 1, "telegram": 1, "voice": 3}
SHEET = ("app", "web")


def cases_for(channel: str) -> list[str]:
    oc = outcome_codes()
    na = oc.get("not_applicable", {})
    out = ["completed", "negative_outcome"]
    out += list(oc["sheet_cases"]) if channel in SHEET else ["partial"]
    out += [k for k, v in oc["failures"].items() if channel in v["channels"] and f"{channel}/{k}" not in na]
    return out


def _raw(channel, sid, iid, value, idx):
    if channel in SHEET:
        return str(value), "sheet_tap"
    if channel == "whatsapp":
        return f"{sid}|{iid}|{value}", "button_reply"
    if channel == "telegram":
        return f"mel|{sid}|{iid}|{value}", "callback_data"
    return str(idx), "keypad"


def _follow_up(item, value):
    if item["type"] == "survey-scale":
        lim = item.get("follow_up_at_or_below")
        return item.get("follow_up_reason") if lim is not None and value <= lim else None
    return next((o.get("follow_up") for o in item["options"] if o["value"] == value), None)


def _pick(item, rnd, want_bad: bool | None):
    ch = choices(item)
    bad = [(i, v) for i, (_, v) in enumerate(ch, 1) if _follow_up(item, v)]
    good = [(i, v) for i, (_, v) in enumerate(ch, 1) if not _follow_up(item, v)]
    pool = bad if want_bad and bad else good if want_bad is False and good else list(enumerate((v for _, v in ch), 1))
    return rnd.choice(pool)


def simulate(survey: dict, channel: str, case: str = "completed", seed: int = 0,
             answers: dict | None = None, attempt: int = 1) -> dict:
    rnd = random.Random(f"{survey['survey_id']}{channel}{case}{seed}")
    oc = outcome_codes()
    fail = oc["failures"].get(case)
    sheet_case = oc["sheet_cases"].get(case)
    sid, items = survey["survey_id"], survey["items"]

    t0 = parse_ist(survey["send_window"]["not_before"]) + timedelta(hours=SEND_OFFSET_H[channel])
    ts = {"sent": fmt_ist(t0), "delivered": fmt_ist(t0 + timedelta(minutes=1)),
          "opened": fmt_ist(t0 + timedelta(minutes=20)), "answered": fmt_ist(t0 + timedelta(minutes=25))}

    # Which items get answered, and whether to push toward a follow-up answer.
    n = len(items)
    answered_upto = {"partial": max(1, n - 1), "sheet_closed_partway": max(1, n - 1),
                     "sheet_interrupted": max(1, n - 1)}.get(case, n)
    if case in SUCCESS_CASES or sheet_case:
        mode = "ok"
    elif case in ("voice_call_dropped", "free_text_instead_of_choice", "keypad_out_of_range", "speech_not_understood"):
        mode = "breaks_last"  # earlier items answered, last item fails
    elif case in ("survey_closed", "survey_replaced", "duplicate_answer", "identity_mismatch"):
        mode = "discarded"
    else:
        mode = "none"

    recs, accepted, reasons = [], {}, []
    for k, it in enumerate(items):
        entry = {"item_id": it["item_id"], "item_type": it["type"], "result": "not_reached",
                 "value": None, "raw_input": None, "input_kind": None, "attempts": 0}
        last = k == n - 1
        if mode in ("ok", "breaks_last") and not (mode == "breaks_last" and last) and k < answered_upto:
            if answers and it["item_id"] in answers:
                v = answers[it["item_id"]]
                idx = next(i for i, (_, cv) in enumerate(choices(it), 1) if cv == v)
            else:
                idx, v = _pick(it, rnd, want_bad=(True if case == "negative_outcome" and k == 0 else False))
            raw, kind = _raw(channel, sid, it["item_id"], v, idx)
            entry.update(result="answered", value=v, raw_input=raw, input_kind=kind, attempts=1)
            accepted[it["item_id"]] = v
            if fu := _follow_up(it, v):
                reasons.append(fu)
        elif mode in ("ok",) and k >= answered_upto:
            entry.update(result="skipped", attempts=1)
        elif mode == "breaks_last" and last:
            if case == "voice_call_dropped":
                pass  # not reached
            else:
                raw, kind = {"free_text_instead_of_choice": ("पता नहीं, कल बताऊँगा", "free_text"),
                             "keypad_out_of_range": ("9" if channel == "voice" else "x", "keypad"),
                             "speech_not_understood": ("हम्म... शायद", "speech")}[case]
                entry.update(result="invalid", raw_input=raw, input_kind=kind,
                             attempts=1 if case == "free_text_instead_of_choice" else 2)
        elif mode == "discarded" and last:
            idx, v = _pick(it, rnd, want_bad=False)
            raw, kind = _raw(channel, sid, it["item_id"], v, idx)
            entry.update(result="discarded", value=v, raw_input=raw, input_kind=kind, attempts=1)
        recs.append(entry)

    if case == "sheet_dismissed":
        recs[0].update(result="skipped", attempts=1)

    if fail:
        status, code = fail["status"], case
        retry, retry_after, cap = fail["retry_decision"], fail["retry_after_minutes"], fail["counts_toward_cap"]
    elif sheet_case:
        status, code = "negative_outcome" if reasons else sheet_case["status"], None
        retry, retry_after, cap = "none", None, True
    else:
        status = "negative_outcome" if reasons else ("completed" if len(accepted) == n else "partial")
        code, retry, retry_after, cap = None, "none", None, True

    undelivered = status == "delivery_failed" and case != "voice_call_dropped"
    if undelivered:
        ts.update(delivered=None, opened=None, answered=None)
    if case in ("window_expired", "push_not_opened", "voice_call_dropped"):
        ts["answered"] = fmt_ist(t0 + timedelta(minutes=25)) if accepted else None
    if case == "push_not_opened" or (case == "window_expired" and channel == "web"):
        ts["opened"] = None
    if channel == "telegram":
        ts["opened"] = None  # no read receipts

    sheet_outcome = None
    if channel in SHEET:
        sheet_outcome = (sheet_case or {}).get("sheet_outcome") or {
            "sheet_dismissed": "dismissed", "farmer_opted_out": "dismissed", "push_token_invalid": "never_opened",
            "client_cannot_render": "never_opened", "push_not_opened": "never_opened", "window_expired": "never_opened",
        }.get(case, "finished")

    sent_to_store = bool(accepted) and status not in ("stale", "duplicate", "identity_mismatch") or case in ("survey_replaced", "duplicate_answer")
    reply = None
    if sent_to_store:
        reply = {"survey_replaced": {"http_status": 404, "outcome": "unknown_flow"},
                 "duplicate_answer": {"http_status": 200, "outcome": "duplicate"}}.get(case, {"http_status": 201, "outcome": "accepted"})

    return {
        "response_key": f"rk-{sid}-{channel}-{case}-{attempt}",
        "survey_id": sid, "farmer_id": survey["farmer_id"], "source_insight_ids": survey["source_insight_ids"],
        "channel": channel, "language": survey["language"],
        "status": status, "failure_code": code, "sheet_outcome": sheet_outcome,
        "answers": accepted if status not in ("stale", "duplicate", "identity_mismatch") else {},
        "items": recs, "complete": len(accepted) == n and status in ("completed", "negative_outcome"),
        "delivery_attempt": 3 if case == "voice_no_answer" else attempt,
        "timestamps": ts, "recorded_at": ts["answered"] or fmt_ist(t0 + timedelta(minutes=2)),
        "answered_by": None if undelivered or case in ("push_not_opened", "window_expired") else
                       ("F-000999" if case == "identity_mismatch" else survey["farmer_id"]),
        "raw_event": None, "retry_decision": retry, "retry_after_minutes": retry_after,
        "counts_toward_cap": cap, "farmerchat_reply": reply,
        "needs_follow_up": bool(reasons) and status not in ("stale", "duplicate", "identity_mismatch"),
        "follow_up_reasons": sorted(set(reasons)) if status not in ("stale", "duplicate", "identity_mismatch") else [],
    }
