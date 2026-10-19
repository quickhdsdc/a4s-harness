import time
import pytest
from a4s.machines.festo_cp_lab.leak_monitor import reduce_leak, LeakConfig, active
from a4s.machines.festo_cp_lab.live_monitor import Monitor, reduce_sample


def frame(at, flow=300, pressure=5500, plc=True):
    values = [{"path": path, "value": value, "status": "Good", "dataType": "Int16",
               "endpoint": "opc.tcp://revpi", "node": path}
              for path, value in [("Press.Flow1", flow), ("Press.Flow2", flow + 10),
                                  ("Press.Pressure1", pressure), ("Press.Pressure2", pressure + 30)]]
    if plc:
        values += [{"path": path, "value": False, "status": "Good", "dataType": "Boolean",
                    "endpoint": "opc.tcp://plc", "node": path}
                   for path in ("Press.Fault", "Turning.Fault")]
    return {"observed_at": at, "source": "live", "values": values}


def apply(frames, state=None):
    events = []
    for sample in frames:
        state, emitted = reduce_leak(state or {}, sample, sample["observed_at"])
        events += emitted
    return state, events


def leaking(start, plc=True):
    return [frame(start + i * 4, 3000, 5500 - 200 * i, plc) for i in range(5)]


def test_high_flow_and_persistent_pressure_fall_without_hmi_fault():
    start = time.time() - 20
    state, events = apply(leaking(start))
    assert len(events) == 1 and events[0]["kind"] == "LEAK_SUSPECTED"
    assert events[0]["at"] - events[0]["first_observed_at"] == 8
    assert state["stable"] and active(state, start + 16)
    assert len(events[0]["trend"]) == 3
    assert events[0]["conditions"][0]["band"] == "sustained"


@pytest.mark.parametrize("mode", ["short_cycle", "pressure_drop_only", "pressure_noise"])
def test_isolated_signals_and_normal_action_examples_do_not_trigger(mode):
    start = time.time()
    rows = []
    for i in range(10):
        flow = 3000
        pressure = 5500 - i * 100
        if mode == "short_cycle" and i >= 2: flow = 300
        if mode == "high_flow_flat_pressure": pressure = 5500
        if mode == "pressure_drop_only": flow = 300
        if mode == "one_step_then_flat": pressure = 5500 if i == 0 else 4000
        if mode == "pressure_noise": pressure = 5500 + (i % 2) * 20; flow = 300
        rows.append(frame(start + i * 4, flow, pressure))
    _, events = apply(rows)
    assert not events


def test_confirmation_is_duration_and_samples_not_just_poll_count():
    start = time.time()
    _, events = apply([frame(start + i, 3000, 5500 - i * 200) for i in range(5)])
    assert not events
    _, events = apply([frame(start + i * 16, 3000, 5500 - i * 500) for i in range(3)])
    assert not events


def test_recovery_rearms_and_persistent_leak_does_not_repeat():
    start = time.time()
    state, events = apply(leaking(start))
    episode = events[0]["episode_id"]
    state, repeated = apply([frame(start + i * 4, 3000, 4500) for i in range(5, 9)], state)
    assert not repeated
    state, recovered = apply([frame(start + i * 4, 300, 5500) for i in range(9, 14)], state)
    assert [e["kind"] for e in recovered] == ["PNEUMATIC_RECOVERY_OBSERVED"]
    assert not active(state, start + 52)
    state, second = apply(leaking(start + 56), state)
    assert len(second) == 1 and second[0]["episode_id"] != episode


@pytest.mark.parametrize("bad", ["Bad", "duplicate", "missing", "string", "nonfinite"])
def test_invalid_sensor_evidence_breaks_trend_continuity(bad):
    start = time.time()
    state, _ = apply(leaking(start)[:2])
    broken = frame(start + 12, 3000, 4900)
    if bad == "Bad": broken["values"][0]["status"] = "Bad"
    if bad == "duplicate": broken["values"].append(dict(broken["values"][0]))
    if bad == "missing": broken["values"].pop(0)
    if bad == "string": broken["values"][0]["value"] = "3000"
    if bad == "nonfinite": broken["values"][0]["value"] = float("nan")
    # Both flow channels must be invalid to withhold all flow evidence. Pressure
    # loss alone no longer blocks an otherwise validated high-flow observation.
    broken["values"] = [r for r in broken["values"] if r["path"].startswith("Press.Flow")]
    for row in broken["values"]: row["status"] = "Bad"
    state, events = apply([broken, frame(start + 16, 3000, 4700)], state)
    assert not events and not active(state, start + 16)


def test_gap_binding_change_and_simulator_do_not_reuse_old_pressure_window():
    start = time.time()
    state, _ = apply(leaking(start)[:2])
    state, events = apply([frame(start + 100, 3000, 4500)], state)
    assert not events and len(state["history"]) == 1
    changed = frame(start + 104, 3000, 4200)
    changed["values"][0]["node"] = "new_sensor"
    state, events = apply([changed], state)
    assert not events and len(state["history"]) == 1
    state, events = reduce_leak(state, {**changed, "source": "simulator"}, start + 104)
    assert state == {} and events == []


def test_claim_is_once_only_and_independent_of_plc_quality(tmp_path):
    start = time.time() - 20
    monitor = Monitor(tmp_path / "leak.db", lambda _: {})
    target = {"asset_id": "urn:press", "endpoint": "http://aas"}
    for row in leaking(start, plc=False): monitor.ingest(target, row)
    status = monitor.status(target)
    event = next(e for e in status["events"] if e["kind"] == "LEAK_SUSPECTED")
    assert status["state"]["communication"] == "UNKNOWN"
    assert status["state"]["process_attention"]
    assert monitor.claim({**target, "asset_id": "other"}, event["id"]) is None
    assert monitor.claim(target, event["id"])
    assert monitor.claim(target, event["id"]) is None


def test_bad_sensors_or_recovery_prevent_an_unclaimed_handoff(tmp_path):
    start = time.time() - 20
    monitor = Monitor(tmp_path / "leak.db", lambda _: {})
    target = {"asset_id": "urn:press", "endpoint": "http://aas"}
    for row in leaking(start): monitor.ingest(target, row)
    event = monitor.status(target)["events"][-1]
    bad = frame(time.time(), 3000, 4500)
    bad["values"][0]["status"] = "Bad"
    bad["values"][1]["status"] = "Bad"
    monitor.ingest(target, bad)
    assert monitor.claim(target, event["id"]) is None


def test_config_is_explicit_not_engineering_unit_conversion(monkeypatch):
    monkeypatch.setenv("A4S_PRESS_LEAK_FLOW_HIGH", "2500")
    assert LeakConfig.from_env().flow_high == 2500
    monkeypatch.setenv("A4S_PRESS_LEAK_SECONDS", "nan")
    with pytest.raises(ValueError): LeakConfig.from_env()


def test_sustained_flow_triggers_without_pressure_drop_or_successful_cycle():
    start = time.time()
    samples = [frame(start + i * 3, 3000, 5000, plc=False) for i in range(4)]
    for sample in samples:
        sample["values"] = [r for r in sample["values"] if r["path"] == "Press.Flow2"]
    state, events = apply(samples)
    assert [e["kind"] for e in events] == ["LEAK_SUSPECTED"]
    assert events[0]["supporting_pressure_declines"] == []
    assert "Press.Pressure1" in events[0]["unavailable_channels"]
    assert active(state, start + 9)


def test_extreme_flow_has_a_faster_but_not_single_sample_confirmation():
    start = time.time()
    state, events = apply([frame(start, 11000)])
    assert not events
    state, events = apply([frame(start + 3, 11000)], state)
    assert len(events) == 1 and events[0]["conditions"][0]["band"] == "extreme"
    assert events[0]["conditions"][0]["duration_seconds"] == 3
    state, events = apply([frame(start, 8221), frame(start + 1.2, 300), frame(start + 3, 300)])
    assert not events


def test_pressure_drop_is_sent_as_support_not_a_required_condition():
    start = time.time()
    _, events = apply([frame(start + i * 3, 3000, 5500 - 500 * i) for i in range(3)])
    assert events[0]["supporting_pressure_declines"]
    from a4s.server.live_monitor_routes import investigation_request
    event = {**events[0], "target": {"asset_id": "urn:press", "endpoint": "http://aas"}}
    request = investigation_request(event)
    assert '"pneumatic"' in request and '"trend"' in request
    assert '"supporting_pressure_declines"' in request
