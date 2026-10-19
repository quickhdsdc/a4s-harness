import time
from pathlib import Path

import pytest

from a4s.machines.festo_cp_lab.live_monitor import Monitor, reduce_sample
from a4s.kernel.prompt import IDENTITY


def sample(press=0, turning=0, at=None, fault=False):
    now = at if at is not None else time.time()
    rows = [{"path": f"{station}.Fault", "value": fault if station == "Press" else False,
             "status": "Good", "dataType": "Boolean", "node": "fault", "endpoint": station}
            for station in ("Press", "Turning")]
    rows += [{"path": f"{station}.ReturnCode", "value": value, "status": "Good",
              "dataType": "Int16", "node": "code", "endpoint": station}
             for station, value in (("Press", press), ("Turning", turning))]
    return {"observed_at": now, "source": "live", "values": rows}


def feed(state, *frames):
    events = []
    for frame in frames:
        state, emitted = reduce_sample(state, frame, frame["observed_at"])
        events.extend(emitted)
    return state, events


def test_code7_independently_triggers_when_all_fault_bits_are_false():
    state, _ = feed({}, sample(), sample())
    state, events = feed(state, sample(turning=7), sample(turning=7), sample(turning=7))
    assert [event["kind"] for event in events] == ["PROCESS_INTERVENTION_RAISED"]
    assert state["stable"] is False and state["process_attention"] is True
    assert events[0]["conditions"] == [{"path": "Turning.ReturnCode", "operator": "eq", "value": 7}]
    assert events[0]["before"]["values"][-1]["value"] == 0
    assert events[0]["after"]["values"][-1]["value"] == 7


def test_baseline_glitch_and_other_codes_do_not_trigger_new_intervention():
    state, events = feed({}, sample(7), sample(7))
    assert [e["kind"] for e in events] == ["BASELINE_PROCESS_INTERVENTION"]
    state, _ = feed({}, sample(), sample())
    state, events = feed(state, sample(7), sample(), sample(9), sample(9), sample())
    assert events == []


@pytest.mark.parametrize("value,kind,status", [("7", "Int16", "Good"), (True, "Boolean", "Good"), (7.0, "Double", "Good"), (7, "Int16", "Bad")])
def test_bad_return_code_cannot_trigger_or_clear_an_existing_condition(value, kind, status):
    state, _ = feed({}, sample(), sample(), sample(7), sample(7))
    bad = sample()
    bad["values"][2].update(value=value, dataType=kind, status=status)
    state, events = feed(state, bad, bad)
    assert events == []
    assert state["process_conditions"]["Press.ReturnCode"]["stable"] is True
    assert state["process_conditions"]["Press.ReturnCode"]["communication"] == "UNKNOWN"
    assert state["process_conditions"]["Press.ReturnCode"]["episode_id"] not in state["active_episode_ids"]


def test_gaps_and_binding_changes_do_not_report_a_fresh_intervention():
    state, _ = feed({}, sample(at=1), sample(at=2))
    state, events = feed(state, sample(7, at=90), sample(7, at=91))
    assert [e["kind"] for e in events] == ["PROCESS_INTERVENTION_AFTER_GAP"]
    replacement = sample(7, at=92)
    replacement["values"][2]["node"] = "replacement"
    state, events = feed(state, replacement, {**replacement, "observed_at": 93})
    assert [e["kind"] for e in events] == ["BASELINE_PROCESS_INTERVENTION"]


def test_missing_returncode_does_not_break_emergency_collective_fault_detection():
    state, _ = feed({}, sample(), sample())
    frame = sample(fault=True)
    frame["values"] = frame["values"][:2]
    state, events = feed(state, frame, frame)
    assert [e["kind"] for e in events] == ["FAULT_RAISED"]
    assert state["communication"] == "GOOD"


def test_both_stations_in_same_frame_have_one_claimable_task(tmp_path):
    monitor = Monitor(tmp_path / "monitor.db", lambda _: sample())
    target = {"asset_id": "urn:asset", "endpoint": "http://aas"}
    for frame in (sample(), sample(), sample(7, 7), sample(7, 7)):
        monitor.ingest(target, frame)
    status = monitor.status(target)
    assert len(status["events"]) == 1
    event = status["events"][0]
    assert len(event["conditions"]) == 2
    assert monitor.claim(target, event["id"])
    assert monitor.claim(target, event["id"]) is None
    for frame in (sample(), sample()):
        monitor.ingest(target, frame)
    assert not monitor.status(target)["state"]["process_attention"]


def test_stale_unknown_and_recovered_process_events_cannot_be_claimed(tmp_path):
    monitor = Monitor(tmp_path / "monitor.db", lambda _: sample())
    target = {"asset_id": "urn:asset", "endpoint": "http://aas"}
    for frame in (sample(), sample(), sample(7), sample(7)):
        monitor.ingest(target, frame)
    event = monitor.status(target)["events"][0]
    broken = sample()
    broken["values"] = broken["values"][:2]
    monitor.ingest(target, broken)
    assert monitor.claim(target, event["id"]) is None
    for frame in (sample(), sample()):
        monitor.ingest(target, frame)
    assert monitor.claim(target, event["id"]) is None


def test_simulation_ignores_physical_returncode_profile():
    frames = [{**sample(7), "source": "simulator"} for _ in range(3)]
    state, events = feed({}, *frames)
    assert not events and not state.get("process_attention")


def test_generic_prompts_do_not_prescribe_signal_or_fault_diagnosis():
    assert "BG8" not in IDENTITY and "pressure leakage maintenance" not in IDENTITY
    skill = (Path(__file__).resolve().parents[1] / "a4s/skills/fault-maintenance/SKILL.md").read_text(encoding="utf-8")
    assert "BG8" not in skill and "xSF01" not in skill and "Werkstueck" not in skill


def test_collective_and_return_code_share_notification_without_losing_process_episode(tmp_path):
    monitor = Monitor(tmp_path / "monitor.db", lambda _: sample())
    target = {"asset_id": "urn:asset", "endpoint": "http://aas"}
    for frame in (sample(), sample(), sample(7, fault=True), sample(7, fault=True)):
        monitor.ingest(target, frame)
    events = monitor.status(target)["events"]
    assert len(events) == 1 and events[0]["kind"] == "FAULT_RAISED"
    for frame in (sample(7), sample(7)):
        monitor.ingest(target, frame)
    assert monitor.claim(target, events[0]["id"])


def test_process_detection_is_independent_of_an_existing_collective_fault():
    state, _ = feed({}, sample(fault=True), sample(fault=True))
    state, events = feed(state, sample(7, fault=True), sample(7, fault=True))
    assert [event["kind"] for event in events] == ["PROCESS_INTERVENTION_RAISED"]
    assert len(state["active_episode_ids"]) == 2


def test_rearming_invalidates_returncode_continuity(tmp_path):
    import threading
    monitor = Monitor(tmp_path / "monitor.db", lambda _: sample(7))
    target = {"asset_id": "urn:asset", "endpoint": "http://aas"}
    monitor.ingest(target, sample()); monitor.ingest(target, sample())
    seen = threading.Event()
    def reader(_):
        seen.set()
        return sample(7)
    monitor.reader = reader
    monitor.interval = 0.01
    try:
        monitor.start(target)
        assert seen.wait(2)
        deadline = time.time() + 2
        while time.time() < deadline and not monitor.status(target)["events"]:
            time.sleep(0.02)
        events = monitor.status(target)["events"]
        assert [event["kind"] for event in events] == ["PROCESS_INTERVENTION_AFTER_GAP"]
    finally:
        monitor.close()
        monitor.workers[monitor.key(target)][1].join(2)
