"""Deterministic process-intervention conditions, without diagnosis or prompts.

Code 7 is a field-observed condition. Its manufacturer meaning is not asserted.
Each station has its own continuity, binding, debounce and episode state.
"""
import hashlib
import json
import uuid

PATHS = ("Press.ReturnCode", "Turning.ReturnCode")
INTEGER_TYPES = {"Int16", "Int32", "UInt16", "UInt32"}


def reduce_returncodes(states, sample, now, max_gap=60):
    states = {path: dict(state) for path, state in states.items()}
    events = []
    rows = sample.get("values", [])
    if sample.get("source") == "simulator":
        return {}, []
    for path in PATHS:
        matches = [row for row in rows if row.get("path") == path]
        if not matches and path not in states:
            continue  # Older assets/simulation profiles need not expose this node.
        state = states.setdefault(path, {})
        previous = state.get("last_good")
        good = (len(matches) == 1 and matches[0].get("status") == "Good"
                and matches[0].get("dataType") in INTEGER_TYPES
                and type(matches[0].get("value")) is int)
        if not good:
            state.update(communication="UNKNOWN", gap=True, candidate=None, count=0)
            continue
        row = matches[0]
        binding = hashlib.sha256(json.dumps([row.get("endpoint"), row.get("node")]).encode()).hexdigest()
        if state.get("binding") and state["binding"] != binding:
            state.update(stable=None, episode_id=None, gap=True, candidate=None, count=0)
        if previous and now - previous["observed_at"] > max_gap:
            state.update(gap=True, candidate=None, count=0)
        active = row["value"] == 7
        if state.get("candidate") != active:
            state.update(candidate=active, count=1, before=previous, first_observed_at=now)
        else:
            state["count"] = state.get("count", 0) + 1
        if state["count"] >= 2 and state.get("stable") != active:
            old = state.get("stable")
            kind = None
            if active:
                state["episode_id"] = uuid.uuid4().hex
                kind = ("BASELINE_PROCESS_INTERVENTION" if old is None else
                        "PROCESS_INTERVENTION_AFTER_GAP" if state.get("gap") else
                        "PROCESS_INTERVENTION_RAISED")
            elif old is True:
                kind = "PROCESS_INTERVENTION_CLEARED"
            if kind:
                events.append({"id": uuid.uuid4().hex, "kind": kind, "at": now,
                               "first_observed_at": state["first_observed_at"],
                               "episode_id": state.get("episode_id"),
                               "rule_id": "module-return-code-7", "conditions": [
                                   {"path": path, "operator": "eq", "value": 7}],
                               "before": state.get("before"), "after": sample})
            state.update(stable=active, gap=False)
            if not active:
                state["episode_id"] = None
        elif state["count"] >= 2:
            state["gap"] = False
        state.update(binding=binding, communication="GOOD", last_good=sample)

    # Both stations entering the same condition in one frame produce one task.
    for kind in ("BASELINE_PROCESS_INTERVENTION", "PROCESS_INTERVENTION_RAISED", "PROCESS_INTERVENTION_AFTER_GAP"):
        group = [event for event in events if event["kind"] == kind]
        if len(group) > 1:
            first = group[0]
            first["conditions"] = [condition for event in group for condition in event["conditions"]]
            first["first_observed_at"] = min(event["first_observed_at"] for event in group)
            for condition in first["conditions"]:
                states[condition["path"]]["episode_id"] = first["episode_id"]
            events = [event for event in events if event not in group[1:]]
    return states, events
