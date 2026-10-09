import sqlite3
from pathlib import Path
from uuid import uuid4
from datetime import date as date_type, time as time_type

DB_FILE = Path(__file__).parent / "campusops.db"


def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS venues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK(capacity > 0),
                facilities TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                venue_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                attendees INTEGER NOT NULL CHECK(attendees > 0),
                status TEXT NOT NULL DEFAULT 'Pending',
                FOREIGN KEY (venue_id) REFERENCES venues(id)
            )
        """)

        if conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO venues (name, capacity, facilities) VALUES (?, ?, ?)",
                [
                    ("Seminar Hall", 100, "Projector, Sound System"),
                    ("Main Auditorium", 300, "Stage, Microphones"),
                    ("Computer Lab", 60, "Computers, Projector"),
                ],
            )


def list_venues():
    init_db()
    with get_connection() as conn:
        return [
            dict(row) for row in
            conn.execute("SELECT * FROM venues ORDER BY id").fetchall()
        ]
def check_availability(venue_id, date, start_time, end_time):
    init_db()

    try:
        date_type.fromisoformat(date)
        start = time_type.fromisoformat(start_time)
        end = time_type.fromisoformat(end_time)
    except (ValueError, TypeError):
        raise ValueError("Use date YYYY-MM-DD and time HH:MM.")

    if end <= start:
        raise ValueError("End time must be after start time.")

    with get_connection() as conn:
        venue = conn.execute(
            "SELECT id FROM venues WHERE id = ?",
            (venue_id,)
        ).fetchone()

        if venue is None:
            raise ValueError("Venue not found.")

        conflicts = conn.execute(
            """SELECT COUNT(*) FROM bookings
               WHERE venue_id = ? AND date = ?
               AND status IN ('Pending', 'Confirmed')
               AND start_time < ? AND end_time > ?""",
            (venue_id, date, end_time, start_time),
        ).fetchone()[0]

    return {
        "venue_id": venue_id,
        "available": conflicts == 0,
        "message": (
            "Venue is available."
            if conflicts == 0
            else "Venue has a pending or confirmed booking at that time."
        )
    }


def create_booking(venue_id, date, start_time, end_time, attendees):
    init_db()

    if type(attendees) is not int or attendees <= 0:
        raise ValueError("Attendees must be a positive whole number.")

    availability = check_availability(
        venue_id, date, start_time, end_time
    )
    if not availability["available"]:
        raise ValueError("Venue is not available at that time.")

    with get_connection() as conn:
        venue = conn.execute(
            "SELECT capacity FROM venues WHERE id = ?", (venue_id,)
        ).fetchone()

        if attendees > venue["capacity"]:
            raise ValueError("Attendees exceed venue capacity.")

        booking = {
            "id": "B-" + uuid4().hex[:8],
            "venue_id": venue_id,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "attendees": attendees,
            "status": "Pending",
        }

        conn.execute(
            """INSERT INTO bookings
               (id, venue_id, date, start_time, end_time, attendees, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                booking["id"], venue_id, date, start_time,
                end_time, attendees, "Pending"
            ),
        )

    return booking


def list_bookings():
    init_db()
    with get_connection() as conn:
        return [
            dict(row) for row in
            conn.execute(
                "SELECT * FROM bookings ORDER BY date, start_time"
            ).fetchall()
        ]


init_db()
