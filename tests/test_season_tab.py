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
