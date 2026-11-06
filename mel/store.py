"""The API's one database: surveys, hand-offs, answers and opt-outs. Owner: P1.

MEL_DATABASE_URL names a SQLite database (the standard library's sqlite3, no driver to install):
  sqlite:///out/mel.sqlite3              a file (the default: <MEL_OUT_DIR>/mel.sqlite3)
  sqlite://                              in memory, for tests
Each record is kept whole as JSON text next to the few columns the API filters on, so the schemas in
config/schemas stay the only contract.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS surveys (
         survey_id TEXT NOT NULL, language TEXT NOT NULL, farmer_id TEXT NOT NULL, body TEXT NOT NULL,
         PRIMARY KEY (survey_id, language))""",
    """CREATE TABLE IF NOT EXISTS no_survey (
         insight_id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL, body TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS handoffs (
         handoff_id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL, survey_id TEXT NOT NULL, flow_id TEXT NOT NULL,
         admission TEXT NOT NULL, reason TEXT NOT NULL, not_before TEXT NOT NULL, expires_at TEXT NOT NULL,
         body TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS handoffs_farmer ON handoffs (farmer_id)",
    "CREATE INDEX IF NOT EXISTS handoffs_flow ON handoffs (flow_id)",
    """CREATE TABLE IF NOT EXISTS responses (
         response_key TEXT PRIMARY KEY, survey_id TEXT NOT NULL, farmer_id TEXT NOT NULL, flow_id TEXT NOT NULL,
         status TEXT NOT NULL, needs_follow_up INTEGER NOT NULL, recorded_at TEXT NOT NULL, body TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS opt_outs (
         farmer_id TEXT PRIMARY KEY, response_key TEXT NOT NULL, recorded_at TEXT NOT NULL)""",
)
SENDABLE = ("sent", "moved")      # admissions that hold a place in the queue; a merged survey rides on its host
TABLES = ("surveys", "no_survey", "handoffs", "responses", "opt_outs")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, url: str | None = None):
        from mel.config import OUT
        self.url = url or os.environ.get("MEL_DATABASE_URL") or f"sqlite:///{OUT / 'mel.sqlite3'}"
        if not self.url.startswith("sqlite://"):
            raise ValueError(f"MEL_DATABASE_URL must start with sqlite://, got {self.url!r}")
        rest = self.url[len("sqlite://"):]
        path = rest[1:] if rest.startswith("/") else rest     # sqlite:///relative, sqlite:////absolute
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # ponytail: one connection behind one lock; a pool when more than a few requests a second matter
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False, isolation_level=None)
        for stmt in SCHEMA:
            self._run(stmt)

    def _run(self, sql: str, params=()):
        with self._lock:
            return self._db.execute(sql, params)

    def _rows(self, sql: str, params=()) -> list:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # ------------------------------------------------------------------ writes
    def put_survey(self, survey: dict) -> None:
        self._run("INSERT INTO surveys (survey_id, language, farmer_id, body) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT (survey_id, language) DO UPDATE SET body = excluded.body",
                  (survey["survey_id"], survey["language"], survey["farmer_id"], _dumps(survey)))

    def put_no_survey(self, record: dict) -> None:
        self._run("INSERT INTO no_survey (insight_id, farmer_id, body) VALUES (?, ?, ?) "
                  "ON CONFLICT (insight_id) DO UPDATE SET body = excluded.body",
                  (record["insight_id"], record["farmer_id"], _dumps(record)))

    def put_handoff(self, handoff: dict, admission: str, reason: str = "") -> None:
        s = handoff["survey"]
        self._run("INSERT INTO handoffs (handoff_id, farmer_id, survey_id, flow_id, admission, reason, not_before, "
                  "expires_at, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (handoff_id) DO UPDATE SET "
                  "admission = excluded.admission, reason = excluded.reason, not_before = excluded.not_before, "
                  "expires_at = excluded.expires_at, body = excluded.body",
                  (handoff["handoff_id"], s["farmer_id"], s["survey_id"], handoff["farmerchat_flow"]["flow_id"],
                   admission, reason, handoff["send_window"]["not_before"], handoff["expires_at"], _dumps(handoff)))

    def put_response(self, record: dict, flow_id: str) -> bool:
        """True when stored now; False when this response_key was seen before (a retry changes nothing)."""
        cur = self._run("INSERT INTO responses (response_key, survey_id, farmer_id, flow_id, status, needs_follow_up, "
                        "recorded_at, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (response_key) DO NOTHING",
                        (record["response_key"], record["survey_id"], record["farmer_id"], flow_id, record["status"],
                         int(bool(record.get("needs_follow_up"))), record["recorded_at"], _dumps(record)))
        return cur.rowcount == 1

    def opt_out(self, farmer_id: str, response_key: str, recorded_at: str) -> None:
        self._run("INSERT INTO opt_outs (farmer_id, response_key, recorded_at) VALUES (?, ?, ?) "
                  "ON CONFLICT (farmer_id) DO NOTHING", (farmer_id, response_key, recorded_at))

    # ------------------------------------------------------------------- reads
    def handoff(self, handoff_id: str) -> tuple[dict, str, str] | None:
        """(hand-off, admission, reason) or None."""
        rows = self._rows("SELECT body, admission, reason FROM handoffs WHERE handoff_id = ?", (handoff_id,))
        return (json.loads(rows[0][0]), rows[0][1], rows[0][2]) if rows else None

    def handoff_by_flow(self, flow_id: str) -> tuple[dict, str, str] | None:
        rows = self._rows("SELECT body, admission, reason FROM handoffs WHERE flow_id = ? ORDER BY handoff_id", (flow_id,))
        return (json.loads(rows[0][0]), rows[0][1], rows[0][2]) if rows else None

    def farmer_handoffs(self, farmer_id: str) -> list[dict]:
        """This farmer's hand-offs that hold a weekly slot, earliest send first: what the cap counts."""
        rows = self._rows("SELECT body FROM handoffs WHERE farmer_id = ? AND admission IN (?, ?) "
                          "ORDER BY not_before, handoff_id", (farmer_id, *SENDABLE))
        return [json.loads(r[0]) for r in rows]

    def due(self, at_ist: str) -> list[dict]:
        """Hand-offs whose window has opened and that have not expired at `at_ist` (an IST timestamp as
        mel.timing.fmt_ist writes it, so the strings compare in time order)."""
        rows = self._rows("SELECT body FROM handoffs WHERE admission IN (?, ?) AND not_before <= ? AND expires_at >= ?",
                          (*SENDABLE, at_ist, at_ist))
        return [json.loads(r[0]) for r in rows]

    def opted_out(self, farmer_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM opt_outs WHERE farmer_id = ?", (farmer_id,)))

    def response(self, response_key: str) -> dict | None:
        rows = self._rows("SELECT body FROM responses WHERE response_key = ?", (response_key,))
        return json.loads(rows[0][0]) if rows else None

    def follow_ups(self, limit: int | None = None) -> list[dict]:
        """Answer records that need a person, oldest first."""
        rows = self._rows("SELECT body FROM responses WHERE needs_follow_up = 1 ORDER BY recorded_at, response_key")
        out = [json.loads(r[0]) for r in rows]
        return out if limit is None else out[:limit]

    def counts(self) -> dict[str, int]:
        return {t: self._rows(f"SELECT COUNT(*) FROM {t}")[0][0] for t in TABLES}
