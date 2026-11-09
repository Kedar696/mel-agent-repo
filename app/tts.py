"""Read the voice-call preview aloud with ElevenLabs text to speech. Display only: nothing is sent to a farmer.

Needs ELEVENLABS_API_KEY in the environment or in the repo's .env (mel.config.env; see .env.example). Optional
ELEVENLABS_VOICE_ID (default: a premade voice) and ELEVENLABS_MODEL (default eleven_multilingual_v2, which speaks
Hindi and English). Without a key, speak() returns None and the app says how to enable it. Standard library only.
"""

import json
import urllib.error
import urllib.request

from mel.config import env

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # "George", one of ElevenLabs' own premade voices (free plans may not use
# library voices through the API; "Rachel" 21m00Tcm4TlvDq8ikWAM is one of those). Override with ELEVENLABS_VOICE_ID.
DEFAULT_MODEL = "eleven_multilingual_v2"


class TTSError(Exception):
    """ElevenLabs refused or could not be reached; the message is safe to show."""


def api_key() -> str:
    return env("ELEVENLABS_API_KEY")


def speak(text: str, *, key: str | None = None, voice: str | None = None, model: str | None = None) -> bytes | None:
    """MP3 bytes for `text`, or None when there is no key or no text. Raises TTSError when the API says no."""
    key = key if key is not None else api_key()
    text = (text or "").strip()
    if not key or not text:
        return None
    body = json.dumps({"text": text, "model_id": model or env("ELEVENLABS_MODEL", DEFAULT_MODEL)}).encode()
    req = urllib.request.Request(
        API.format(voice=voice or env("ELEVENLABS_VOICE_ID", DEFAULT_VOICE)),
        data=body,
        method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:  # ElevenLabs answers {"detail": {"message": "..."}} or {"detail": "..."}; show that sentence
            detail = json.loads(raw).get("detail")
            msg = detail.get("message") if isinstance(detail, dict) else detail
        except (ValueError, AttributeError):
            msg = None
        raise TTSError(f"HTTP {e.code}: {str(msg or raw or e.reason)[:240]}") from None
    except (urllib.error.URLError, OSError) as e:
        raise TTSError(str(e)) from None
