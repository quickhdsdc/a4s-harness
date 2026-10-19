"""Read-only local integration check. No PLC writes or MES business mutations.

Run with the project Python from the repository root. Evidence is kept in work/temp/.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    import httpx

    from a4s.kernel.config import load_env
    from a4s.machines.festo_cp_lab.live_monitor import Monitor
    from a4s.mesctl.client import Config, MesClient
    from a4s.mesctl.commands import build_parser
    from a4s.mesctl.executor import execute
    from a4s.server.live_monitor_routes import read_target
    from a4s.server.festo_assets import identity

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", help="Also arm/check/stop a real backend reader; never starts equipment")
    args = parser.parse_args()
    load_env(str(ROOT / ".env"))
    target = identity(None, "https://example.com/ids/aas/FestoWorkCenterStamping_381")
    parent = ROOT / "work/temp" / "live-integration"
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="read-only-", dir=parent))
    monitor = Monitor(directory / "evidence.db", read_target)
    print("Evidence:", directory, flush=True)
    for index in range(4):
        sample = read_target(target)
        sample["observed_at"] = time.time()
        events = monitor.ingest(target, sample)
        critical = [{k: v.get(k) for k in ("path", "value", "status", "source_timestamp")}
                    for v in sample["values"] if v["path"] in
                    ("Press.Fault", "Turning.Fault", "Press.Fault01", "Press.Ready", "Turning.Ready")]
        print(json.dumps({"sample": index + 1, "signals": len(sample["values"]),
                          "failed": sample["failed"], "critical": critical,
                          "events": [e["kind"] for e in events]}), flush=True)
        if index < 3:
            time.sleep(3)
    state = Monitor(directory / "evidence.db", read_target).status(target)
    assert state["state"]["communication"] == "GOOD", "Critical OPC evidence unavailable"
    print("Persisted events:", [e["kind"] for e in state["events"]], flush=True)
    with MesClient(Config.from_env()) as mes:
        def run(words):
            return execute(build_parser().parse_args(words), mes)
        for words in (["health"], ["auth", "whoami"], ["maintenance", "ls", "--per-page", "1"]):
            result = run(words)
            print("MES", " ".join(words), result["execution"]["outcome"], flush=True)
        lines = mes.rows("/api/v1/lines")
        assert lines, "No real MES line available for dry-run target"
        start = datetime.now(timezone.utc) + timedelta(minutes=10)
        result = run(["maintenance", "create", "--title", "Read-only integration preview",
                      "--event-type", "inspection", "--line", str(lines[0]["id"]),
                      "--scheduled-at", start.isoformat(), "--scheduled-end-at", (start+timedelta(minutes=30)).isoformat(), "--dry-run"])
        assert result["dry_run"]
        print("MES maintenance create:", result["execution"]["outcome"], "(not committed)")

    if args.backend:
        path = "/api/festo/live-monitor"
        with httpx.Client(base_url=args.backend, timeout=20, trust_env=False) as api:
            response = api.get(path, params=target)
            response.raise_for_status()
            already_running = response.json()["running"]
            try:
                if not already_running:
                    response = api.post(path + "/start", json=target)
                    response.raise_for_status()
                for _ in range(30):
                    response = api.get(path, params=target)
                    response.raise_for_status()
                    report = response.json()
                    if report["running"] and not report["stale"] and report["state"].get("count", 0) >= 3:
                        break
                    time.sleep(2)
                assert report["state"]["communication"] == "GOOD" and report["state"]["count"] >= 3
                print("HTTP monitor:", json.dumps({"running": report["running"],
                      "communication": report["state"]["communication"],
                      "fault": report["state"]["stable"],
                      "events": [e["kind"] for e in report["events"]]}), flush=True)
            finally:
                if not already_running:
                    response = api.post(path + "/stop", json=target)
                    response.raise_for_status()
                    assert not response.json()["running"]
                    print("Test-owned HTTP reader stopped; equipment unchanged.")


if __name__ == "__main__":
    main()
