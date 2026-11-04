"""End-to-end glue: insight -> decision -> surveys -> hand-off. Owner: P1 (integration lead).
Keep this thin: each step lives in its owner's package."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from mel.config import CHANNELS, LANGS
from mel.decision import decide
from mel.schedule import build_handoff
from mel.timing import chat_hours
from mel.writer import write_surveys

RULE_IDS = tuple(f"R{n}" for n in range(1, 9))
PRIORITIES = ("high", "normal", "low")


def clean(survey: dict) -> dict:
    return {k: v for k, v in survey.items() if not k.startswith("_")}


def run_insight(insight: dict, farmer: dict | None = None, history_hours=()) -> dict:
    """Returns {'decision', 'no_survey'} or {'decision', 'surveys', 'handoff'} (hand-off in farmer's language).
    `farmer` (farmers.csv row) and `history_hours` only refine decision.send_time, P2's recommended send time.
    The hand-off file cannot carry it (the organisers' schema forbids extra fields); senders read it from the decision."""
    d = decide(insight, farmer, history_hours)
    if not d.survey:
        return {"decision": d, "no_survey": d.no_survey_record(insight)}
    surveys = write_surveys(insight, d.send_window)
    lang = insight.get("conversation_language", "hi-IN")
    farmer_copy = clean(surveys.get(lang) or surveys["hi-IN"])
    return {"decision": d, "surveys": surveys, "handoff": build_handoff(insight, farmer_copy)}


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


def run_pipeline(insights: list[dict], limit: int | None = None, farmer: str | None = None,
                 farmers: dict[str, dict] | None = None) -> PipelineResult:
    """Run the filtered batch through ``run_insight``. Pure: it writes nothing, so the CLI (or
    a test) decides where output goes. Order follows the input, so two runs give equal results.
    `farmers` (load_farmers()) and each farmer's earlier chats in `insights`, including rows the
    filter left out, feed P2's recommended send time."""
    chosen = select_insights(insights, limit=limit, farmer=farmer)
    farmers = farmers or {}
    by_farmer = defaultdict(list)
    for i in insights:
        if isinstance(i, dict):
            by_farmer[i.get("farmer_id")].append(i)
    outputs = [run_insight(i, farmers.get(i.get("farmer_id")),
                           chat_hours(by_farmer[i.get("farmer_id")], i.get("farmer_id"), i.get("created_at")))
               for i in chosen]
    return PipelineResult(insights=chosen, outputs=outputs, rows_read=len(insights))
