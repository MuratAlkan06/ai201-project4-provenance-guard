"""
audit_log.py — persistence and the append-only audit trail.

Two tables, on purpose:
  * content    : current state per submission (status is updated in place on appeal)
  * audit_log  : append-only event history (never updated or deleted)

An appeal appends a NEW audit_log row and flips content.status to 'under_review'. The
original classification event is never overwritten — the log is the evidentiary record of
what happened, including the decision a creator is contesting.
"""

import os
import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("PG_DB_PATH", "provenance_guard.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                content_id   TEXT PRIMARY KEY,
                creator_id   TEXT,
                text         TEXT,
                attribution  TEXT,
                confidence   REAL,
                llm_score    REAL,
                stylo_score  REAL,
                status       TEXT,
                created_at   TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id        TEXT,
                event_type        TEXT,
                timestamp         TEXT,
                attribution       TEXT,
                confidence        REAL,
                llm_score         REAL,
                stylo_score       REAL,
                status            TEXT,
                appeal_reasoning  TEXT
            )
            """
        )


def record_submission(content_id, creator_id, text, result):
    """Insert the content row and append a 'classified' audit event."""
    ts = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO content (content_id, creator_id, text, attribution, confidence, "
            "llm_score, stylo_score, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                content_id, creator_id, text, result["attribution"], result["confidence"],
                result["llm_score"], result["stylo_score"], "classified", ts,
            ),
        )
        conn.execute(
            "INSERT INTO audit_log (content_id, event_type, timestamp, attribution, "
            "confidence, llm_score, stylo_score, status, appeal_reasoning) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                content_id, "classified", ts, result["attribution"], result["confidence"],
                result["llm_score"], result["stylo_score"], "classified", None,
            ),
        )


def get_content(content_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM content WHERE content_id = ?", (content_id,)
        ).fetchone()
        return dict(row) if row else None


def record_appeal(content_id, creator_reasoning):
    """
    Flip content.status to 'under_review' (in place) and APPEND an appeal event that
    references the original decision. Returns False if the content_id is unknown.
    """
    original = get_content(content_id)
    if original is None:
        return False
    ts = _now()
    with _conn() as conn:
        conn.execute(
            "UPDATE content SET status = ? WHERE content_id = ?",
            ("under_review", content_id),
        )
        conn.execute(
            "INSERT INTO audit_log (content_id, event_type, timestamp, attribution, "
            "confidence, llm_score, stylo_score, status, appeal_reasoning) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                content_id, "appeal", ts, original["attribution"], original["confidence"],
                original["llm_score"], original["stylo_score"], "under_review",
                creator_reasoning,
            ),
        )
    return True


def get_recent_log(n=20):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]
