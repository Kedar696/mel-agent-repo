"""Interactive channel preview (app/preview_state.py + app/channel_preview.py): one tap advances one
question, every ending keeps the real taps and invents none, every record is schema-valid, and the
times on screen agree with the record."""
from datetime import timedelta

from mel.channels.render import UI
from mel.data import load_scenario, errors
from mel.timing import parse_ist
from app.preview_state import (PreviewState, STOP_WORD, build_record, chat_log, open_time, send_time,
                               tap_time)

SCALE = "3-potato-blight-wait"  # q1 yes/no (2 buttons), q2 four options (WhatsApp picker), q3 scale 1-5


def survey(name=SCALE, lang="en-IN"):
    return load_scenario(name)["surveys"][lang]


def valid(rec):
    assert not errors("response", rec), errors("response", rec)
    ts = rec["timestamps"]
    stamps = [parse_ist(v) for v in (ts["sent"], ts["delivered"], ts["opened"], ts["answered"]) if v]
    assert stamps == sorted(stamps), ts
    assert parse_ist(rec["recorded_at"]) >= stamps[-1], (rec["recorded_at"], ts)


def test_whatsapp_full_run_keeps_real_taps_and_channel_encoding():
    s, st = survey(), PreviewState.new(survey(), "whatsapp")
    assert st.stage == "invite" and build_record(s, "whatsapp", st) is None
    st.start()
    st.answer("q1", "yes")
    st.open_picker()
    st.answer("q2", "same")
    st.open_picker()
    st.answer("q3", 5)
    assert st.done and st.ending == "finished"
    rec = build_record(s, "whatsapp", st)
    valid(rec)
    assert rec["status"] == "completed" and rec["answers"] == {"q1": "yes", "q2": "same", "q3": 5}
    # 2 choices ride reply buttons; 4 and 5 choices go through the list picker (render._whatsapp)
    assert [i["input_kind"] for i in rec["items"]] == ["button_reply", "list_reply", "list_reply"]
    assert rec["items"][2]["raw_input"] == "S-21310|q3|5"


def test_one_tap_advances_one_question():
    st = PreviewState.new(survey(), "telegram")
    st.answer("q1", "yes")
    st.answer("q1", "yes")  # a double submit
    assert st.step == 1 and st.taps == {"q1": "yes"}
    st.answer("q3", 5)  # a question that is not on screen yet
    st.answer("q2", "bogus")  # a value its buttons do not carry
    assert st.step == 1 and st.current == "q2" and st.taps == {"q1": "yes"}


def test_stop_after_partial_answers_keeps_them():
    s, st = survey(), PreviewState.new(survey(), "whatsapp")
    st.start()
    st.answer("q1", "no")
    st.send_text(" stop ")
    rec = build_record(s, "whatsapp", st)
    valid(rec)
    assert (rec["status"], rec["failure_code"], rec["raw_event"]) == ("declined", "farmer_opted_out", "STOP")
    assert rec["answers"] == {"q1": "no"} and not rec["complete"]
    assert [i["result"] for i in rec["items"]] == ["answered", "skipped", "not_reached"]
    assert rec["farmerchat_reply"] == {"http_status": 201, "outcome": "accepted"}


def test_typed_message_is_invalid_on_the_question_shown():
    s, st = survey(), PreviewState.new(survey(), "telegram")
    st.answer("q1", "yes")
    st.send_text("कल बताऊँगा")
    rec = build_record(s, "telegram", st)
    valid(rec)
    assert rec["status"] == "invalid_input" and rec["retry_decision"] == "retry_same_channel"
    q2 = rec["items"][1]
    assert (q2["result"], q2["raw_input"], q2["input_kind"]) == ("invalid", "कल बताऊँगा", "free_text")
    assert rec["answers"] == {"q1": "yes"} and rec["items"][2]["result"] == "not_reached"
    assert rec["farmerchat_reply"] is None


def test_stop_words_not_now_and_the_opening():
    s = survey()
    tg = PreviewState.new(s, "telegram")
    tg.send_text("/STOP")
    assert tg.ending == "opted_out" and build_record(s, "telegram", tg)["raw_event"] == "/stop"
    wa = PreviewState.new(s, "whatsapp")
    wa.decline()
    rec = build_record(s, "whatsapp", wa)
    valid(rec)
    assert (rec["status"], rec["failure_code"], rec["raw_event"]) == ("declined", "farmer_declined", "S-21310|later")
    assert rec["answers"] == {} and all(i["result"] == "not_reached" for i in rec["items"])
    typed = PreviewState.new(s, "whatsapp")
    typed.send_text("hello?")  # typed at the template instead of tapping Start
    rec = build_record(s, "whatsapp", typed)
    valid(rec)
    assert rec["failure_code"] == "free_text_instead_of_choice" and rec["items"][0]["raw_input"] == "hello?"


def test_negative_answer_flags_follow_up():
    s = survey("4-cow-vet-escalation", "hi-IN")
    st = PreviewState.new(s, "telegram")
    st.answer("q1", "no")
    st.answer("q2", "worse")
    rec = build_record(s, "telegram", st)
    valid(rec)
    assert rec["status"] == "negative_outcome" and rec["needs_follow_up"]
    assert rec["timestamps"]["opened"] is None  # Telegram has no read receipts


def test_sheet_close_dismiss_and_opt_out():
    s = survey()
    a = PreviewState.new(s, "app")
    a.answer("q1", "yes")
    a.close()
    rec = build_record(s, "app", a)
    valid(rec)
    assert (rec["status"], rec["sheet_outcome"], rec["answers"]) == ("partial", "closed_partway", {"q1": "yes"})
    assert rec["raw_event"] == "Close tapped at step 2 of 3"
    assert [i["result"] for i in rec["items"]] == ["answered", "skipped", "not_reached"]
    d = PreviewState.new(s, "web")
    d.close()
    rec = build_record(s, "web", d)
    valid(rec)
    assert (rec["failure_code"], rec["sheet_outcome"]) == ("sheet_dismissed", "dismissed")
    o = PreviewState.new(s, "app")
    o.answer("q1", "yes")
    o.answer("q2", "no_new")
    o.opt_out()
    rec = build_record(s, "app", o)
    valid(rec)
    assert rec["failure_code"] == "farmer_opted_out" and rec["answers"] == {"q1": "yes", "q2": "no_new"}
    assert rec["raw_event"] == "tapped Do not ask me again in the sheet"


def test_voice_keys_and_hang_up_times():
    s = survey("1-mustard-aphid-spray", "hi-IN")  # a single-select survey: P3's anchor is q3, not q1
    v = PreviewState.new(s, "voice")
    assert v.stage == "ringing" and not v.started
    v.answer("q1", "yes")  # nothing works until the phone is picked up
    v.pick_up()
    v.start()
    v.answer("q1", "yes")
    v.hang_up()
    rec = build_record(s, "voice", v)
    valid(rec)
    assert rec["failure_code"] == "voice_call_dropped" and rec["answers"] == {"q1": "yes"}
    assert [i["result"] for i in rec["items"]] == ["answered", "not_reached", "not_reached"]
    assert rec["items"][0]["input_kind"] == "speech"  # a yes/no on a call is spoken (simulate.py)
    assert rec["recorded_at"] == rec["timestamps"]["answered"]
    w = PreviewState.new(s, "voice")  # nothing answered: the cut is logged after the pick-up, not before
    w.pick_up()
    w.start()
    w.hang_up()
    rec = build_record(s, "voice", w)
    valid(rec)
    assert rec["answers"] == {} and rec["answered_by"] is None and rec["timestamps"]["answered"] is None
    assert parse_ist(rec["recorded_at"]) > parse_ist(rec["timestamps"]["opened"])
    d = PreviewState.new(s, "voice")
    d.pick_up()
    d.decline()
    assert build_record(s, "voice", d)["raw_event"] == "pressed 2 at the opening (not now)"
    m = PreviewState.new(s, "voice")  # the phone rings out: P3's voice_no_answer, nothing presented
    m.miss()
    rec = build_record(s, "voice", m)
    valid(rec)
    assert (rec["failure_code"], rec["retry_decision"], rec["answers"]) == ("voice_no_answer", "fall_back_to_next_channel", {})
    assert all(i["result"] == "not_reached" for i in rec["items"]) and rec["timestamps"]["opened"] is None


def _drive(st, how):
    """Walk a fresh state to one ending; None when the channel has no such control."""
    ch = st.channel
    st.pick_up()
    st.start()
    if how == "missed" and ch == "voice":
        st.reset(), st.miss()
    elif how == "finished":
        for i in st.ids:
            st.answer(i, st.values[i][0])
    elif how == "stop":
        st.answer(st.ids[0], st.values[st.ids[0]][-1])
        if ch in STOP_WORD:
            st.send_text(STOP_WORD[ch])
        elif ch == "voice":
            st.reset(), st.pick_up(), st.opt_out()  # key 9 is offered during the greeting only
        else:
            st.opt_out()
    elif how == "typed" and ch in STOP_WORD:
        st.answer(st.ids[0], st.values[st.ids[0]][0])
        st.send_text("पता नहीं")
    elif how in ("closed", "dismissed") and ch in ("app", "web"):
        if how == "closed":
            st.answer(st.ids[0], st.values[st.ids[0]][0])
        st.close()
    elif how == "declined" and ch in ("whatsapp", "voice"):
        st.reset(), st.pick_up(), st.decline()
    elif how == "dropped" and ch == "voice":
        st.answer(st.ids[0], st.values[st.ids[0]][0])
        st.hang_up()
    else:
        return None
    assert st.done and st.ending == {"stop": "opted_out", "typed": "free_text"}.get(how, how)
    return st


def test_every_ending_on_every_channel_is_valid_and_chronological():
    n = 0
    for name in ("1-mustard-aphid-spray", SCALE, "4-cow-vet-escalation"):
        for lang in ("hi-IN", "en-IN"):
            s = load_scenario(name)["surveys"][lang]
            for ch in ("app", "web", "whatsapp", "telegram", "voice"):
                for how in ("finished", "stop", "typed", "closed", "dismissed", "declined", "dropped", "missed"):
                    st = _drive(PreviewState.new(s, ch), how)
                    if st is None:
                        continue
                    rec = build_record(s, ch, st, send_at="2027-01-10T09:30:00+05:30")
                    valid(rec)
                    assert rec["answers"] == st.taps, (name, ch, how)  # the record carries the taps, nothing else
                    assert rec["timestamps"]["sent"] == "2027-01-10T09:30:00+05:30"
                    n += 1
    assert n == 3 * 2 * (4 + 4 + 4 + 3 + 5)  # app, web, whatsapp, telegram, voice endings per survey


def test_send_time_fallback_and_tap_times_match_the_record():
    s = survey()
    t0 = send_time(s, "whatsapp")  # no recommended time: the window opening plus P3's channel offset
    assert t0 == parse_ist(s["send_window"]["not_before"]) + timedelta(hours=1)
    assert send_time(s, "app") == parse_ist(s["send_window"]["not_before"])
    st = PreviewState.new(s, "whatsapp")
    _drive(st, "finished")
    rec = build_record(s, "whatsapp", st)
    assert rec["timestamps"]["sent"] == "2027-01-09T08:00:00+05:30"
    taps = [tap_time(t0, k, 3) for k in (1, 2, 3)]
    assert open_time(t0) < taps[0] < taps[1] < taps[2] == parse_ist(rec["timestamps"]["answered"])
    assert tap_time(t0, 1, 1) == parse_ist(rec["timestamps"]["answered"])


def test_chat_log_shows_only_the_question_on_screen():
    s, t0 = survey(), send_time(survey(), "whatsapp")
    st = PreviewState.new(s, "whatsapp")
    log, cur = chat_log(s, "whatsapp", st, t0)
    assert [m["who"] for m in log] == ["bot"] and cur is None and log[0]["buttons"] == ["Start", "Not now"]
    st.start()
    log, cur = chat_log(s, "whatsapp", st, t0)
    assert [m["who"] for m in log] == ["bot", "farmer"] and log[1]["at"] == open_time(t0)
    assert cur["text"] == s["items"][0]["prompt"] and not cur["picker"]
    shown = " ".join(m["text"] for m in log) + cur["text"]
    assert s["items"][1]["prompt"] not in shown and s["items"][2]["prompt"] not in shown
    st.answer("q1", "yes")
    log, cur = chat_log(s, "whatsapp", st, t0)
    assert log[-2]["text"] == s["items"][0]["prompt"] and log[-1] == {"who": "farmer", "text": "Yes", "at": tap_time(t0, 1, 3)}
    assert cur["picker"] and cur["at"] == tap_time(t0, 1, 3)
    tg = PreviewState.new(s, "telegram")  # Telegram: the tap edits the question instead of a farmer message
    tg.answer("q1", "yes")
    log, cur = chat_log(s, "telegram", tg, t0)
    assert [m["who"] for m in log] == ["bot", "bot"] and log[1]["answer"] == "Yes" and log[0]["at"] == log[1]["at"] == t0
    hi = survey(lang="hi-IN")
    done = _drive(PreviewState.new(hi, "whatsapp"), "finished")
    log, cur = chat_log(hi, "whatsapp", done, t0, follow_up=True)
    assert cur is None and log[-1]["text"] == UI["hi-IN"]["closing_fu"] and log[-1]["at"] == tap_time(t0, 3, 3)
    stop = PreviewState.new(s, "whatsapp")  # the final event on screen sits on the record's answered stamp
    _drive(stop, "stop")
    log, _ = chat_log(s, "whatsapp", stop, t0)
    assert log[-1]["text"] == "STOP" and log[-1]["at"] == parse_ist(build_record(s, "whatsapp", stop)["timestamps"]["answered"])


def test_reset_starts_fresh():
    s, st = survey(), PreviewState.new(survey(), "whatsapp")
    _drive(st, "finished")
    st.reset()
    assert (st.stage, st.step, st.taps, st.ending, st.typed) == ("invite", 0, {}, None, None)
    assert build_record(s, "whatsapp", st) is None and not st.started and st.rev > 0


def _preview_app():
    # Runs as a script inside the pytest process, so conftest's sys.path (the repo root) already applies.
    import streamlit as st
    from mel.data import load_scenario
    from app.channel_preview import render_channel_preview
    survey = load_scenario("3-potato-blight-wait")["surveys"]["en-IN"]
    st.session_state["rec"] = render_channel_preview(survey, "whatsapp", key="t|wa")


def test_streamlit_click_through():
    """The real widgets, driven headlessly: Start, a reply button, the list picker, STOP, Start over."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_preview_app, default_timeout=60).run()
    assert not at.exception
    assert sorted(b.key for b in at.button) == ["t|wa|later", "t|wa|start"]
    at.button(key="t|wa|start").click().run()
    assert at.session_state["rec"] is None and {b.key for b in at.button} >= {"t|wa|q1|yes", "t|wa|q1|no"}
    screen = " ".join(m.value for m in at.markdown)  # 2027-01-09 08:00 IST shows as the evening before, Eastern
    assert "01/08/2027" in screen and "9:30 PM" in screen and "9:50 PM" in screen and "01/09/2027" not in screen
    at.button(key="t|wa|q1|yes").click().run()
    assert "t|wa|pick" in {b.key for b in at.button} and not any("q3" in b.key for b in at.button)
    at.button(key="t|wa|pick").click().run()
    at.button(key="t|wa|q2|same").click().run()
    at.chat_input(key="t|wa|typed").set_value("STOP").run()
    rec = at.session_state["rec"]
    assert rec["failure_code"] == "farmer_opted_out" and rec["answers"] == {"q1": "yes", "q2": "same"}
    assert not at.exception
    at.button(key="t|wa|reset").click().run()
    assert at.session_state["rec"] is None and sorted(b.key for b in at.button) == ["t|wa|later", "t|wa|start"]


def _restart_app():
    import streamlit as st
    from mel.data import load_scenario
    from app.channel_preview import render_channel_preview
    survey = load_scenario("3-potato-blight-wait")["surveys"]["en-IN"]
    st.session_state["rec"] = render_channel_preview(survey, "telegram", key="t|r", show_restart=False,
                                                     restart=st.session_state.get("restart", False))


def test_restart_flag_and_hidden_start_over():
    """The app's own Restart control: restart=True resets before drawing; show_restart=False hides ours."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_restart_app, default_timeout=60).run()
    at.button(key="t|r|q1|yes").click().run()
    keys = {b.key for b in at.button}
    assert "t|r|q2|no_new" in keys and "t|r|reset" not in keys
    at.session_state["restart"] = True
    at.run()
    assert "t|r|q1|yes" in {b.key for b in at.button} and at.session_state["rec"] is None and not at.exception


def _voice_app():
    import streamlit as st
    from mel.data import load_scenario
    from app.channel_preview import render_channel_preview
    survey = load_scenario("3-potato-blight-wait")["surveys"]["en-IN"]
    st.session_state["rec"] = render_channel_preview(survey, "voice", key="t|vo")


def test_voice_clock_follows_the_call():
    """Voice sends at 10:00 IST (window + 3 h), which the phone shows as 11:30 PM Eastern the evening before:
    rings 11:30, picked up 11:50 (timer 00:00), key 1 at 11:52 (02:00), cut logged 11:55 (05:00)."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_voice_app, default_timeout=60).run()
    screen = lambda: " ".join(m.value for m in at.markdown)
    assert "11:30 PM</span>" in screen() and "Incoming call" in screen() and "Hello, this is a call" not in screen()
    assert {b.key for b in at.button} >= {"t|vo|miss", "t|vo|pickup"}
    at.button(key="t|vo|pickup").click().run()
    assert "11:50 PM</span>" in screen() and 'data-start="0" data-live="1">00:00' in screen()
    assert "Hello, this is a call" in screen() and "potato leaves" not in screen()
    at.button(key="t|vo|start").click().run()
    assert "potato leaves" in screen()
    at.button(key="t|vo|q1|yes").click().run()
    assert "11:52 PM</span>" in screen() and "02:00" in screen()
    at.button(key="t|vo|hang").click().run()
    rec = at.session_state["rec"]
    assert rec["failure_code"] == "voice_call_dropped" and rec["recorded_at"].endswith("T10:25:00+05:30")
    assert "11:55 PM</span>" in screen() and "05:00" in screen() and not at.exception
