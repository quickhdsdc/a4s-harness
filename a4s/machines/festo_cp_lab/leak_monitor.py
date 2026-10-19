"""Press abnormal airflow evidence; no HMI or successful-cycle dependency."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import uuid

FLOWS = ("Press.Flow1", "Press.Flow2")
PRESSURES = ("Press.Pressure1", "Press.Pressure2")
PATHS = FLOWS + PRESSURES
NUMERIC = {"Byte", "SByte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64", "Float", "Double"}


@dataclass(frozen=True)
class LeakConfig:
    flow_high: float = 2000
    flow_clear: float = 1200
    seconds: float = 6
    extreme_flow: float = 10000
    extreme_seconds: float = 2
    pressure_drop: float = 300
    pressure_fraction: float = .10
    clear_seconds: float = 10
    min_samples: int = 3

    @classmethod
    def from_env(cls):
        names = {"flow_high": "FLOW_HIGH", "flow_clear": "FLOW_CLEAR", "seconds": "SECONDS",
                 "pressure_drop": "PRESSURE_DROP", "pressure_fraction": "PRESSURE_FRACTION",
                 "clear_seconds": "CLEAR_SECONDS", "min_samples": "MIN_SAMPLES",
                 "extreme_flow": "EXTREME_FLOW", "extreme_seconds": "EXTREME_SECONDS"}
        defaults = asdict(cls())
        values = {key: (int if key == "min_samples" else float)(
            os.getenv("A4S_PRESS_LEAK_" + suffix, str(defaults[key]))) for key, suffix in names.items()}
        if (not all(math.isfinite(v) and v > 0 for v in values.values())
                or values["flow_clear"] >= values["flow_high"] or values["pressure_fraction"] >= 1
                or values["extreme_flow"] <= values["flow_high"] or values["min_samples"] < 3):
            raise ValueError("Invalid Press leakage trend configuration")
        return cls(**values)


def active(state, now, max_gap=60):
    return bool(state.get("stable") and state.get("episode_id") and not state.get("gap")
                and state.get("communication") == "GOOD"
                and any(path not in state.get("unavailable_channels", []) for path in state.get("trigger_paths", []))
                and now - (state.get("last_good") or {}).get("observed_at", 0) <= max_gap)


def reduce_leak(state, sample, now, max_gap=60, config=None):
    if sample.get("source") == "simulator":
        return {}, []  # Simulator engineering values are a separate signal contract.
    state = dict(state or {})
    rows = sample.get("values", [])
    if not state and not any(row.get("path") in PATHS for row in rows):
        return {}, []
    config = config or LeakConfig.from_env()
    matches = {path: [row for row in rows if row.get("path") == path] for path in PATHS}
    valid = {path: group[0] for path, group in matches.items() if len(group) == 1 and group[0].get("status") == "Good"
               and group[0].get("dataType") in NUMERIC
               and type(group[0].get("value")) in (int, float)
               and math.isfinite(group[0]["value"]) and group[0]["value"] >= 0
               }
    if not any(path in valid for path in FLOWS):
        state.update(communication="UNKNOWN", gap=True, history=[], recovering_since=None)
        return state, []
    by_path = {path: (group[0] if len(group) == 1 else {}) for path, group in matches.items()}
    binding = hashlib.sha256(json.dumps([asdict(config), [
        [path, by_path[path].get("endpoint"), by_path[path].get("node"), by_path[path].get("dataType")]
        for path in FLOWS]], sort_keys=True).encode()).hexdigest()
    if binding != state.get("binding"):
        state = {"binding": binding, "stable": False, "history": []}
    previous = state.get("last_good")
    if previous and (now <= previous["observed_at"] or now - previous["observed_at"] > max_gap):
        state.update(gap=True, history=[], recovering_since=None)
        if now <= previous["observed_at"]:
            state["communication"] = "UNKNOWN"
            return state, []
    values = {path: valid[path]["value"] if path in valid else None for path in PATHS}
    history = [*state.get("history", []), {"at": now, "values": values}]
    # Retain the left boundary frame when polling does not divide the window.
    window = max(config.seconds, config.extreme_seconds, config.clear_seconds)
    while len(history) > 2 and history[1]["at"] <= now - window:
        history.pop(0)
    high = any(values[path] is not None and values[path] >= config.flow_high for path in FLOWS)
    if not high and not state.get("stable"):
        history = [history[-1]]
        state["before"] = sample
    state.update(communication="GOOD", config=asdict(config), history=history, last_good=sample,
                 unavailable_channels=[path for path in PATHS if path not in valid])
    duration = history[-1]["at"] - history[0]["at"]
    sufficient = len(history) >= config.min_samples and duration >= config.seconds
    confirmed = []
    for path in FLOWS:
        for threshold, seconds, count, band in (
                (config.extreme_flow, config.extreme_seconds, 2, "extreme"),
                (config.flow_high, config.seconds, config.min_samples, "sustained")):
            run = []
            for h in reversed(history):
                value = h["values"].get(path)
                if value is None or value < threshold:
                    break
                run.append(h)
            if len(run) >= count and now - run[-1]["at"] >= seconds:
                confirmed.append({"path": path, "operator": "ge", "value": threshold,
                                  "duration_seconds": now - run[-1]["at"], "band": band, "units": "raw"})
                break
    falling = []
    if sufficient:
        for path in PRESSURES:
            series = [h["values"][path] for h in history]
            if any(value is None for value in series):
                continue
            drop = series[0] - series[-1]
            # Multiple falling samples distinguish a trend from a one-off
            # pressure step during a normal pneumatic action. Allow raw noise.
            falls = sum(a - b > 30 for a, b in zip(series, series[1:]))
            if drop >= max(config.pressure_drop, series[0] * config.pressure_fraction) and falls >= max(2, math.ceil((len(series) - 1) * .6)):
                falling.append({"path": path, "operator": "decrease", "value": drop,
                                "from": series[0], "to": series[-1], "units": "raw"})
    events = []
    if not state.get("stable") and confirmed:
        state.update(stable=True, episode_id=uuid.uuid4().hex, gap=False,
                     trigger_paths=[c["path"] for c in confirmed])
        events.append({"id": uuid.uuid4().hex, "kind": "LEAK_SUSPECTED", "at": now,
                       "first_observed_at": now - max(c["duration_seconds"] for c in confirmed), "episode_id": state["episode_id"],
                       "rule_id": "press-abnormal-airflow", "config": asdict(config),
                       "conditions": confirmed, "supporting_pressure_declines": falling,
                       "unavailable_channels": state["unavailable_channels"],
                       "trend": history, "before": state.get("before") or previous, "after": sample,
                       "assessment": "Abnormal pneumatic consumption; possible leakage, venting or actuator/stopper condition. Pressure decline is supporting evidence, not required. Raw units; cause unverified."})
    if state.get("stable"):
        recovered = all(values[path] is not None and values[path] <= config.flow_clear for path in FLOWS)
        if recovered:
            if state.get("recovering_since") is None:
                state["recovering_since"] = now
            if now - state["recovering_since"] >= config.clear_seconds and sufficient:
                events.append({"id": uuid.uuid4().hex, "kind": "PNEUMATIC_RECOVERY_OBSERVED", "at": now,
                               "episode_id": state.get("episode_id"), "before": previous, "after": sample})
                state.update(stable=False, episode_id=None, recovering_since=None)
        else:
            state["recovering_since"] = None
        if sufficient:
            state["gap"] = False
    state["phase"] = "suspected" if state.get("stable") else "observing" if high else "watching"
    return state, events


def augment(result, events, sample, now, max_gap=60):
    """Adds an independent detector to either the local or deployed reducer."""
    leak, emitted = reduce_leak(result.get("press_leak"), sample, now, max_gap)
    if leak:
        result["press_leak"] = leak
    else:
        result.pop("press_leak", None)
    primary = next((e for e in events if e["kind"] in ("FAULT_RAISED", "PROCESS_INTERVENTION_RAISED")), None)
    suspected = next((e for e in emitted if e["kind"] == "LEAK_SUSPECTED"), None)
    if primary and suspected:
        primary["conditions"] = primary.get("conditions", []) + suspected["conditions"]
        primary["pneumatic_evidence"] = suspected
        leak["episode_id"] = primary["episode_id"]
        emitted.remove(suspected)
    # Recompute owners: legacy reducers without ReturnCode nodes carry old lists
    # forward, which would otherwise hide new PLC faults or retain cleared ones.
    other_owners = set()
    if result.get("communication") == "GOOD" and result.get("candidate") is True and result.get("count", 0) >= 2:
        other_owners.update(result.get("fault_episodes", {}).values())
        other_owners.add(result.get("episode_id"))
    other_owners.update(s.get("episode_id") for s in result.get("process_conditions", {}).values()
                        if s.get("stable") and s.get("communication") == "GOOD"
                        and s.get("count", 0) >= 2 and not s.get("gap")
                        and now - (s.get("last_good") or {}).get("observed_at", 0) <= max_gap)
    ids = sorted(identifier for identifier in other_owners if identifier)
    result["active_episode_ids"] = list(dict.fromkeys([*ids, *([leak["episode_id"]] if active(leak, now, max_gap) else [])]))
    result["process_attention"] = any(s.get("stable") for s in result.get("process_conditions", {}).values()) or active(leak, now, max_gap)
    return result, [*events, *emitted]
