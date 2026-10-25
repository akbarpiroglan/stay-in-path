"""SQLite persistence and calendar math for Stay in Path (no GUI dependencies)."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("SIP_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "StayInPath"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "StayInPath"


class Store:
    def __init__(self, db_path: Path | None = None):
        self.path = Path(db_path) if db_path else data_dir() / "stay_in_path.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('yesno', 'time')),
                goal_minutes INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                created_on TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS logs (
                habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                day TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0 CHECK(value >= 0),
                PRIMARY KEY(habit_id, day)
            );
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER REFERENCES habits(id) ON DELETE SET NULL,
                day TEXT NOT NULL,
                seconds INTEGER NOT NULL CHECK(seconds > 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mission (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 1,
                deadline TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO mission(id,title,completed,total,deadline)
                VALUES (1,'Define your main mission',0,4,'');
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def habits(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM habits WHERE active=1 ORDER BY id").fetchall()]

    def add_habit(self, name: str, kind: str, goal_minutes: int = 1):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Habit name must be 1–80 characters.")
        if kind not in ("yesno", "time"):
            raise ValueError("Invalid habit type.")
        if not 1 <= int(goal_minutes) <= 1440:
            raise ValueError("Goal must be between 1 and 1440 minutes.")
        with self.db:
            self.db.execute("INSERT INTO habits(name,kind,goal_minutes,created_on) VALUES (?,?,?,?)",
                            (name, kind, int(goal_minutes) if kind == 'time' else 1, date.today().isoformat()))

    def delete_habit(self, habit_id: int):
        """Archive the habit without erasing historical logs or focus sessions."""
        with self.db:
            self.db.execute("UPDATE habits SET active=0 WHERE id=?", (habit_id,))

    def log_value(self, habit_id: int, day: str | None = None) -> float:
        day = day or date.today().isoformat()
        r = self.db.execute("SELECT value FROM logs WHERE habit_id=? AND day=?", (habit_id, day)).fetchone()
        return float(r[0]) if r else 0.0

    def set_log(self, habit_id: int, value: float, day: str | None = None):
        day = day or date.today().isoformat()
        value = max(0.0, float(value))
        with self.db:
            self.db.execute("""INSERT INTO logs(habit_id,day,value) VALUES (?,?,?)
                          ON CONFLICT(habit_id,day) DO UPDATE SET value=excluded.value""",
                            (habit_id, day, value))

    def add_focus(self, habit_id: int, seconds: int, day: str | None = None):
        if seconds <= 0:
            return
        habit = self.db.execute("SELECT kind FROM habits WHERE id=? AND active=1", (habit_id,)).fetchone()
        if not habit or habit[0] != 'time':
            raise ValueError("Focus sessions require an active time-based habit.")
        day = day or date.today().isoformat()
        with self.db:
            self.db.execute("INSERT INTO focus_sessions(habit_id,day,seconds,created_at) VALUES (?,?,?,?)",
                            (habit_id, day, seconds, datetime.now().isoformat(timespec='seconds')))
            self.db.execute("""INSERT INTO logs(habit_id,day,value) VALUES (?,?,?)
                ON CONFLICT(habit_id,day) DO UPDATE SET value=value+excluded.value""",
                            (habit_id, day, seconds / 60.0))

    def get_mission(self):
        return dict(self.db.execute("SELECT * FROM mission WHERE id=1").fetchone())

    def save_mission(self, title: str, completed: int, total: int, deadline: str):
        title = title.strip()
        if not title or len(title) > 140:
            raise ValueError("Mission title must be 1–140 characters.")
        if total < 1 or completed < 0 or completed > total:
            raise ValueError("Mission progress is invalid.")
        if deadline:
            date.fromisoformat(deadline)
        with self.db:
            self.db.execute("UPDATE mission SET title=?,completed=?,total=?,deadline=? WHERE id=1",
                            (title, completed, total, deadline))

    def setting(self, key: str, default: str = '') -> str:
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def save_setting(self, key: str, value: str):
        with self.db:
            self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _all_logs(self, start: str, end: str) -> dict[tuple[int, str], float]:
        return {(r['habit_id'], r['day']): float(r['value']) for r in self.db.execute(
            "SELECT * FROM logs WHERE day>=? AND day<=?", (start, end))}

    @staticmethod
    def percent(habit: dict, value: float) -> float:
        if habit['kind'] == 'yesno':
            return 1.0 if value >= 1 else 0.0
        return min(1.0, value / max(1, habit['goal_minutes']))

    def calendar(self, days: int = 91, habit_id: int | None = None, today: date | None = None):
        """Map ISO day => fraction completed; None if habit didn't yet exist.

        A global day is an average across active habits existing on that date.
        """
        today = today or date.today()
        start = today - timedelta(days=days - 1)
        logs = self._all_logs(start.isoformat(), today.isoformat())
        habits = [h for h in self.habits() if habit_id is None or h['id'] == habit_id]
        output = {}
        for n in range(days):
            day = (start + timedelta(days=n)).isoformat()
            eligible = [h for h in habits if h['created_on'] <= day]
            output[day] = (sum(self.percent(h, logs.get((h['id'], day), 0)) for h in eligible)
                           / len(eligible) if eligible else None)
        return output

    def streaks(self, habit_id: int | None = None, today: date | None = None) -> tuple[int, int]:
        """Current and all-time longest streak of fully completed days.

        An unfinished day today doesn't break yesterday's current streak yet.
        """
        today = today or date.today()
        habits = [h for h in self.habits() if habit_id is None or h['id'] == habit_id]
        if not habits:
            return (0, 0)
        first = min(date.fromisoformat(h['created_on']) for h in habits)
        days = (today - first).days + 1
        if days <= 0:
            return (0, 0)
        calendar = self.calendar(days, habit_id, today)
        ordered = [calendar[(first + timedelta(days=i)).isoformat()] for i in range(days)]
        longest = running = 0
        for value in ordered:
            if value is not None and value >= 1 - 1e-9:
                running += 1
                longest = max(longest, running)
            else:
                running = 0
        current = running
        if not current and len(ordered) >= 2 and ordered[-2] is not None and ordered[-2] >= 1 - 1e-9:
            i = len(ordered) - 2
            while i >= 0 and ordered[i] is not None and ordered[i] >= 1 - 1e-9:
                current += 1
                i -= 1
        return current, longest

    def weekly_review(self, today: date | None = None):
        today = today or date.today()
        week_start = today - timedelta(days=today.weekday())
        prev_start = week_start - timedelta(days=7)
        first_day = min((date.fromisoformat(h['created_on']) for h in self.habits()), default=today)
        calendar = self.calendar(max(14, (today - first_day).days + 1), today=today)

        def avg(start, end):
            values = [calendar.get((start + timedelta(days=i)).isoformat()) for i in range((end - start).days + 1)]
            values = [x for x in values if x is not None]
            return round(sum(values) * 100 / len(values)) if values else 0

        focus = self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM focus_sessions WHERE day>=? AND day<=?",
                                (week_start.isoformat(), today.isoformat())).fetchone()[0]
        prev_focus = self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM focus_sessions WHERE day>=? AND day<?",
                                     (prev_start.isoformat(), week_start.isoformat())).fetchone()[0]
        habits = []
        for h in self.habits():
            hcal = self.calendar(max(14, (today - date.fromisoformat(h['created_on'])).days+1), h['id'], today)
            vals = [hcal.get((week_start + timedelta(days=i)).isoformat()) for i in range((today - week_start).days + 1)]
            vals = [v for v in vals if v is not None]
            habits.append((h['name'], round(sum(vals)*100/len(vals)) if vals else 0))
        return {
            'start': week_start.isoformat(), 'end': today.isoformat(),
            'completion': avg(week_start, today),
            'previous_completion': avg(prev_start, week_start-timedelta(days=1)),
            'focus_minutes': round(focus / 60), 'previous_focus_minutes': round(prev_focus/60),
            'habit_rates': habits,
        }
