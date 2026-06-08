import sqlite3
import uuid
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from config import DATABASE_PATH, DATABASE_DIR, MAX_LETTERS_PER_DAY, LOCK_DURATION_SECONDS

import llm

BEIJING = timezone(timedelta(hours=8))


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    os.makedirs(DATABASE_DIR, exist_ok=True)
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS letters (
                id               TEXT PRIMARY KEY,
                device_id        TEXT NOT NULL,
                content          TEXT NOT NULL,
                target_frequency TEXT NOT NULL,
                status           TEXT DEFAULT 'locked',
                unlock_at        TEXT NOT NULL,
                reply            TEXT,
                persona          TEXT,
                persona_id_used  TEXT,
                era              TEXT,
                is_favorited     INTEGER DEFAULT 0,
                created_at       TEXT DEFAULT (datetime('now')),
                replied_at       TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                persona_id TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(device_id, persona_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_letters_device ON letters(device_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_letters_device_created ON letters(device_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_device ON favorites(device_id)")
        conn.commit()


def check_rate_limit(device_id: str):
    now_beijing = datetime.now(BEIJING)
    today_start = now_beijing.strftime("%Y-%m-%d") + " 00:00:00"
    today_end = (now_beijing + timedelta(days=1)).strftime("%Y-%m-%d") + " 00:00:00"
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM letters WHERE device_id=? AND created_at >= ? AND created_at < ?",
            (device_id, today_start, today_end)
        ).fetchone()
    if row["cnt"] >= MAX_LETTERS_PER_DAY:
        return False
    return True


def get_rate_limit_reset():
    now_beijing = datetime.now(BEIJING)
    return (now_beijing + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def insert_letter(device_id: str, content: str, target_frequency: str):
    letter_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    unlock_at = now_utc + timedelta(seconds=LOCK_DURATION_SECONDS)
    unlock_at_str = unlock_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO letters (id, device_id, content, target_frequency, status, unlock_at) VALUES (?, ?, ?, ?, 'locked', ?)",
            (letter_id, device_id, content, target_frequency, unlock_at_str)
        )
        conn.commit()
    return {"id": letter_id, "unlock_at": unlock_at_str, "status": "locked"}


def get_letters_by_device(device_id: str):
    persona_map = llm.get_persona_map()
    now_utc = datetime.now(timezone.utc)
    result = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM letters WHERE device_id=? ORDER BY created_at DESC",
            (device_id,)
        ).fetchall()

        for row in rows:
            unlock_at = datetime.fromisoformat(row["unlock_at"].replace("Z", "+00:00"))
            remaining = max(0, int((unlock_at - now_utc).total_seconds()))

            persona_name = None
            persona_era = None
            if row["persona"]:
                persona_name = row["persona"]
                persona_era = row["era"]

            actual_persona_id = row["persona_id_used"] or row["target_frequency"]

            entry = {
                "id": row["id"],
                "status": row["status"],
                "unlock_at": row["unlock_at"],
                "remaining_seconds": remaining,
                "persona_id": actual_persona_id,
                "user_content": row["content"],
                "has_reply": row["reply"] is not None,
                "reply_preview": row["reply"],
                "persona_name": persona_name,
                "persona_era": persona_era,
                "is_favorited": bool(row["is_favorited"]),
                "created_at": row["created_at"]
            }
            result.append(entry)
    return result


def open_letter(letter_id: str, device_id: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM letters WHERE id=? AND device_id=?", (letter_id, device_id)
        ).fetchone()

        if not row:
            return {"error": "letter_not_found", "status": 404}

        now_utc = datetime.now(timezone.utc)
        unlock_at = datetime.fromisoformat(row["unlock_at"].replace("Z", "+00:00"))

        if now_utc < unlock_at:
            remaining = max(0, int((unlock_at - now_utc).total_seconds()))
            return {"error": "still_locked", "remaining_seconds": remaining, "status": 403}

        if row["reply"] is not None:
            persona_name = row["persona"] or "未知"
            persona_era = row["era"] or ""
            return {
                "id": row["id"],
                "reply": row["reply"],
                "persona": {"name": persona_name, "era": persona_era},
                "replied_at": row["replied_at"]
            }

        return {"row": dict(row), "status": 200}


def save_reply(letter_id: str, reply: str, persona_name: str, persona_era: str, persona_id_used: str):
    now_utc = datetime.now(timezone.utc)
    replied_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        conn.execute(
            "UPDATE letters SET reply=?, persona=?, persona_id_used=?, era=?, status='replied', replied_at=? WHERE id=?",
            (reply, persona_name, persona_id_used, persona_era, replied_at, letter_id)
        )
        conn.commit()
    return replied_at


def add_favorite(device_id: str, persona_id: str):
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO favorites (device_id, persona_id) VALUES (?, ?)",
                (device_id, persona_id)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_favorites(device_id: str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT persona_id FROM favorites WHERE device_id=? ORDER BY created_at",
            (device_id,)
        ).fetchall()
    return [r["persona_id"] for r in rows]


def toggle_letter_favorite(letter_id: str, device_id: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT is_favorited FROM letters WHERE id=? AND device_id=?",
            (letter_id, device_id)
        ).fetchone()
        if not row:
            return None
        new_val = 0 if row["is_favorited"] else 1
        conn.execute(
            "UPDATE letters SET is_favorited=? WHERE id=?",
            (new_val, letter_id)
        )
        conn.commit()
    return {"id": letter_id, "is_favorited": bool(new_val)}
