"""The team app end to end (owner: P5): the Dashboard waits for Run evaluation, and the Survey demo's guided flow
(hand the conversation to the agent, send the survey to the farmer, the agent reviews and plans the next survey).

Runs the real app on the mock sample (MEL_DATA_DIR set); the example conversation comes from the full pack, so on the
mock sample the Survey demo opens on Browse, which takes the same flow."""

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def _ours(name):
    return name in ("mel", "app") or name.startswith(("mel.", "app."))


def _modules():
    """The app's auto-reload drops and re-imports every mel.* and app.* module. Snapshot the originals and put them
    back afterwards, or later tests would patch (or switch the time zone of) one copy of a module while the code
    under test uses another."""
    return {k: v for k, v in sys.modules.items() if _ours(k)}


def _restore(saved):
    for k in [k for k in sys.modules if _ours(k)]:
        del sys.modules[k]
    sys.modules.update(saved)


@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MEL_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data" / "mock"))
    saved = _modules()
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, [e.message for e in at.exception]
    yield at
    _restore(saved)


def _click(at, key):
    at.button(key=key).click().run()
    assert not at.exception, [e.message for e in at.exception]


def _goat(at):
    box = next(s for s in at.selectbox if s.label.startswith("Conversation ("))
    box.select(next(o for o in box.options if o.startswith("I-001253"))).run()
    assert not at.exception, [e.message for e in at.exception]


def test_terminal_input_moves_the_flow_and_answers(app):
    """Survey demo: typing in the terminal runs the flow's commands and answers questions from the case's facts."""
    _goat(app)
    for line in ("start", "why", "send"):
        app.chat_input(key="ask|flow|I-001253").set_value(line).run()
        assert not app.exception, [e.message for e in app.exception]
    text = " ".join(m.value for m in app.markdown)
    assert "Reading the conversation." in text and "R8 · Survey" in text and "Sent. The survey is on the farmer" in text
    assert app.session_state["flow|I-001253"] == 2  # on the farmer's phone now


def _to_phone(at, goat=True):
    """Survey demo: (on the mock sample, pick the goat case in Browse: it has a recorded Bedrock run), hand the
    conversation to the agent, then send the survey to the farmer."""
    if goat:
        _goat(at)
    _click(at, "flow_hand")
    _click(at, "flow_send")


def test_dashboard_scores_only_on_request(app):
    text = lambda: " ".join(m.value for m in app.markdown)
    assert "Decisions right" not in text()  # nothing scored on load
    _click(app, "dash_eval_run")
    assert "Decisions right" in text() and "Answer key vs agent" in text()
    assert not [b for b in app.button if b.key == "dash_eval_run"]  # the button gives way to the results


def test_hindi_is_labelled_pending_review(app):
    """Survey demo: Hindi carries a "pending review" label until P4's review sheet is fully checked."""
    pending = lambda: [c.value for c in app.caption if c.value.startswith("Hindi pending review")]
    _to_phone(app)
    assert not pending()  # English first, no label
    app.toggle(key="lang_hi").set_value(True).run()
    assert not app.exception and pending()


def test_demo_pick_shows_the_bedrock_written_questions(app):
    """Survey demo: the phone carries the survey Bedrock wrote (recorded from AgentCore), not the template."""
    _to_phone(app)
    caps = [c.value for c in app.caption]
    assert any(c.startswith("Questions written by Bedrock") and "recorded" in c for c in caps), caps
    assert any("Template vs Bedrock questions" in e.label for e in app.expander)
    text = " ".join(m.value for m in app.markdown)
    assert "11/28/2026 7:00 AM IST" in text  # the farmer's send time, in India time (team decision 5 Nov)


def test_finished_survey_says_when_the_next_one_comes(app):
    """Survey demo: once the farmer taps through, the terminal reviews the answers, judges the survey, thinks it over
    and plans the next survey."""
    import re

    _to_phone(app)
    keys = lambda: [b.key for b in app.button if b.key and "preview" in b.key]
    for _ in range(12):  # Start (chat channels only), then every question with its first option
        ks = keys()
        q = (
            [k for k in ks if k.endswith("|start")]
            or [k for k in ks if "|pick" in k]
            or [k for k in ks if re.search(r"\|q\d+\|", k)]
        )
        if not q:
            break
        app.button(key=q[0]).click().run()
        assert not app.exception, [e.message for e in app.exception]
    text = " ".join(m.value for m in app.markdown)
    for step in ("<b>Review</b>", "<b>Assess</b>", "Thinking…", "<b>Plan</b>"):
        assert step in text, step
    assert "2 of 2 answered" in text and "Verdict" in text and "Next survey" in text, text


def test_own_insight_is_written_by_bedrock(tmp_path, monkeypatch):
    """Create your own insight with Bedrock on: the model reads the conversation and fills in the Details, the agent
    writes the English questions and translates them into Hindi. Every request is answered from the on-disk cache
    (filled first with a stand-in client), so nothing here calls AWS."""
    from streamlit.testing.v1 import AppTest
    from app import custom_context as cc
    from mel.agent import run_agent
    from mel.writer import llm

    for k, v in {
        "MEL_USE_LLM": "1",
        "MEL_BEDROCK_WRITE_MODEL": "test-write-model",
        "MEL_CACHE_DIR": str(tmp_path / "cache"),
        "MEL_LLM_LOG": str(tmp_path / "calls.jsonl"),
        "MEL_DATA_DIR": str(Path(__file__).resolve().parents[1] / "data" / "mock"),
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MEL_BEDROCK_CHECK_MODEL", raising=False)
    question = "My goat has not eaten for two days and has a fever."
    advice = "Call the government vet today and keep the goat in the shade with clean water."
    replies = [
        "asset: goat\nconcern: livestock_health\nseverity: high\nadvice_type: escalate_to_expert\n"
        "act_within_days: 1\ncheck_back: next_day\nquestions: 2",
        "confirm | Did you call the government vet about your goat? | Yes | No*e\nscale | How is your goat's health now?",
        "confirm | क्या आपने बकरी के लिए सरकारी पशु चिकित्सक को बुलाया? | हाँ | नहीं*e\nscale | अब आपकी बकरी की सेहत कैसी है?",
    ]

    class Runtime:
        def converse(self, **kw):
            return {
                "output": {"message": {"content": [{"text": replies.pop(0)}]}},
                "usage": {"inputTokens": 100, "outputTokens": 40},
            }

    llm.set_client(llm.ModelClient(runtime=Runtime(), sleep=lambda s: None))
    read = llm.read_conversation(question, advice)
    fields = cc.apply_reading({**cc.DEFAULTS, "question": question, "advice": advice}, read)
    list(run_agent(cc.build_insight(fields, cc.new_ids(1), cc.now_ist()), memory=None, n_items=read["questions"]))
    llm.set_client(None)
    assert not replies  # the three answers are on disk now
    saved = _modules()
    try:
        at = AppTest.from_file(str(APP), default_timeout=120).run()
        assert not at.exception, [e.message for e in at.exception]
        at.button(key="own_add").click().run()
        at.text_area(key="cc_question").set_value(question)
        at.text_area(key="cc_advice").set_value(advice).run()
        at.button(key="custom_submit").click().run()
        assert not at.exception, [e.message for e in at.exception]
        _to_phone(at, goat=False)
        text = " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)
        assert "Questions written by Bedrock just now (test-write-model)" in text
        assert (
            "Bedrock read the conversation as: Goat · animal health · high severity" in text and "2 questions" in text
        )
        assert any("Template vs Bedrock questions" in e.label for e in at.expander)
        assert at.session_state["custom_draft"]["asset"] == "goat"  # the Details now show what the model read
    finally:
        _restore(saved)
