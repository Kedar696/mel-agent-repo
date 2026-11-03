"""P5/P6: every survey we write is schema-valid and passes guardrails, in both languages."""
from mel.data import load_insights
from mel.decision import decide
from mel.writer import write_surveys, check_survey
from mel.pipeline import clean


def test_all_surveys_pass_guards():
    n = 0
    for i in load_insights():
        d = decide(i)
        if d.survey:
            for s in write_surveys(i, d.send_window).values():
                assert check_survey(clean(s)) == [], i["insight_id"]
            n += 1
    assert n > 0


def test_guards_catch_advice_and_pii():
    s = {"survey_id": "S-00001", "farmer_id": "F", "source_insight_ids": ["I"], "language": "en-IN",
         "send_window": {"not_before": "2026-12-06T07:00:00+05:30", "not_after": "2026-12-09T19:00:00+05:30"},
         "rationale": "x", "items": [{"item_id": "q1", "type": "survey-confirm",
                                      "prompt": "You should spray now. What is your phone number?",
                                      "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}]}
    p = check_survey(s)
    assert any("advice" in x for x in p) and any("personal" in x for x in p)


def test_relevance_score_in_range():
    n = 0
    for i in load_insights():
        d = decide(i)
        if d.survey:
            for s in write_surveys(i, d.send_window).values():
                r = s["self_eval"]["relevance_score"]
                assert 0 <= r <= 1
                n += r > 0
    assert n > 0
