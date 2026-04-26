import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "lescrow.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS owner (
                id               INTEGER PRIMARY KEY,
                locus_auth_token TEXT,
                max_task_budget  REAL    DEFAULT 0.0,
                daily_limit      REAL    DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS agent_policies (
                id                      INTEGER PRIMARY KEY,
                required_assessor_score REAL    DEFAULT 4.5,
                allowed_service_types   TEXT    DEFAULT '[]'
            );
        """)
        if not conn.execute("SELECT 1 FROM owner WHERE id = 1").fetchone():
            conn.execute(
                "INSERT INTO owner (id, locus_auth_token, max_task_budget, daily_limit) VALUES (1, NULL, 0.0, 0.0)"
            )
        if not conn.execute("SELECT 1 FROM agent_policies WHERE id = 1").fetchone():
            conn.execute(
                "INSERT INTO agent_policies (id, required_assessor_score, allowed_service_types) VALUES (1, 4.5, '[]')"
            )


def get_owner() -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM owner WHERE id = 1").fetchone()
        return dict(row) if row else {}


def update_mandate(token: str, max_budget: float, daily_limit: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE owner SET locus_auth_token = ?, max_task_budget = ?, daily_limit = ? WHERE id = 1",
            (token, max_budget, daily_limit),
        )


def get_policy() -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM agent_policies WHERE id = 1").fetchone()
        return dict(row) if row else {}


def update_policy(required_assessor_score: float, allowed_service_types: list) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE agent_policies SET required_assessor_score = ?, allowed_service_types = ? WHERE id = 1",
            (required_assessor_score, json.dumps(allowed_service_types)),
        )
