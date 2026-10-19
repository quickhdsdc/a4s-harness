"""Exercise real loopback OPC -> AAS bindings -> one neutral fault notification.

Requires provisioned AAS profile and port 4849 free. No real PLC or MES writes.
"""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


def main():
    from a4s.kernel.config import load_env
    from a4s.machines.festo_cp_lab.live_monitor import Monitor
    from a4s.server.live_monitor_routes import read_target, target, investigation_request
    load_env()
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 4849)) == 0:
            raise RuntimeError("Close the existing simulator first; it will not be stopped by this check")
    root = Path("work/temp/live-integration")
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="fault-workflow-", dir=root))
    process = subprocess.Popen([sys.executable, "-u", "-m", "a4s.machines.festo_cp_lab.opc_simulator"],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, text=True)
    selection = target("unused", None, "simulator")
    monitor = Monitor(folder / "events.db", read_target)
    def sample():
        value = read_target(selection)
        assert len(value["values"]) == 8 and not value["failed"]
        value["observed_at"] = time.time()
        return monitor.ingest(selection, value)
    try:
        for _ in range(30):
            if process.poll() is not None:
                raise RuntimeError("Simulator failed to start")
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", 4849)) == 0:
                    break
            time.sleep(0.2)
        sample()
        sample()
        assert monitor.status(selection)["state"]["stable"] is False
        process.stdin.write("fault\n")
        process.stdin.flush()
        time.sleep(0.5)
        sample()
        sample()
        sample()
        events = monitor.status(selection)["events"]
        assert len(events) == 1 and events[0]["kind"] == "FAULT_RAISED"
        request = investigation_request(events[0])
        (folder / "notification.txt").write_text(request, encoding="utf-8")
        print("PASS: AAS-resolved 8 OPC nodes, normal baseline, one fault, deduplication")
        print("Notification:", folder / "notification.txt")
        print("No MES business writes; no real PLC connection")
    finally:
        if process.poll() is None:
            process.stdin.write("quit\n")
            process.stdin.flush()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
