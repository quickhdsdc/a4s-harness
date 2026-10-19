"""Fresh demo slots follow the current clock and the MES local calendar."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from a4s.machines.festo_cp_lab.production_schedule import lots, next_start


def test_new_schedule_tracks_now_at_whole_hours():
    now = datetime(2026, 10, 2, 11, 42, 1, tzinfo=timezone.utc)
    start = next_start(now)
    assert start == datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    assert timedelta(minutes=15) <= start - now < timedelta(minutes=75)
    schedule = lots(start, 'Europe/Berlin')
    assert schedule[0]['planned_start_at'] == start.isoformat()
    assert len(schedule) == 1
    assert schedule[0]['planned_end_at'] == (start + timedelta(minutes=45)).isoformat()


def test_due_date_uses_berlin_date_at_slot_end():
    start = datetime(2026, 10, 2, 20, 30, tzinfo=timezone.utc)
    schedule = lots(start, 'Europe/Berlin')
    assert [slot['due_date'] for slot in schedule] == ['2026-10-02']


@pytest.mark.parametrize('now,expected', [
    ('2026-10-07T00:00:00+02:00', '2026-10-07T01:00:00+02:00'),
    ('2026-10-07T00:20:00+02:00', '2026-10-07T01:00:00+02:00'),
    ('2026-10-07T00:50:00+02:00', '2026-10-07T02:00:00+02:00'),
    ('2026-10-07T23:30:00+02:00', '2026-10-08T00:00:00+02:00'),
    ('2026-10-25T01:40:00+02:00', '2026-10-25T03:00:00+01:00'),
])
def test_fresh_reset_uses_current_berlin_date_and_future_hour(now, expected):
    start = next_start(datetime.fromisoformat(now), 'Europe/Berlin')
    assert start == datetime.fromisoformat(expected)
    assert start.astimezone(ZoneInfo('Europe/Berlin')).minute == 0


def test_midnight_example_creates_two_new_slots_for_october_7():
    now = datetime(2026, 10, 7, 0, tzinfo=ZoneInfo('Europe/Berlin'))
    schedule = lots(next_start(now), 'Europe/Berlin')
    times = [(datetime.fromisoformat(row['planned_start_at']).astimezone(now.tzinfo).strftime('%H:%M'),
              datetime.fromisoformat(row['planned_end_at']).astimezone(now.tzinfo).strftime('%H:%M')) for row in schedule]
    assert times == [('01:00', '01:45')]
    assert [row['due_date'] for row in schedule] == ['2026-10-07']
