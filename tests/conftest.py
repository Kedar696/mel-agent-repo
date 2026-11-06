import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import mel.config  # noqa: E402


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Tests see only the process environment, never the developer's .env."""
    monkeypatch.setattr(mel.config, "_dotenv", dict)
