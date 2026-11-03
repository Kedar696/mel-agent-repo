"""Readers for the participant pack (or the mock subset in data/mock). Owner: P1."""
import csv
import json
from pathlib import Path
from typing import Iterator

from mel.config import DATA, FIXTURES


def _jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_insights(path: Path | None = None) -> list[dict]:
    return list(_jsonl(path or DATA / "insights.jsonl"))


def load_golden(path: Path | None = None) -> list[dict]:
    return list(_jsonl(path or DATA / "golden_set.jsonl"))


def load_farmers(path: Path | None = None) -> dict[str, dict]:
    with open(path or DATA / "farmers.csv", encoding="utf-8") as f:
        return {r["farmer_id"]: r for r in csv.DictReader(f)}


def load_crop_calendar(path: Path | None = None) -> list[dict]:
    with open(path or DATA / "crop_calendar_bihar_rabi.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def list_scenarios() -> list[str]:
    return sorted(p.name for p in (FIXTURES / "scenarios").iterdir() if p.is_dir())


def load_scenario(name: str) -> dict:
    """Returns {'insight', 'surveys': {lang: survey}, 'handoff', 'no_survey', 'responses': {channel: rec}}."""
    d = FIXTURES / "scenarios" / name
    read = lambda p: json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return {
        "insight": read(d / "insight.json"),
        "surveys": {p.stem.split(".", 1)[1]: read(p) for p in d.glob("survey.*.json")},
        "handoff": read(d / "schedule_handoff.json"),
        "no_survey": read(d / "no_survey.json"),
        "responses": {p.stem: read(p) for p in (d / "responses").glob("*.json")} if (d / "responses").exists() else {},
    }
