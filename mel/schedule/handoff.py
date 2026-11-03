"""Builds schedule_handoff.json from an insight + survey. Owner: P4."""
import uuid
from datetime import timedelta

from mel.config import rules
from mel.timing import expires_at, parse_ist, fmt_ist

NS = uuid.UUID("6f1c2b8e-5d0a-4c1e-9f3a-2b7d8e9a0c11")  # project namespace for stable ids


def priority(insight: dict) -> str:
    p = rules()["priority"]
    if (insight.get("resolution_type") in p["high_if_resolution"]
            or insight.get("severity") in p["high_if_severity"]
            or insight.get("behavioral_intent") in p["high_if_behavioral_intent"]):
        return "high"
    if insight.get("resolution_type") in p["low_if_resolution"]:
        return "low"
    return "normal"


def channel_order(insight: dict, prio: str) -> list[dict]:
    order: list[str] = []
    add = lambda c: c and c not in order and order.append(c)
    add(insight.get("preferred_channel"))
    add(rules()["channel_by_method"].get((insight.get("verification") or {}).get("method") or "none"))
    add("whatsapp")
    if prio == "high":
        add("voice")
    wait = rules()["wait_hours_by_priority"][prio]
    return [{"channel": c, "wait_hours": wait if i < len(order) - 1 else None} for i, c in enumerate(order)]


def build_handoff(insight: dict, survey: dict) -> dict:
    r = rules()
    prio = priority(insight)
    sid = survey["survey_id"]
    flow_key = r["farmerchat_flow"]["flow_key"].format(survey_id_lower=sid.lower().replace("-", "_"))
    created = parse_ist(insight["created_at"]).replace(hour=23, minute=0, second=0)
    return {
        "handoff_id": "H-" + sid.split("-", 1)[1],
        "created_at": fmt_ist(created),
        "survey": survey,
        "send_window": survey["send_window"],
        "send_hours": dict(r["send_hours"]),
        "channel_order": channel_order(insight, prio),
        "frequency_cap": {
            "key": r["frequency_cap"]["key"].format(farmer_id=insight["farmer_id"]),
            "max_surveys": r["frequency_cap"]["max_surveys"],
            "window_days": r["frequency_cap"]["window_days"],
            "exempt": prio in r["frequency_cap"]["exempt_priority"],
        },
        "priority": prio,
        "expires_at": expires_at(survey["send_window"]),
        "farmerchat_flow": {
            "org_id": r["farmerchat_flow"]["org_id"],
            "flow_key": flow_key,
            "version": r["farmerchat_flow"]["version"],
            "campaign_id": str(uuid.uuid5(NS, r["farmerchat_flow"]["campaign_name"])),
            "flow_id": str(uuid.uuid5(NS, flow_key)),
        },
    }


class OptOutList:
    """Farmers who asked for no more surveys (Do not ask me again, STOP, /stop, or 9 on a call). Owner: P4.
    The brief: 'Stop all future surveys to this farmer.' Feed it every answer record; check it before sending.
    TODO(P4): persist across runs (a file now; a database such as DynamoDB if this ever goes to AWS)."""

    def __init__(self):
        self._farmers: set[str] = set()

    def record(self, response: dict) -> None:
        if response.get("failure_code") == "farmer_opted_out":
            self._farmers.add(response["farmer_id"])

    def blocks(self, handoff_or_farmer) -> bool:
        fid = handoff_or_farmer if isinstance(handoff_or_farmer, str) else handoff_or_farmer["survey"]["farmer_id"]
        return fid in self._farmers


class CapLedger:
    """Per-farmer 1-survey-per-7-days cap across all surveys and channels. Owner: P4.
    TODO(P4): decide whether a capped normal/low survey is dropped or shifted to the next free day."""

    def __init__(self):
        self._sent: dict[str, list] = {}

    def allow(self, handoff: dict) -> bool:
        cap = handoff["frequency_cap"]
        start = parse_ist(handoff["send_window"]["not_before"])
        recent = [t for t in self._sent.get(cap["key"], []) if abs((start - t).days) < cap["window_days"]]
        ok = cap["exempt"] or len(recent) < cap["max_surveys"]
        if ok:
            self._sent.setdefault(cap["key"], []).append(start)
        return ok
