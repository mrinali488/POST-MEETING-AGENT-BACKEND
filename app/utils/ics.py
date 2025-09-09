from datetime import datetime, timedelta
from pathlib import Path
import re, uuid

def _dtstamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")

def slugify(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]+', '-', text).strip('-').lower()

def create_ics(title: str, start: datetime | None = None, duration_minutes: int = 30) -> str:
    """Create a minimal .ics file and return its absolute path."""
    start = start or (datetime.utcnow() + timedelta(days=1, hours=9))  # default: tomorrow 9:00 UTC
    end = start + timedelta(minutes=duration_minutes)

    uid = f"{uuid.uuid4()}@postmeeting-agent"
    content = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//PostMeetingAgent//EN\n"
        "BEGIN:VEVENT\n"
        f"UID:{uid}\n"
        f"DTSTAMP:{_dtstamp(datetime.utcnow())}\n"
        f"DTSTART:{_dtstamp(start)}\n"
        f"DTEND:{_dtstamp(end)}\n"
        f"SUMMARY:{title}\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )

    outdir = Path(__file__).resolve().parent.parent / "tmp"
    outdir.mkdir(parents=True, exist_ok=True)
    fname = f"{slugify(title) or 'event'}-{uid[:8]}.ics"
    fpath = outdir / fname
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    return str(fpath)
