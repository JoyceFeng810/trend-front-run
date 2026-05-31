"""SQLite briefing history store."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "briefings.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date    TEXT    NOT NULL,
                signal_count INTEGER NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id        INTEGER NOT NULL REFERENCES runs(id),
                run_date      TEXT    NOT NULL,
                sector        TEXT    NOT NULL,
                title         TEXT    NOT NULL,
                brand         TEXT,
                ticker        TEXT,
                stage         TEXT,
                trend_score INTEGER,
                sources       TEXT,
                signal        TEXT,
                catalyst      TEXT,
                risk          TEXT,
                raw_json      TEXT,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def save_run(run_date: str, signal_count: int) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (run_date, signal_count) VALUES (?, ?)",
            (run_date, signal_count),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


def save_signals(run_id: int, run_date: str, signals: list[dict]) -> None:
    with _connect() as conn:
        for s in signals:
            sources = s.get("sources")
            conn.execute(
                """
                INSERT INTO signals
                    (run_id, run_date, sector, title, brand, ticker,
                     stage, trend_score, sources, signal, catalyst, risk, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run_date,
                    s.get("sector", ""),
                    s.get("title", ""),
                    s.get("brand"),
                    s.get("ticker"),
                    s.get("stage"),
                    s.get("trend_score"),
                    json.dumps(sources) if isinstance(sources, list) else sources,
                    s.get("signal"),
                    s.get("catalyst"),
                    s.get("risk"),
                    json.dumps(s),
                ),
            )
        conn.commit()


def get_recent_signals(days: int = 30) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE created_at >= datetime('now', ?)
            ORDER BY trend_score DESC, created_at DESC
            """,
            (f"-{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run_history(limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
