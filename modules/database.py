"""Small SQLite layer for the conversion history."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('TTS', 'STT')),
    input_data TEXT NOT NULL,
    output_data TEXT NOT NULL,
    language TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    with closing(connect(path)) as conn, conn:
        conn.execute(SCHEMA)


def add_conversion(path: str, op: str, input_data: str, output_data: str, lang: str) -> int:
    with closing(connect(path)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO conversions (operation_type, input_data, output_data, language) "
            "VALUES (?, ?, ?, ?)",
            (op, input_data, output_data, lang),
        )
        return int(cur.lastrowid)


def stats(path: str) -> dict:
    with closing(connect(path)) as conn:
        rows = conn.execute(
            "SELECT operation_type, COUNT(*) FROM conversions GROUP BY operation_type"
        ).fetchall()
        recent = conn.execute(
            "SELECT * FROM conversions ORDER BY created_at DESC, id DESC LIMIT 5"
        ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    return {
        "total": sum(counts.values()),
        "tts": counts.get("TTS", 0),
        "stt": counts.get("STT", 0),
        "recent": recent,
    }


def search(path: str, term: str = "", op: str = "") -> list[sqlite3.Row]:
    """Return history rows, newest first, optionally filtered by text and operation."""
    where, params = [], []
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(input_data LIKE ? ESCAPE '\\' OR output_data LIKE ? ESCAPE '\\')")
        params += [f"%{escaped}%"] * 2
    if op in ("TTS", "STT"):
        where.append("operation_type = ?")
        params.append(op)
    sql = "SELECT * FROM conversions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC"
    with closing(connect(path)) as conn:
        return conn.execute(sql, params).fetchall()


def get(path: str, item_id: int) -> Optional[sqlite3.Row]:
    with closing(connect(path)) as conn:
        return conn.execute("SELECT * FROM conversions WHERE id = ?", (item_id,)).fetchone()


def find_by_filename(path: str, filename: str) -> Optional[sqlite3.Row]:
    """Find the conversion whose stored audio file is ``filename``."""
    with closing(connect(path)) as conn:
        return conn.execute(
            "SELECT * FROM conversions WHERE "
            "(operation_type = 'TTS' AND output_data = ?) OR "
            "(operation_type = 'STT' AND input_data = ?)",
            (filename, filename),
        ).fetchone()


def delete(path: str, item_id: int) -> None:
    with closing(connect(path)) as conn, conn:
        conn.execute("DELETE FROM conversions WHERE id = ?", (item_id,))


def delete_all(path: str) -> None:
    with closing(connect(path)) as conn, conn:
        conn.execute("DELETE FROM conversions")


def audio_filename(row: sqlite3.Row) -> str:
    """Name of the audio file on disk belonging to a history row."""
    return row["output_data"] if row["operation_type"] == "TTS" else row["input_data"]
