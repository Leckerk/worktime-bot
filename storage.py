"""Хранилище данных бота (SQLite).

Таблицы:
  users       — пользователи и их настройки (час напоминания, день статистики)
  entries     — записи о сверхурочных часах по датам
  pending     — активные "ожидания ответа" (бот ждёт кол-во часов после напоминания)
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "worktime.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id      INTEGER PRIMARY KEY,
                reminder_h   INTEGER NOT NULL DEFAULT 20,   -- час напоминания (0-23)
                reminder_m   INTEGER NOT NULL DEFAULT 0,    -- минуты напоминания
                report_day   INTEGER NOT NULL DEFAULT 1,    -- день месяца для статистики
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL REFERENCES users(chat_id),
                day        TEXT NOT NULL,                   -- ISO-дата 'YYYY-MM-DD'
                hours      REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (chat_id, day)
            );

            CREATE TABLE IF NOT EXISTS pending (
                chat_id    INTEGER PRIMARY KEY REFERENCES users(chat_id),
                day        TEXT NOT NULL                    -- за какой день ждём ответ
            );
            """
        )


# ---------- пользователи / настройки ----------

def upsert_user(chat_id: int) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO users (chat_id) VALUES (?) ON CONFLICT(chat_id) DO NOTHING",
            (chat_id,),
        )


def get_settings(chat_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT reminder_h, reminder_m, report_day FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def set_reminder_time(chat_id: int, hour: int, minute: int = 0) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE users SET reminder_h = ?, reminder_m = ? WHERE chat_id = ?",
            (hour, minute, chat_id),
        )


def set_report_day(chat_id: int, day: int) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET report_day = ? WHERE chat_id = ?", (day, chat_id))


def all_users() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("SELECT * FROM users").fetchall()


# ---------- записи ----------

def save_entry(chat_id: int, day: str, hours: float) -> None:
    """Сохраняет/перезаписывает часы за день."""
    with _conn() as c:
        c.execute(
            """INSERT INTO entries (chat_id, day, hours) VALUES (?, ?, ?)
               ON CONFLICT(chat_id, day) DO UPDATE SET hours = excluded.hours,
                                                       created_at = datetime('now')""",
            (chat_id, day, hours),
        )


def month_entries(chat_id: int, year: int, month: int) -> list[sqlite3.Row]:
    like = f"{year:04d}-{month:02d}-%"
    with _conn() as c:
        return c.execute(
            "SELECT day, hours FROM entries WHERE chat_id = ? AND day LIKE ? ORDER BY day",
            (chat_id, like),
        ).fetchall()


# ---------- ожидание ответа ----------

def set_pending(chat_id: int, day: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO pending (chat_id, day) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET day = excluded.day",
            (chat_id, day),
        )


def pop_pending(chat_id: int) -> str | None:
    """Возвращает дату, за которую ждём ответ, и снимает флаг."""
    with _conn() as c:
        row = c.execute("SELECT day FROM pending WHERE chat_id = ?", (chat_id,)).fetchone()
        if row:
            c.execute("DELETE FROM pending WHERE chat_id = ?", (chat_id,))
            return row["day"]
    return None


def today() -> str:
    return date.today().isoformat()
