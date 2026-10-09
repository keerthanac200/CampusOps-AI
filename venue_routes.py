import os
import sqlite3
import uuid

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = Path(
    os.getenv("CAMPUSOPS_DB_PATH", str(BASE_DIR / "campusops.db"))
)

router = APIRouter(tags=["Smart Campus Venue Booking"])

VALID_VENUE_TYPES = {
    "indoor_auditorium",
    "outdoor_amphitheatre",
    "seminar_hall",
    "event_room",
}

BLOCKING_STATUSES = ("pending_approval", "approved")


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

@contextmanager
def get_db():
    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=10,
        isolation_level=None,
    )

    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        connection.close()


def initialize_venue_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS venues (
                venue_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                venue_type TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK(capacity > 0),
                location TEXT NOT NULL,
                facilities TEXT NOT NULL,
                opening_time TEXT NOT NULL,
                closing_time TEXT NOT NULL,
                booking_deadline_days INTEGER NOT NULL DEFAULT 2,
                deadline_time TEXT NOT NULL DEFAULT '17:00',
                is_sample_data INTEGER NOT NULL DEFAULT 1
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id TEXT PRIMARY KEY,
                venue_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                description TEXT NOT NULL,
                event_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                attendance INTEGER NOT NULL,
                organizer TEXT NOT NULL,
                status TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                FOREIGN KEY (venue_id) REFERENCES venues(venue_id)
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_booking_venue_date
            ON bookings(venue_id, event_date, status)
        """)

        # Clearly identified DEMO data.
        # These are not actual college venue records.
        venue_count = db.execute(
            "SELECT COUNT(*) FROM venues"
        ).fetchone()[0]

        if venue_count == 0:
            sample_venues = [
                (
                    "VEN-001",
                    "Sample Main Auditorium",
                    "indoor_auditorium",
                    500,
                    "Sample Main Building",
                    "Projector, Sound System, Stage, Air Conditioning",
                    "09:00",
                    "18:00",
                    2,
                    "17:00",
                    1,
                ),
                (
                    "VEN-002",
                    "Sample Outdoor Amphitheatre",
                    "outdoor_amphitheatre",
                    250,
                    "Sample Open Campus Grounds",
                    "Open Stage, Seating, Public Address System",
                    "08:00",
                    "18:00",
                    3,
                    "17:00",
                    1,
                ),
                (
                    "VEN-003",
                    "Sample Seminar Hall",
                    "seminar_hall",
                    100,
                    "Sample Academic Block",
                    "Projector, Whiteboard, Wi-Fi",
                    "09:00",
                    "17:00",
                    2,
                    "17:00",
                    1,
                ),
                (
                    "VEN-004",
                    "Sample Innovation Event Room",
                    "event_room",
                    40,
                    "Sample Innovation Center",
                    "Tables, Chairs, Wi-Fi, Display",
                    "09:00",
                    "17:00",
                    1,
                    "17:00",
                    1,
                ),
            ]

            db.executemany("""
                INSERT INTO venues (
                    venue_id, name, venue_type, capacity,
                    location, facilities, opening_time,
                    closing_time, booking_deadline_days,
                    deadline_time, is_sample_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_venues)


initialize_venue_database()


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class BookingRequest(BaseModel):
    venue_id: str
    event_name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=1000)
    event_date: date
    start_time: str
    end_time: str
    attendance: int = Field(gt=0)
    organizer: str = Field(min_length=2, max_length=150)

    @model_validator(mode="after")
    def validate_time_range(self):
        start = parse_time(self.start_time)
        end = parse_time(self.end_time)

        if start >= end:
            raise ValueError("Start time must be before end time.")

        return self


class BookingDecision(BaseModel):
    status: str
    admin_id: str = Field(min_length=2, max_length=100)


# --------------------------------------------------
# VALIDATION HELPERS
# --------------------------------------------------

def parse_time(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={
                "success": False,
                "error": "Invalid time format.",
                "message": "Use 24-hour HH:MM format, for example 14:30.",
            },
        )


def get_venue_or_404(db, venue_id: str):
    venue = db.execute(
        "SELECT * FROM venues WHERE venue_id = ?",
        (venue_id,),
    ).fetchone()

    if venue is None:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": "venue_not_found",
                "message": f"Venue {venue_id} does not exist.",
            },
        )

    return dict(venue)


def get_booking_deadline(venue: dict, event_date: date) -> datetime:
    deadline_date = event_date - timedelta(
        days=venue["booking_deadline_days"]
    )

    cutoff = time.fromisoformat(venue["deadline_time"])

    return datetime.combine(deadline_date, cutoff)


def check_deadline(venue: dict, event_date: date):
    deadline = get_booking_deadline(venue, event_date)
    now = datetime.now()

    if event_date < now.date():
        return False, deadline.isoformat(), "The event date has passed."

    if now >= deadline:
        return (
            False,
            deadline.isoformat(),
            "The booking deadline has passed.",
        )

    return True, deadline.isoformat(), None


def find_conflicts(
    db,
    venue_id: str,
    event_date: date,
    start_time: str,
    end_time: str,
    exclude_booking_id: Optional[str] = None,
):
    # Half-open intervals: an event ending at 11:00
    # does not conflict with one beginning at 11:00.
    query = """
        SELECT booking_id, event_name, start_time, end_time, status
        FROM bookings
        WHERE venue_id = ?
          AND event_date = ?
          AND status IN ('pending_approval', 'approved')
          AND start_time < ?
          AND end_time > ?
    """

    params = [
        venue_id,
        event_date.isoformat(),
        end_time,
        start_time,
    ]

    if exclude_booking_id:
        query += " AND booking_id != ?"
        params.append(exclude_booking_id)

    rows = db.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def check_availability(
    db,
    venue: dict,
    event_date: date,
    start_time: str,
    end_time: str,
    attendance: Optional[int] = None,
    exclude_booking_id: Optional[str] = None,
):
    start = parse_time(start_time)
    end = parse_time(end_time)

    if start >= end:
        raise HTTPException(
            status_code=422,
            detail="Start time must be before end time.",
        )

    opening = time.fromisoformat(venue["opening_time"])
    closing = time.fromisoformat(venue["closing_time"])

    deadline_ok, deadline, deadline_reason = check_deadline(
        venue,
        event_date,
    )

    if attendance is not None and attendance > venue["capacity"]:
        return {
            "available": False,
            "reason": "Attendance exceeds venue capacity.",
            "capacity": venue["capacity"],
            "deadline": deadline,
            "conflicts": [],
        }

    if start < opening or end > closing:
        return {
            "available": False,
            "reason": (
                f"Venue operating hours are "
                f"{venue['opening_time']}–{venue['closing_time']}."
            ),
            "deadline": deadline,
            "conflicts": [],
        }

    if not deadline_ok:
        return {
            "available": False,
            "reason": deadline_reason,
            "deadline": deadline,
            "conflicts": [],
        }

    conflicts = find_conflicts(
        db,
        venue["venue_id"],
        event_date,
        start_time,
        end_time,
        exclude_booking_id,
    )

    if conflicts:
        return {
            "available": False,
            "reason": "This time slot conflicts with another reservation.",
            "deadline": deadline,
            "conflicts": conflicts,
        }

    return {
        "available": True,
        "reason": None,
        "deadline": deadline,
        "conflicts": [],
    }


# --------------------------------------------------
# VENUE DISCOVERY
# --------------------------------------------------

@router.get("/venues")
def list_venues(
    venue_type: Optional[str] = None,
    min_capacity: int = Query(default=1, ge=1),
    location: Optional[str] = None,
):
    if venue_type and venue_type not in VALID_VENUE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "success": False,
                "error": "Invalid venue type.",
                "valid_types": sorted(VALID_VENUE_TYPES),
            },
        )

    query = """
        SELECT * FROM venues
        WHERE capacity >= ?
    """
    params = [min_capacity]

    if venue_type:
        query += " AND venue_type = ?"
        params.append(venue_type)

    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")

    query += " ORDER BY capacity DESC"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()

    venues = []

    for row in rows:
        item = dict(row)
        item["facilities"] = item["facilities"].split(", ")
        item["data_source"] = (
            "SAMPLE DEMO DATA"
            if item["is_sample_data"]
            else "CONFIGURED VENUE DATA"
        )
        venues.append(item)

    return {
        "success": True,
        "count": len(venues),
        "venues": venues,
        "notice": "Sample venues are not live college reservation records.",
    }


# --------------------------------------------------
# AVAILABILITY
# --------------------------------------------------

@router.get("/venues/availability")
def venue_availability(
    venue_id: str,
    event_date: date,
    start_time: str,
    end_time: str,
    attendance: Optional[int] = Query(default=None, ge=1),
):
    with get_db() as db:
        venue = get_venue_or_404(db, venue_id)

        result = check_availability(
            db,
            venue,
            event_date,
            start_time,
            end_time,
            attendance,
        )

    return {
        "success": True,
        "venue_id": venue_id,
        "event_date": event_date.isoformat(),
        "start_time": start_time,
        "end_time": end_time,
        "booking_deadline": result["deadline"],
        **result,
    }


# --------------------------------------------------
# CREATE BOOKING REQUEST
# --------------------------------------------------

@router.post("/bookings", status_code=201)
def create_booking_request(request: BookingRequest):
    booking_id = f"BK-{uuid.uuid4().hex[:10].upper()}"

    with get_db() as db:
        # Acquire a write lock before checking and inserting.
        # This prevents concurrent requests from both passing
        # the conflict check and inserting overlapping bookings.
        db.execute("BEGIN IMMEDIATE")

        try:
            venue = get_venue_or_404(db, request.venue_id)

            if request.attendance > venue["capacity"]:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "success": False,
                        "error": "capacity_exceeded",
                        "capacity": venue["capacity"],
                        "requested_attendance": request.attendance,
                    },
                )

            result = check_availability(
                db,
                venue,
                request.event_date,
                request.start_time,
                request.end_time,
                request.attendance,
            )

            if not result["available"]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "success": False,
                        "error": "venue_unavailable",
                        "reason": result["reason"],
                        "booking_deadline": result["deadline"],
                        "conflicts": result["conflicts"],
                    },
                )

            submitted_at = datetime.now().isoformat(timespec="seconds")

            db.execute("""
                INSERT INTO bookings (
                    booking_id, venue_id, event_name, description,
                    event_date, start_time, end_time, attendance,
                    organizer, status, submitted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                booking_id,
                request.venue_id,
                request.event_name,
                request.description,
                request.event_date.isoformat(),
                request.start_time,
                request.end_time,
                request.attendance,
                request.organizer,
                "pending_approval",
                submitted_at,
            ))

            db.execute("COMMIT")

        except Exception:
            db.execute("ROLLBACK")
            raise

    return {
        "success": True,
        "booking_id": booking_id,
        "status": "pending_approval",
        "message": (
            "Your booking request has been submitted "
            "and is awaiting approval. The venue is not yet confirmed."
        ),
        "booking_deadline": result["deadline"],
        "submitted_at": submitted_at,
    }


# --------------------------------------------------
# LIST BOOKINGS
# --------------------------------------------------

@router.get("/bookings")
def list_bookings(
    organizer: Optional[str] = None,
    status: Optional[str] = None,
):
    allowed_statuses = {
        "pending_approval",
        "approved",
        "rejected",
        "cancelled",
    }

    if status and status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail="Invalid booking status.",
        )

    query = """
        SELECT b.*, v.name AS venue_name, v.location,
               v.booking_deadline_days, v.deadline_time
        FROM bookings b
        JOIN venues v ON b.venue_id = v.venue_id
        WHERE 1 = 1
    """
    params = []

    if organizer:
        query += " AND b.organizer = ?"
        params.append(organizer)

    if status:
        query += " AND b.status = ?"
        params.append(status)

    query += " ORDER BY b.submitted_at DESC"

    with get_db() as db:
        rows = db.execute(query, params).fetchall()

    bookings = []

    for row in rows:
        item = dict(row)

        venue = {
            "booking_deadline_days": item["booking_deadline_days"],
            "deadline_time": item["deadline_time"],
        }

        deadline = get_booking_deadline(
            venue,
            date.fromisoformat(item["event_date"]),
        )

        item["booking_deadline"] = deadline.isoformat()
        item.pop("booking_deadline_days", None)
        item.pop("deadline_time", None)

        bookings.append(item)

    return {
        "success": True,
        "count": len(bookings),
        "bookings": bookings,
    }


# --------------------------------------------------
# GET BOOKING DETAILS
# --------------------------------------------------

@router.get("/bookings/{booking_id}")
def get_booking(booking_id: str):
    with get_db() as db:
        row = db.execute("""
            SELECT b.*, v.name AS venue_name, v.location,
                   v.booking_deadline_days, v.deadline_time
            FROM bookings b
            JOIN venues v ON b.venue_id = v.venue_id
            WHERE b.booking_id = ?
        """, (booking_id,)).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": "booking_not_found",
                "booking_id": booking_id,
            },
        )

    booking = dict(row)

    venue = {
        "booking_deadline_days": booking["booking_deadline_days"],
        "deadline_time": booking["deadline_time"],
    }

    booking["booking_deadline"] = get_booking_deadline(
        venue,
        date.fromisoformat(booking["event_date"]),
    ).isoformat()

    booking.pop("booking_deadline_days", None)
    booking.pop("deadline_time", None)

    return {
        "success": True,
        "booking": booking,
    }


# --------------------------------------------------
# ADMIN APPROVAL
# --------------------------------------------------

@router.post("/bookings/{booking_id}/decision")
def decide_booking(
    booking_id: str,
    decision: BookingDecision,
):
    if decision.status not in {"approved", "rejected"}:
        raise HTTPException(
            status_code=422,
            detail="Status must be approved or rejected.",
        )

    # Demo-only guard. Configure a real admin token before
    # using this endpoint beyond a local hackathon demo.
    expected_token = os.getenv("CAMPUSOPS_ADMIN_TOKEN")

    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Administrator approval is disabled. "
                "Set CAMPUSOPS_ADMIN_TOKEN and implement "
                "authentication before enabling approval."
            ),
        )

    # Do not accept admin identity as proof of authorization.
    # This MVP uses a bearer token in the request header instead.
    # See the follow-up note below before using this endpoint.
    raise HTTPException(
        status_code=501,
        detail=(
            "Approval authentication must be connected before "
            "this endpoint can change booking status."
        ),
    )