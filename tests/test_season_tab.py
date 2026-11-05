"""The app's Season tab: P3's shared simulated clock moving through November to March (owner: P5).

Runs the real app on the mock sample (MEL_DATA_DIR set), clicks the clock forward and checks that surveys go out,
the queue empties by the end of March, and a different farmer persona restarts the season."""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


@pytest.fixture
def app(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("MEL_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data" / "mock"))
    # The app's auto-reload drops and re-imports every mel.* module. Put the originals back afterwards, or later
    # tests would patch one copy of a module while the code under test uses another.
    saved = {k: v for k, v in sys.modules.items() if k == "mel" or k.startswith("mel.")}
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception, [e.message for e in at.exception]
    yield at
    for k in [k for k in sys.modules if k == "mel" or k.startswith("mel.")]:
        del sys.modules[k]
    sys.modules.update(saved)


def _metrics(at):
    return {m.label: int(m.value.replace(",", "")) for m in at.metric
            if m.label in ("Waiting to send", "Messages sent", "Answered", "Opted out")}


def _click(at, label):
    [b for b in at.button if b.label == label][0].click().run()
    assert not at.exception, [e.message for e in at.exception]


def test_season_walk_sends_and_empties_the_queue(app):
    start = _metrics(app)
    assert start["Messages sent"] == 0 and start["Waiting to send"] > 0
    _click(app, "To end of March")
    end = _metrics(app)
    assert end["Waiting to send"] == 0 and end["Messages sent"] > 0
    assert end["Answered"] == end["Messages sent"]          # the default persona answers on the first channel
    assert "season over" in app.get("progress")[0].proto.text


def test_persona_change_restarts_the_season(app):
    _click(app, "+1 week")
    [s for s in app.selectbox if s.label == "How farmers respond"][0].select("opts_out_first").run()
    assert _metrics(app)["Messages sent"] == 0               # new persona = fresh season
    _click(app, "To end of March")
    m = _metrics(app)
    assert m["Opted out"] == m["Messages sent"] > 0 and m["Answered"] == 0


def test_hindi_is_labelled_pending_review(app):
    """Survey demo: Hindi carries a "pending review" label until P4's review sheet is fully checked."""
    pending = lambda: [c.value for c in app.caption if c.value.startswith("Hindi pending review")]
    assert not pending()                                     # English first, no label
    app.toggle(key="lang_hi").set_value(True).run()
    assert not app.exception and pending()


def test_demo_pick_shows_the_bedrock_written_questions(app):
    """Survey demo: the phone carries the survey Bedrock wrote (recorded from AgentCore), not the template."""
    caps = [c.value for c in app.caption]
    assert any(c.startswith("Questions written by Bedrock") and "recorded" in c for c in caps), caps
    assert any("Template vs Bedrock questions" in e.label for e in app.expander)
    text = " ".join(m.value for m in app.markdown)
    assert "11/28/2026 7:00 AM IST" in text              # the farmer's send time, in India time (team decision 5 Nov)


def test_own_insight_is_written_by_bedrock(tmp_path, monkeypatch):
    """Create your own insight with Bedrock on: the model reads the conversation and fills in the Details, the agent
    writes the English questions and translates them into Hindi. Every request is answered from the on-disk cache
    (filled first with a stand-in client), so nothing here calls AWS."""
    from streamlit.testing.v1 import AppTest
    from app import custom_context as cc
    from mel.agent import run_agent
    from mel.writer import llm
    for k, v in {"MEL_USE_LLM": "1", "MEL_BEDROCK_WRITE_MODEL": "test-write-model", "MEL_CACHE_DIR": str(tmp_path / "cache"),
                 "MEL_LLM_LOG": str(tmp_path / "calls.jsonl"),
                 "MEL_DATA_DIR": str(Path(__file__).resolve().parents[1] / "data" / "mock")}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("MEL_BEDROCK_CHECK_MODEL", raising=False)
    question = "My goat has not eaten for two days and has a fever."
    advice = "Call the government vet today and keep the goat in the shade with clean water."
    replies = ["asset: goat\nconcern: livestock_health\nseverity: high\nadvice_type: escalate_to_expert\n"
               "act_within_days: 1\ncheck_back: next_day\nquestions: 2",
               "confirm | Did you call the government vet about your goat? | Yes | No*e\nscale | How is your goat's health now?",
               "confirm | क्या आपने बकरी के लिए सरकारी पशु चिकित्सक को बुलाया? | हाँ | नहीं*e\nscale | अब आपकी बकरी की सेहत कैसी है?"]

    class Runtime:
        def converse(self, **kw):
            return {"output": {"message": {"content": [{"text": replies.pop(0)}]}}, "usage": {"inputTokens": 100, "outputTokens": 40}}

    llm.set_client(llm.ModelClient(runtime=Runtime(), sleep=lambda s: None))
    read = llm.read_conversation(question, advice)
    fields = cc.apply_reading({**cc.DEFAULTS, "question": question, "advice": advice}, read)
    list(run_agent(cc.build_insight(fields, cc.new_ids(1), cc.now_ist()), memory=None, n_items=read["questions"]))
    llm.set_client(None)
    assert not replies                                                    # the three answers are on disk now
    saved = {k: v for k, v in sys.modules.items() if k == "mel" or k.startswith("mel.")}
    try:
        at = AppTest.from_file(str(APP), default_timeout=120).run()
        assert not at.exception, [e.message for e in at.exception]
        at.button(key="own_add").click().run()
        at.text_area(key="cc_question").set_value(question)
        at.text_area(key="cc_advice").set_value(advice).run()
        at.button(key="custom_submit").click().run()
        assert not at.exception, [e.message for e in at.exception]
        text = " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)
        assert "Questions written by Bedrock just now (test-write-model)" in text
        assert "Bedrock read the conversation as: Goat · animal health · high severity" in text and "2 questions" in text
        assert any("Template vs Bedrock questions" in e.label for e in at.expander)
        assert at.session_state["custom_draft"]["asset"] == "goat"          # the Details now show what the model read
    finally:
        for k in [k for k in sys.modules if k == "mel" or k.startswith("mel.")]:
            del sys.modules[k]
        sys.modules.update(saved)
