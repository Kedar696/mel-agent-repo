"""Shared paths, constants and settings. Everyone imports from here.

Every MEL_* setting is read through env() at call time (so a test can change it with monkeypatch): the process
environment first, then the repo's .env (copy .env.example; never committed), then the default. Nothing else in
the repo reads os.environ for a MEL_* name."""
import json
import os
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
SCHEMAS = CONFIG / "schemas"
RULES_DIR = CONFIG / "rules"


@lru_cache
def _dotenv() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def env(name: str, default: str = "") -> str:
    """The setting `name`: the environment, else .env, else `default`; stripped. Empty counts as unset."""
    return (os.environ.get(name) or _dotenv().get(name) or default).strip()


def flag(name: str) -> bool:
    """A yes/no setting: on only when it is exactly "1"."""
    return env(name) == "1"


def bedrock_region() -> str:
    """MEL_BEDROCK_REGION, else the AWS SDK's own region settings, else "" (boto3 then decides)."""
    return env("MEL_BEDROCK_REGION") or env("AWS_REGION") or env("AWS_DEFAULT_REGION")


DATA = Path(env("MEL_DATA_DIR") or ROOT / "data" / "mock")
FIXTURES = ROOT / "data" / "mock"  # scenarios/ + outcomes/ always come from here
PACK = ROOT / "mel-survey-agent-participant-pack" / "participant-pack"
PACK_DATA = PACK / "data"
OUT = Path(env("MEL_OUT_DIR") or ROOT / "out")
IST = timezone(timedelta(hours=5, minutes=30))
LANGS = ("hi-IN", "en-IN")
CHANNELS = ("app", "web", "whatsapp", "telegram", "voice")


def full_pack() -> bool:
    """True when the full participant pack is in the repo and MEL_DATA_DIR does not point elsewhere: the agent,
    the app and the comparison scripts then read the 6,999 insights instead of the mock sample."""
    return (PACK_DATA / "insights.jsonl").exists() and not env("MEL_DATA_DIR")


@lru_cache
def rules() -> dict:
    return json.loads((RULES_DIR / "rules.json").read_text(encoding="utf-8"))


@lru_cache
def outcome_codes() -> dict:
    return json.loads((RULES_DIR / "outcome_codes.json").read_text(encoding="utf-8"))
