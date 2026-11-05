"""End-to-end glue: insight -> decision -> surveys -> hand-off. Owner: P1 (integration lead).
Keep this thin: each step lives in its owner's package."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from mel.config import CHANNELS, LANGS
from mel.decision import decide
from mel.schedule import build_handoff
from mel.schedule.handoff import priority as _brief_priority
from mel.timing import chat_hours
from mel.timing.window import parse_ist as _parse_ist
from mel.writer import write_surveys

RULE_IDS = tuple(f"R{n}" for n in range(1, 9))
PRIORITIES = ("high", "normal", "low")
ATTENTION_TIERS = ("surge", "neutral", "steady_high")
ATTENTION_REASONS = ("insufficient_history", "quiet_then_high_weight", "activity_jump", "declining", "none")


def clean(survey: dict) -> dict:
    return {k: v for k, v in survey.items() if not k.startswith("_")}


def run_insight(insight: dict, farmer: dict | None = None, history_hours=(), memory=None,
                attention: dict | None = None) -> dict:
    """Returns {'decision', 'no_survey'} or {'decision', 'surveys', 'handoff'} (hand-off in farmer's language).
    `farmer` (farmers.csv row) and `history_hours` only refine decision.send_time, P2's recommended send time.
    The hand-off file cannot carry it (the organisers' schema forbids extra fields); senders read it from the decision.
    `memory` (mel.writer.FarmerMemory) turns on P4's history rules H1-H4, which adapt the questions.
    `attention` (mel.data.activity, off by default) adjusts priority (P3), question count (P4) and send time (P2);
    it never changes survey vs no-survey, the rule, or the send window. When None, behaviour is exactly today's."""
    d = decide(insight, farmer, history_hours, attention)
    if not d.survey:
        return {"decision": d, "no_survey": d.no_survey_record(insight)}
    surveys = write_surveys(insight, d.send_window, memory=memory, attention=attention)
    lang = insight.get("conversation_language", "hi-IN")
    farmer_copy = clean(surveys.get(lang) or surveys["hi-IN"])
    return {"decision": d, "surveys": surveys, "handoff": build_handoff(insight, farmer_copy, attention)}


def select_insights(insights: list[dict], limit: int | None = None, farmer: str | None = None) -> list[dict]:
    """Narrow a batch for a focused run: one farmer first, then the first ``limit`` rows of that."""
    if limit is not None and limit < 0:
        raise ValueError(f"limit must be 0 or more, got {limit}")
    rows = [i for i in insights if i.get("farmer_id") == farmer] if farmer else list(insights)
    return rows if limit is None else rows[:limit]


@dataclass
class PipelineResult:
    """What a batch run produced, in input order. Same input gives an equal result."""
    insights: list[dict] = field(default_factory=list)   # the rows that were processed
    outputs: list[dict] = field(default_factory=list)    # run_insight() result per row, same order
    rows_read: int = 0                                   # rows given to run_pipeline before filtering

    @property
    def rows_processed(self) -> int:
        return len(self.insights)

    def counts(self) -> dict:
        """Counts for run_summary.json. Rules cover every row processed; language, first channel
        and priority describe the hand-offs, so they only count rows that got a survey."""
        by_rule = Counter({r: 0 for r in RULE_IDS})
        by_lang = Counter({lang: 0 for lang in LANGS})
        by_channel = Counter({c: 0 for c in CHANNELS})
        by_priority = Counter({p: 0 for p in PRIORITIES})
        for out in self.outputs:
            by_rule[out["decision"].rule] += 1
            h = out.get("handoff")
            if h:
                by_lang[h["survey"]["language"]] += 1
                by_channel[h["channel_order"][0]["channel"]] += 1
                by_priority[h["priority"]] += 1
        return {"by_rule": dict(by_rule), "by_language": dict(by_lang),
                "by_first_channel": dict(by_channel), "by_priority": dict(by_priority)}

    def attention_counts(self) -> dict:
        """Counts by attention tier and reason, over every processed row that carries an attention result.
        Added to run_summary.json ONLY when attention is on (see cmd_run), so the off path is unchanged."""
        by_tier = Counter({t: 0 for t in ATTENTION_TIERS})
        by_reason = Counter({r: 0 for r in ATTENTION_REASONS})
        for out in self.outputs:
            att = getattr(out["decision"], "attention", None)
            if att:
                by_tier[att["tier"]] += 1
                by_reason[att["reason"]] += 1
        return {"by_tier": dict(by_tier), "by_reason": dict(by_reason)}


def _attention_by_insight_id(insights: list[dict]) -> dict[str, dict]:
    """Compute each insight's attention result from the UNFILTERED set, then apply the once-per-7-days
    `activity_jump -> high` promotion budget per farmer. Returns {insight_id: attention_dict}.

    The budget is decided HERE, not in a send/admit loop, because `mel.cli run` never uses CapLedger. We walk
    every usable insight grouped by farmer in created_at order (insight_id as a stable tiebreak), so the result
    is independent of input order, --farmer and --limit. A promotion to `high` whose cause is `activity_jump`
    and whose brief priority is `normal` is allowed only if no earlier allowed such promotion for that farmer is
    within 7 days; otherwise its attention is marked high_budget="spent" so adjust_priority stops at normal.
    `quiet_then_high_weight` surges and brief-high surveys are never budgeted."""
    from mel.data.activity import ActivityHistory, with_high_budget_spent

    usable = [i for i in insights if isinstance(i, dict)]
    hist = ActivityHistory(usable)
    window = timedelta(days=hist.cfg["high_promotion_window_days"])

    # Group by farmer, ordered by created_at then insight_id (stable, order-independent).
    def _sort_key(i):
        try:
            t = _parse_ist(i["created_at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            t = None
        return (t is None, t, i.get("insight_id") or "")

    per_farmer: dict[str, list] = defaultdict(list)
    for i in usable:
        if i.get("farmer_id") and i.get("insight_id"):
            per_farmer[i["farmer_id"]].append(i)

    result: dict[str, dict] = {}
    for fid, rows in per_farmer.items():
        last_promoted = None  # created_at of the last allowed activity_jump->high for this farmer
        for i in sorted(rows, key=_sort_key):
            att = hist.attention_for(i)
            # Only a row that actually becomes a survey may use the 7-day high promotion. A no-survey chat never
            # spends the budget and never blocks a later real survey from being promoted within the same window.
            if att.reason == "activity_jump" and _brief_priority(i) == "normal" and decide(i).survey:
                try:
                    t = _parse_ist(i["created_at"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    t = None
                if t is not None and last_promoted is not None and (t - last_promoted) < window:
                    att = with_high_budget_spent(att)   # budget spent: stays normal
                elif t is not None:
                    last_promoted = t                   # this one gets the high slot
            result[i["insight_id"]] = att.as_dict()
    return result


def run_pipeline(insights: list[dict], limit: int | None = None, farmer: str | None = None,
                 farmers: dict[str, dict] | None = None, history: bool = False,
                 attention: bool = False) -> PipelineResult:
    """Run the filtered batch through ``run_insight``. Pure: it writes nothing, so the CLI (or
    a test) decides where output goes. Order follows the input, so two runs give equal results.
    `farmers` (load_farmers()) and each farmer's earlier chats in `insights`, including rows the
    filter left out, feed P2's recommended send time.
    `history=True` builds a FarmerMemory from all `insights` + `farmers` and turns on P4's history rules
    (team default 4 Nov: on in the app, off for scoring and the CLI).
    `attention=True` turns on activity attention (team default: on in the app, off for scoring and the CLI).
    Its per-insight result is computed from the UNFILTERED `insights` and the 7-day high-promotion budget is
    applied there, so a farmer's result is identical in a filtered (--farmer/--limit) and a full run."""
    chosen = select_insights(insights, limit=limit, farmer=farmer)
    farmers = farmers or {}
    by_farmer = defaultdict(list)
    for i in insights:
        if isinstance(i, dict):
            by_farmer[i.get("farmer_id")].append(i)
    memory = None
    if history:
        from mel.writer import FarmerMemory
        memory = FarmerMemory([i for i in insights if isinstance(i, dict)], farmers)
    att_by_id = _attention_by_insight_id(insights) if attention else {}
    outputs = [run_insight(i, farmers.get(i.get("farmer_id")),
                           chat_hours(by_farmer[i.get("farmer_id")], i.get("farmer_id"), i.get("created_at")),
                           memory, att_by_id.get(i.get("insight_id")))
               for i in chosen]
    return PipelineResult(insights=chosen, outputs=outputs, rows_read=len(insights))
