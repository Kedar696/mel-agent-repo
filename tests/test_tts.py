"""ElevenLabs read-aloud helper: no key means no call; with a key the request carries the key, model and text."""

import io
import json
import urllib.request

import pytest

from app import tts


def test_no_key_or_no_text_means_no_request(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not call the API"))
    assert tts.speak("Hello", key="") is None
    assert tts.speak("   ", key="k") is None


def test_request_shape_and_audio_bytes(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["headers"], seen["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
        return Resp(b"ID3fake-mp3")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = tts.speak(
        "नमस्ते, यह FarmerChat की ओर से कॉल है।", key="secret-key", voice="v123", model="eleven_multilingual_v2"
    )
    assert out == b"ID3fake-mp3"
    assert seen["url"].startswith("https://api.elevenlabs.io/v1/text-to-speech/v123?")
    assert seen["headers"]["Xi-api-key"] == "secret-key" and seen["body"]["model_id"] == "eleven_multilingual_v2"
    assert seen["body"]["text"].startswith("नमस्ते")


def test_key_comes_from_the_settings(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert tts.api_key() == ""
    monkeypatch.setenv("ELEVENLABS_API_KEY", " from-env ")
    assert tts.api_key() == "from-env"


def test_api_refusal_is_a_readable_error(monkeypatch):
    import urllib.error

    body = (
        b'{"detail":{"type":"invalid_request","code":"quota_exceeded","message":"This request exceeds your '
        b'API key quota of 5. You have 0 credits remaining."}}'
    )  # the shape ElevenLabs really returns

    def refuse(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(tts.TTSError, match=r"^HTTP 401: This request exceeds your API key quota of 5\. You have 0"):
        tts.speak("Hello", key="wrong")

    def refuse_plain(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"bad key"}'))

    monkeypatch.setattr(urllib.request, "urlopen", refuse_plain)
    with pytest.raises(tts.TTSError, match=r"^HTTP 401: bad key$"):
        tts.speak("Hello", key="wrong")
