"""Current-time slots for a fresh local housing demo plan."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LEAD_MINUTES = 15
SLOT_MINUTES = 45


def next_start(now: datetime, timezone_name: str = 'Europe/Berlin') -> datetime:
    """Next MES-local whole hour with at least 15 minutes to review and reset."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Current time must include a timezone')
    zone = ZoneInfo(timezone_name or 'UTC')
    earliest = (now.astimezone(timezone.utc) + timedelta(minutes=LEAD_MINUTES)).astimezone(zone)
    boundary = earliest.replace(minute=0, second=0, microsecond=0)
    if boundary.timestamp() < earliest.timestamp():
        boundary = (boundary.astimezone(timezone.utc) + timedelta(hours=1)).astimezone(zone)
    # OpenMES stores wall-clock timestamps and cannot safely represent a
    # repeated DST hour; schedule after that ambiguity, just like schedule_time.
    while boundary.replace(fold=0).utcoffset() != boundary.replace(fold=1).utcoffset():
        boundary = (boundary.astimezone(timezone.utc) + timedelta(hours=1)).astimezone(zone)
    return boundary.astimezone(timezone.utc)


def lots(start: datetime, timezone_name: str):
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError('Plan start must include a timezone')
    zone = ZoneInfo(timezone_name or 'UTC')
    first = start.astimezone(timezone.utc)
    result = []
    for index, suffix in enumerate(('A',)):
        begin = first + timedelta(minutes=SLOT_MINUTES * index)
        end = begin + timedelta(minutes=SLOT_MINUTES)
        result.append({'lot': suffix, 'planned_start_at': begin.isoformat(),
                       'planned_end_at': end.isoformat(),
                       'due_date': end.astimezone(zone).date().isoformat()})
    return result
