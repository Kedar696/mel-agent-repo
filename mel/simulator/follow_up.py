"""Follow-up tickets from simulated answer records. Owner: P3 (producer side).

The follow-up queue (P5's Follow-up tab, `app/streamlit_app.py` `_follow_queue`) takes an answer
record when `needs_follow_up` is true and files one ticket per record, keyed by the first answer
that triggered it (its `follow_up` reason). Today that tab forces each survey's first flagged
answer itself, because no P3 persona ever reported a failure. `follow_up_tickets()` applies the
same rule to real simulated records, so the queue can be fed by what a persona actually answered
(for example `PERSONAS["sometimes_fails"]`), instead of a forced answer.

Ticket fields match the ones the tab already shows: response_key, farmer_id, survey_id, channel,
recorded_at, reason, item_id, value, rec. Ids only; no farmer contact details.
"""


def _trigger(item: dict, value):
    """The follow_up reason this answer carries on this item, or None."""
    if item["type"] == "survey-scale":
        lim = item.get("follow_up_at_or_below")
        return item.get("follow_up_reason") if lim is not None and value is not None and value <= lim else None
    return next((o.get("follow_up") for o in item.get("options", []) if o["value"] == value), None)


def follow_up_tickets(records, surveys) -> list[dict]:
    """One ticket per record that needs follow-up, in record order.

      records : simulated response records (from simulate, simulate_handoff, run_batch, ...).
      surveys : {survey_id: survey}, to find which item and answer triggered the follow-up.

    A record goes in only if `needs_follow_up` is true, which the simulator sets only for stored,
    accepted answers that carry a follow-up reason. The ticket's reason is the first such
    answer's (question order), the same choice the Follow-up tab makes."""
    tickets = []
    for rec in records:
        if not rec.get("needs_follow_up"):
            continue
        survey = surveys[rec["survey_id"]]
        for item in survey["items"]:
            value = rec["answers"].get(item["item_id"])
            reason = _trigger(item, value) if item["item_id"] in rec["answers"] else None
            if reason:
                tickets.append({"response_key": rec["response_key"], "farmer_id": rec["farmer_id"],
                                "survey_id": rec["survey_id"], "channel": rec["channel"],
                                "recorded_at": rec["recorded_at"], "reason": reason,
                                "item_id": item["item_id"], "value": value, "rec": rec})
                break
    return tickets
