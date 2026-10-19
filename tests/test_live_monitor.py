import time
import threading
import pytest

from a4s.machines.festo_cp_lab.live_monitor import Monitor, reduce_sample


def sample(fault=False, at=None, status="Good", missing=False):
    return {
        "observed_at": at or time.time(),
        "values": []
        if missing
        else [
            {
                "path": p,
                "value": fault if p.startswith("Press") else False,
                "dataType": "Boolean",
                "status": status,
                "endpoint": "opc.tcp://test",
                "node": p,
                "source_timestamp": "2026-09-23T10:00:00Z",
            }
            for p in ("Press.Fault", "Turning.Fault")
        ],
    }


def feed(state, *frames):
    events = []
    for frame in frames:
        state, new = reduce_sample(state, frame, frame["observed_at"])
        events.extend(new)
    return state, events


def test_baseline_existing_fault_is_not_new_and_repeats_are_merged():
    state, events = feed({}, *[sample(True) for _ in range(10)])
    assert [e["kind"] for e in events] == ["BASELINE_FAULT"]
    assert state["stable"] is True


def test_bg8_cycles_do_not_trigger_but_are_preserved_in_fault_evidence():
    def frame(bg8, fault=False):
        result = sample(fault)
        result["values"].append({"path": "Turning.BG8", "value": bg8,
                                "dataType": "Boolean", "status": "Good",
                                "endpoint": "opc.tcp://turning",
                                "node": 'ns=3;s="xG1_KG2_BG8"'})
        return result

    state, events = feed({}, frame(True), frame(True), frame(False), frame(False), frame(True))
    assert events == []
    state, events = feed(state, frame(False, True), frame(False, True))
    assert [event["kind"] for event in events] == ["FAULT_RAISED"]
    event = events[0]
    assert event["before"]["values"][-1]["value"] is True
    assert event["after"]["values"][-1]["value"] is False


def test_transition_evidence_debounce_recovery_and_new_episode():
    s, _ = feed({}, sample(), sample())
    s, events = feed(s, sample(True), sample())
    assert not events and s["stable"] is False
    s, events = feed(s, sample(True), sample(True), sample(True))
    event = events[0]
    assert event["kind"] == "FAULT_RAISED"
    assert event["before"]["values"][0]["value"] is False
    assert event["after"]["values"][0]["value"] is True
    s, recovery = feed(s, sample(), sample())
    assert recovery[0]["kind"] == "RECOVERY_OBSERVED"
    s, events = feed(s, sample(True), sample(True))
    assert events[0]["episode_id"] != event["episode_id"]


def test_unknown_never_clears_fault_and_never_creates_new_fault():
    s, _ = feed({}, sample(), sample())
    s, events = feed(s, sample(missing=True), sample(missing=True), sample(True), sample(True))
    assert [e["kind"] for e in events] == [
        "COMMUNICATION_LOST",
        "COMMUNICATION_RESTORED",
        "FAULT_OBSERVED_AFTER_GAP",
    ]
    s, events = feed(s, sample(status="Uncertain"), sample(missing=True))
    assert s["stable"] is True and s["communication"] == "UNKNOWN"
    assert [e["kind"] for e in events] == ["COMMUNICATION_LOST"]
    s, events = feed(s, sample(True), sample(True))
    assert [e["kind"] for e in events] == ["COMMUNICATION_RESTORED"]


def test_long_gap_and_changed_binding_require_rebaseline():
    s, _ = feed({}, sample(at=100), sample(at=101))
    s, events = feed(s, sample(True, at=200), sample(True, at=201))
    assert events[0]["kind"] == "FAULT_OBSERVED_AFTER_GAP"
    a = sample(True, at=202)
    a["values"][0]["node"] = "replacement"
    s, events = feed(s, a, {**a, "observed_at": 203})
    assert [e["kind"] for e in events] == ["BINDING_CHANGED", "BASELINE_FAULT"]


def test_persistence_scope_and_atomic_handoff(tmp_path):
    path = tmp_path / "events.db"
    target = {"endpoint": "http://aas", "asset_id": "urn:one"}
    monitor = Monitor(path, lambda _: sample())
    for frame in (sample(), sample(), sample(True), sample(True)):
        monitor.ingest(target, frame)
    event = monitor.status(target)["events"][0]
    restored = Monitor(path, lambda _: sample())
    assert restored.status(target)["events"][0]["id"] == event["id"]
    assert not restored.status(target)["running"]
    assert not restored.status({**target, "endpoint": "http://other"})["events"]
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(restored.claim(target, event["id"])))
        for _ in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(e is not None for e in results) == 1


def test_worker_duplicate_start_and_stop(tmp_path):
    ready = threading.Event()

    def read(_):
        ready.set()
        return sample()

    monitor = Monitor(tmp_path / "worker.db", read, interval=0.01)
    target = {"endpoint": "http://aas", "asset_id": "urn:one"}
    try:
        monitor.start(target)
        assert ready.wait(2)
        worker = monitor.workers[monitor.key(target)][1]
        monitor.start(target)
        assert monitor.workers[monitor.key(target)][1] is worker
        monitor.stop(target)
        worker.join(2)
        assert not monitor.status(target)["running"]
    finally:
        monitor.close()


@pytest.mark.parametrize(
    "value,data_type,status",
    [
        ("true", "Boolean", "Good"),
        (1, "Int16", "Good"),
        (True, "Boolean", "Bad"),
        (False, "Boolean", "Uncertain"),
    ],
)
def test_invalid_critical_evidence_is_unknown(value, data_type, status):
    s, _ = feed({}, sample(), sample())
    bad = sample()
    bad["values"][0].update(value=value, dataType=data_type, status=status)
    s, events = feed(s, bad, bad)
    assert s["stable"] is False and s["communication"] == "UNKNOWN"
    assert [e["kind"] for e in events] == ["COMMUNICATION_LOST"]


def test_rearm_does_not_replay_existing_episode(tmp_path):
    monitor = Monitor(tmp_path / "events.db", lambda _: sample(True))
    target = {"asset_id": "urn:one", "endpoint": "http://aas"}
    for frame in (sample(), sample(), sample(True), sample(True)):
        monitor.ingest(target, frame)
    event = monitor.status(target)["events"][0]
    assert monitor.claim({**target, "asset_id": "urn:other"}, event["id"]) is None
    assert monitor.claim(target, event["id"])
    monitor = Monitor(tmp_path / "events.db", lambda _: sample(True))
    for frame in (sample(True), sample(True)):
        monitor.ingest(target, frame)
    assert len(monitor.status(target)["events"]) == 1
    assert monitor.claim(target, event["id"]) is None


def station_sample(press=False, turning=False):
    frame = sample(press)
    frame["values"][1]["value"] = turning
    return frame


@pytest.mark.parametrize("first,second", [("Press", "Turning"), ("Turning", "Press")])
def test_second_station_fault_is_new_and_both_episodes_remain_claimable(tmp_path, first, second):
    monitor = Monitor(tmp_path / "stations.db", lambda _: sample())
    target = {"asset_id": "urn:stations", "endpoint": "http://aas"}
    one = station_sample(press=first == "Press", turning=first == "Turning")
    for frame in (sample(), sample(), one, one):
        monitor.ingest(target, frame)
    first_event = monitor.status(target)["events"][-1]
    assert first_event["conditions"] == [{"path": first + ".Fault", "operator": "eq", "value": True}]
    both = station_sample(True, True)
    monitor.ingest(target, both)
    assert len(monitor.status(target)["events"]) == 1
    monitor.ingest(target, both)
    second_event = monitor.status(target)["events"][-1]
    assert second_event["kind"] == "FAULT_RAISED"
    assert second_event["conditions"] == [{"path": second + ".Fault", "operator": "eq", "value": True}]
    assert first_event["episode_id"] != second_event["episode_id"]
    assert monitor.claim(target, first_event["id"])
    assert monitor.claim(target, second_event["id"])
    monitor.ingest(target, both)
    assert len(monitor.status(target)["events"]) == 2


def test_clearing_one_station_expires_only_its_episode(tmp_path):
    monitor = Monitor(tmp_path / "partial.db", lambda _: sample())
    target = {"asset_id": "urn:stations", "endpoint": "http://aas"}
    for frame in (sample(), sample(), station_sample(True), station_sample(True),
                  station_sample(True, True), station_sample(True, True),
                  station_sample(False, True), station_sample(False, True)):
        monitor.ingest(target, frame)
    first, second = monitor.status(target)["events"]
    assert monitor.claim(target, first["id"]) is None
    assert monitor.claim(target, second["id"])
    assert monitor.status(target)["state"]["stable"] is True


def test_simultaneous_station_faults_produce_one_event_with_both_paths():
    state, _ = feed({}, sample(), sample())
    state, events = feed(state, station_sample(True, True), station_sample(True, True))
    assert len(events) == 1 and events[0]["kind"] == "FAULT_RAISED"
    assert {c["path"] for c in events[0]["conditions"]} == {"Press.Fault", "Turning.Fault"}


def test_second_station_glitch_and_gap_do_not_create_fresh_faults():
    state, _ = feed({}, sample(), sample(), station_sample(True), station_sample(True))
    state, events = feed(state, station_sample(True, True), station_sample(True), station_sample(True))
    assert events == []
    state, events = feed(state, sample(missing=True), station_sample(True, True), station_sample(True, True))
    assert [e["kind"] for e in events] == ["COMMUNICATION_LOST", "COMMUNICATION_RESTORED", "FAULT_OBSERVED_AFTER_GAP"]


def test_old_persisted_aggregate_state_migrates_without_replaying_first_fault():
    state, _ = feed({}, sample(), sample(), station_sample(True), station_sample(True))
    original_episode = state["episode_id"]
    for key in ("stable_fault_paths", "fault_episodes", "candidate_fault_paths"):
        state.pop(key)
    state, events = feed(state, station_sample(True), station_sample(True))
    assert events == []
    assert state["fault_episodes"] == {"Press.Fault": original_episode}
    state, events = feed(state, station_sample(True, True), station_sample(True, True))
    assert len(events) == 1 and events[0]["kind"] == "FAULT_RAISED"


def test_upgrade_during_first_unconfirmed_fault_sample_does_not_lose_transition():
    state, _ = feed({}, sample(), sample(), station_sample(True))
    for key in ("stable_fault_paths", "fault_episodes", "candidate_fault_paths"):
        state.pop(key)
    state, events = feed(state, station_sample(True), station_sample(True))
    assert [event["kind"] for event in events] == ["FAULT_RAISED"]
    assert state["episode_id"] in state["active_episode_ids"]
