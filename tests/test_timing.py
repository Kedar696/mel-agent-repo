"""P2: send window reproduces every worked scenario."""
from mel.data import load_scenario, list_scenarios
from mel.timing import send_window, expires_at


def test_windows_match_scenarios():
    for n in list_scenarios():
        s = load_scenario(n)
        if s["handoff"]:
            w = send_window(s["insight"])
            assert w == s["handoff"]["send_window"], n
            assert expires_at(w) == s["handoff"]["expires_at"], n
