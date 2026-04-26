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
                id                    INTEGER PRIMARY KEY,
                locus_auth_token      TEXT,
                merchant_locus_token  TEXT,
                max_task_budget       REAL    DEFAULT 0.0,
                daily_limit           REAL    DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS agent_policies (
                id                      INTEGER PRIMARY KEY,
                required_assessor_score REAL    DEFAULT 4.5,
                allowed_service_types   TEXT    DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS rfps (
                id                TEXT PRIMARY KEY,
                buyer_id          TEXT NOT NULL,
                task_spec         TEXT NOT NULL,
                max_budget        REAL NOT NULL,
                currency          TEXT DEFAULT 'USDC',
                deadline_seconds  INTEGER NOT NULL,
                min_reputation    REAL DEFAULT 0.0,
                verification_type TEXT DEFAULT 'manual',
                status            TEXT DEFAULT 'Open',
                escrow_session_id TEXT,
                webhook_secret    TEXT,
                verifying_bid_id  TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bids (
                id                  TEXT PRIMARY KEY,
                rfp_id              TEXT NOT NULL REFERENCES rfps(id),
                seller_id           TEXT NOT NULL,
                seller_email        TEXT NOT NULL,
                bid_amount          REAL NOT NULL,
                eta_seconds         INTEGER NOT NULL,
                status              TEXT DEFAULT 'Pending',
                locus_transaction_id TEXT,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Migrations for databases created before these columns existed
        for migration in [
            "ALTER TABLE owner ADD COLUMN merchant_locus_token TEXT",
            "ALTER TABLE rfps ADD COLUMN webhook_secret TEXT",
            "ALTER TABLE rfps ADD COLUMN verifying_bid_id TEXT",
            "ALTER TABLE bids ADD COLUMN locus_transaction_id TEXT",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass

        if not conn.execute("SELECT 1 FROM owner WHERE id = 1").fetchone():
            conn.execute(
                "INSERT INTO owner (id, locus_auth_token, merchant_locus_token, max_task_budget, daily_limit) VALUES (1, NULL, NULL, 0.0, 0.0)"
            )
        if not conn.execute("SELECT 1 FROM agent_policies WHERE id = 1").fetchone():
            conn.execute(
                "INSERT INTO agent_policies (id, required_assessor_score, allowed_service_types) VALUES (1, 4.5, '[]')"
            )


# ── Owner functions ───────────────────────────────────────────────────────────

def get_owner() -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM owner WHERE id = 1").fetchone()
        return dict(row) if row else {}


def update_mandate(
    token: str, merchant_token: str, max_budget: float, daily_limit: float
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE owner
               SET locus_auth_token = ?, merchant_locus_token = ?,
                   max_task_budget = ?, daily_limit = ?
               WHERE id = 1""",
            (token, merchant_token, max_budget, daily_limit),
        )


# ── Policy functions ──────────────────────────────────────────────────────────

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


# ── RFP functions ─────────────────────────────────────────────────────────────

def create_rfp(
    id: str, buyer_id: str, task_spec: str, max_budget: float,
    deadline_seconds: int, min_reputation: float, verification_type: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO rfps
               (id, buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (id, buyer_id, task_spec, max_budget, deadline_seconds, min_reputation, verification_type),
        )


def get_rfps(status: str | None = None) -> list[dict]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM rfps WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM rfps ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_rfp(rfp_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM rfps WHERE id = ?", (rfp_id,)).fetchone()
        return dict(row) if row else None


def get_rfp_by_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM rfps WHERE escrow_session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def set_rfp_verifying(
    rfp_id: str, session_id: str, webhook_secret: str, bid_id: str
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE rfps
               SET status = 'Verifying', escrow_session_id = ?,
                   webhook_secret = ?, verifying_bid_id = ?
               WHERE id = ?""",
            (session_id, webhook_secret, bid_id, rfp_id),
        )


def revert_rfp_to_open(rfp_id: str) -> None:
    """Roll back a failed escrow attempt — RFP returns to Open, bid to Pending."""
    with _connect() as conn:
        rfp = conn.execute("SELECT verifying_bid_id FROM rfps WHERE id = ?", (rfp_id,)).fetchone()
        conn.execute(
            "UPDATE rfps SET status = 'Open', escrow_session_id = NULL, webhook_secret = NULL, verifying_bid_id = NULL WHERE id = ?",
            (rfp_id,),
        )
        if rfp and rfp["verifying_bid_id"]:
            conn.execute(
                "UPDATE bids SET status = 'Pending' WHERE id = ?",
                (rfp["verifying_bid_id"],),
            )


# ── Bid functions ─────────────────────────────────────────────────────────────

def create_bid(
    id: str, rfp_id: str, seller_id: str, seller_email: str,
    bid_amount: float, eta_seconds: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO bids (id, rfp_id, seller_id, seller_email, bid_amount, eta_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id, rfp_id, seller_id, seller_email, bid_amount, eta_seconds),
        )


def get_bids_for_rfp(rfp_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bids WHERE rfp_id = ? ORDER BY created_at ASC", (rfp_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def accept_bid(bid_id: str, rfp_id: str, session_id: str, transaction_id: str) -> None:
    """Atomically lock RFP, accept winning bid, reject all others."""
    with _connect() as conn:
        conn.execute(
            "UPDATE rfps SET status = 'Locked', escrow_session_id = ?, verifying_bid_id = NULL WHERE id = ?",
            (session_id, rfp_id),
        )
        conn.execute(
            "UPDATE bids SET status = 'Accepted', locus_transaction_id = ? WHERE id = ?",
            (transaction_id, bid_id),
        )
        conn.execute(
            "UPDATE bids SET status = 'Rejected' WHERE rfp_id = ? AND id != ?",
            (rfp_id, bid_id),
        )
