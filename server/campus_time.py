"""Campus-local time helpers without a platform-dependent tz database."""
from datetime import datetime, timedelta, timezone

# India uses UTC+05:30 year-round and does not observe daylight saving time.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def campus_today(now: datetime | None = None) -> str:
    """Return today's date in India Standard Time, including UTC date rollover."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(IST).date().isoformat()
