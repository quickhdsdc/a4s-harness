"""Persistent read-only fault episodes. No MES state, PLC writes or LLM calls."""

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .process_monitor import reduce_returncodes
from .leak_monitor import augment as augment_leak, active as leak_active

CRITICAL = ("Press.Fault", "Turning.Fault")
MAX_GAP = 60


def _reduce_fault_sample(state, sample, now):
    """Two consecutive complete Good Boolean frames confirm a transition.

    A gap invalidates continuity, not the last confirmed equipment state.
    All timestamps are host observations; a polling interval can miss short faults.
    """
    s = dict(state)
    events = []
    previous = s.get("last_good")
    rows = {v["path"]: v for v in sample.get("values", [])}
    good = all(
        sum(v.get("path") == p for v in sample.get("values", [])) == 1
        and p in rows
        and rows[p].get("status") == "Good"
        and rows[p].get("dataType") == "Boolean"
        and type(rows[p].get("value")) is bool
        for p in CRITICAL
    )
    binding = hashlib.sha256(
        json.dumps(
            [(p, rows.get(p, {}).get("endpoint"), rows.get(p, {}).get("node")) for p in CRITICAL],
            sort_keys=True,
        ).encode()
    ).hexdigest()

    def event(kind, before, after, paths=()):
        events.append(
            {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "at": now,
                "episode_id": s.get("episode_id"),
                "before": before,
                "after": after,
                "conditions": [{"path": path, "operator": "eq", "value": True} for path in paths],
            }
        )

    if not good:
        if s.get("communication") != "UNKNOWN":
            event("COMMUNICATION_LOST", previous, sample)
        s.update(communication="UNKNOWN", gap=True, candidate=None, count=0, latest=sample)
        return s, events
    if s.get("communication") == "UNKNOWN":
        event("COMMUNICATION_RESTORED", previous, sample)
    if s.get("binding") and s["binding"] != binding:
        event("BINDING_CHANGED", previous, sample)
        s.update(stable=None, episode_id=None, candidate=None, count=0, gap=True,
                 stable_fault_paths=[], fault_episodes={})
    if previous and now - previous["observed_at"] > MAX_GAP:
        s.update(gap=True, candidate=None, count=0)
    fault_paths = [path for path in CRITICAL if rows[path]["value"]]
    fault = bool(fault_paths)
    # Preserve an existing persisted episode across upgrade. The old reducer
    # recorded the full last Good frame even though it reduced it to one bit.
    if "stable_fault_paths" not in s:
        old_frame = previous or {}
        if s.get("stable") is True and not any(
                row.get("path") in CRITICAL and row.get("value") is True
                for row in old_frame.get("values", [])):
            old_frame = s.get("candidate_before") or old_frame
        old_rows = {row["path"]: row for row in old_frame.get("values", [])}
        s["stable_fault_paths"] = ([path for path in CRITICAL if old_rows.get(path, {}).get("value") is True]
                                   if s.get("stable") is True else [])
        s["fault_episodes"] = {path: s["episode_id"] for path in s["stable_fault_paths"] if s.get("episode_id")}
    if s.get("candidate") != fault or s.get("candidate_fault_paths") != fault_paths:
        s.update(candidate=fault, count=1, candidate_before=previous, candidate_first=sample)
        s["candidate_fault_paths"] = fault_paths
    else:
        s["count"] = s.get("count", 0) + 1
    if s["count"] >= 2:
        stable = s.get("stable")
        previous_paths = s.get("stable_fault_paths", [])
        added_paths = [path for path in fault_paths if path not in previous_paths]
        episodes = {path: episode for path, episode in s.get("fault_episodes", {}).items() if path in fault_paths}
        if stable is None:
            if fault:
                s["episode_id"] = uuid.uuid4().hex
                episodes = {path: s["episode_id"] for path in fault_paths}
                event("BASELINE_FAULT", s.get("candidate_before"), sample, fault_paths)
        elif stable != fault or added_paths:
            if added_paths:
                s["episode_id"] = uuid.uuid4().hex
                episodes.update({path: s["episode_id"] for path in added_paths})
                event(
                    "FAULT_OBSERVED_AFTER_GAP" if s.get("gap") else "FAULT_RAISED",
                    s.get("candidate_before"),
                    sample,
                    added_paths,
                )
            else:
                event("RECOVERY_OBSERVED", s.get("candidate_before"), sample)
                s["episode_id"] = None
        if fault and s.get("episode_id") not in episodes.values():
            s["episode_id"] = next(iter(episodes.values()), None)
        s.update(stable_fault_paths=fault_paths, fault_episodes=episodes)
        s.update(stable=fault, gap=False)
    s.update(communication="GOOD", binding=binding, last_good=sample, latest=sample)
    return s, events


def reduce_sample(state, sample, now):
    """Keep collective alarms and process conditions independent of diagnosis."""
    result, events = _reduce_fault_sample(state, sample, now)
    conditions, process_events = reduce_returncodes(state.get("process_conditions", {}), sample, now, MAX_GAP)
    if conditions:
        result["process_conditions"] = conditions
        result["process_attention"] = any(condition.get("stable") is True for condition in conditions.values())
        # One notification when a collective alarm and code condition coincide.
        fault_event = next((event for event in events if event["kind"] == "FAULT_RAISED"), None)
        process_event = next((event for event in process_events if event["kind"] == "PROCESS_INTERVENTION_RAISED"), None)
        if fault_event and process_event:
            fault_event["conditions"] = fault_event.get("conditions", []) + process_event["conditions"]
            for condition in process_event["conditions"]:
                conditions[condition["path"]]["episode_id"] = fault_event["episode_id"]
            process_events.remove(process_event)
    # Every active station keeps its own episode. Clearing one station, or
    # faulting the second, must not replace the first station's notification.
    fault_episodes = (list(result.get("fault_episodes", {}).values())
                      if result.get("communication") == "GOOD" and not result.get("gap")
                      and result.get("candidate") is True and result.get("count", 0) >= 2 else [])
    result["active_episode_ids"] = list(dict.fromkeys(
            episode for episode in [*fault_episodes, *[
                condition.get("episode_id") for condition in conditions.values()
                if condition.get("stable") is True and condition.get("communication") == "GOOD"
                and condition.get("count", 0) >= 2 and not condition.get("gap")
                and now - (condition.get("last_good") or {}).get("observed_at", 0) <= MAX_GAP]] if episode))
    return augment_leak(result, [*events, *process_events], sample, now, MAX_GAP)


class Monitor:
    """Single-process demo service. SQLite holds evidence and one-shot handoffs.

    Monitoring is explicitly re-armed after restart; demo history is disposable.
    No automatic retry of an uncertain Agent handoff. Not a multi-worker service.
    """

    def __init__(self, path, reader, interval=3):
        self.path = Path(path)
        self.reader = reader
        self.interval = interval
        self.lock = threading.RLock()
        self.workers = {}

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS states (scope TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "scope TEXT NOT NULL, id TEXT UNIQUE, body TEXT NOT NULL, claimed INTEGER DEFAULT 0)"
        )
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def key(target):
        return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()

    def _load(self, db, key):
        row = db.execute("SELECT body FROM states WHERE scope=?", (key,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _save(self, db, key, state):
        db.execute("INSERT OR REPLACE INTO states VALUES (?,?)", (key, json.dumps(state)))

    def ingest(self, target, sample):
        key = self.key(target)
        with self.lock, self.db() as db:
            state, events = reduce_sample(self._load(db, key), sample, sample["observed_at"])
            self._save(db, key, state)
            for event in events:
                event["target"] = target
                event.setdefault("first_observed_at", (
                    (state.get("candidate_first") or sample)["observed_at"]
                    if event["kind"]
                    in (
                        "BASELINE_FAULT",
                        "FAULT_RAISED",
                        "FAULT_OBSERVED_AFTER_GAP",
                        "RECOVERY_OBSERVED",
                    )
                    else sample["observed_at"]
                ))
                db.execute(
                    "INSERT INTO events(scope,id,body) VALUES (?,?,?)",
                    (key, event["id"], json.dumps(event)),
                )
        return events

    def status(self, target):
        key = self.key(target)
        with self.lock, self.db() as db:
            state = self._load(db, key)
            events = [
                {**json.loads(row["body"]), "seq": row["seq"], "claimed": bool(row["claimed"])}
                for row in db.execute(
                    "SELECT * FROM events WHERE scope=? ORDER BY seq DESC LIMIT 100", (key,)
                )
            ]
            worker = self.workers.get(key)
            running = bool(worker and worker[1].is_alive() and not worker[0].is_set())
        at = (state.get("latest") or {}).get("observed_at", 0)
        return {
            "target": target,
            "running": running,
            "state": state,
            "events": list(reversed(events)),
            "stale": not running or time.time() - at > MAX_GAP,
            "note": "Host timestamps; two Good typed samples confirm each condition. No PLC writes.",
        }

    def start(self, target):
        key = self.key(target)
        with self.lock:
            old = self.workers.get(key)
            if old and old[1].is_alive():
                if old[0].is_set():
                    raise ValueError("Previous read is still stopping; wait before re-arming")
                return self.status(target)
            if sum(thread.is_alive() for _, thread in self.workers.values()) >= 8:
                raise ValueError("Eight active monitors maximum")
            with self.db() as db:
                state = self._load(db, key)
                state.update(gap=True, candidate=None, count=0)
                for condition in state.get("process_conditions", {}).values():
                    condition.update(gap=True, candidate=None, count=0)
                self._save(db, key, state)
            stop = threading.Event()
            thread = threading.Thread(target=self._loop, args=(target, stop), daemon=True)
            self.workers[key] = (stop, thread)
            thread.start()
        return self.status(target)

    def stop(self, target):
        with self.lock:
            worker = self.workers.get(self.key(target))
            if worker:
                worker[0].set()
        return self.status(target)

    def close(self):
        with self.lock:
            for stop, _ in self.workers.values():
                stop.set()

    def reset(self):
        """Discard demo evidence, including any read already in flight.

        Keep stopping workers registered until they exit, so re-arming cannot
        overlap their last read. The loop checks the stop flag under this lock
        before ingesting; a late result cannot recreate deleted history.
        """
        with self.lock:
            self.close()
            with self.db() as db:
                db.execute("DELETE FROM events")
                db.execute("DELETE FROM states")

    def _loop(self, target, stop):
        while not stop.is_set():
            try:
                sample = self.reader(target)
            except Exception as exc:
                sample = {"values": [], "error": type(exc).__name__}
            sample["observed_at"] = time.time()
            with self.lock:
                if stop.is_set():
                    return
                self.ingest(target, sample)
            stop.wait(self.interval)

    def claim(self, target, event_id):
        """At-most-once dispatch reservation, NOT a completed Agent task."""
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM events WHERE scope=? AND id=?", (self.key(target), event_id)
            ).fetchone()
            if not row or row["claimed"]:
                return None
            event = json.loads(row["body"])
            state = self._load(db, self.key(target))
            if (
                event["kind"] not in ("FAULT_RAISED", "PROCESS_INTERVENTION_RAISED", "LEAK_SUSPECTED")
                or event["episode_id"] not in state.get("active_episode_ids", [state.get("episode_id")])
                or time.time() - event["at"] > 300
                or time.time() - (state.get("latest") or {}).get("observed_at", 0) > MAX_GAP
            ):
                return None
            fault_active = (event["kind"] == "FAULT_RAISED"
                            and state.get("communication") == "GOOD"
                            and event["episode_id"] in state.get("fault_episodes", {}).values()
                            and state.get("candidate") is True and not state.get("gap")
                            and state.get("count", 0) >= 2)
            process_active = state.get("communication") == "GOOD" and any(
                condition.get("episode_id") == event["episode_id"] and condition.get("stable") is True
                and condition.get("count", 0) >= 2 and condition.get("communication") == "GOOD"
                and not condition.get("gap")
                and time.time() - (condition.get("last_good") or {}).get("observed_at", 0) <= MAX_GAP
                for condition in state.get("process_conditions", {}).values())
            pneumatic_active = (leak_active(state.get("press_leak", {}), time.time(), MAX_GAP)
                                and state["press_leak"]["episode_id"] == event["episode_id"])
            if not fault_active and not process_active and not pneumatic_active:
                return None
            db.execute("UPDATE events SET claimed=1 WHERE id=?", (event_id,))
            return event
