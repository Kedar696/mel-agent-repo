"""Shared paths and constants. Owner: P1 (Data & Integration). Everyone imports from here."""
import json
import os
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
SCHEMAS = CONFIG / "schemas"
RULES_DIR = CONFIG / "rules"
DATA = Path(os.environ.get("MEL_DATA_DIR", ROOT / "data" / "mock"))
FIXTURES = ROOT / "data" / "mock"  # scenarios/ + outcomes/ always come from here
PACK = ROOT / "mel-survey-agent-participant-pack" / "participant-pack"
PACK_DATA = PACK / "data"
OUT = Path(os.environ.get("MEL_OUT_DIR", ROOT / "out"))
IST = timezone(timedelta(hours=5, minutes=30))
LANGS = ("hi-IN", "en-IN")
CHANNELS = ("app", "web", "whatsapp", "telegram", "voice")


@lru_cache
def rules() -> dict:
    return json.loads((RULES_DIR / "rules.json").read_text(encoding="utf-8"))


@lru_cache
def outcome_codes() -> dict:
    return json.loads((RULES_DIR / "outcome_codes.json").read_text(encoding="utf-8"))
