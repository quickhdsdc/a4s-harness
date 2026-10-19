"""Disposable demo presentation, separate from MES state and durable audit logs."""
import threading
import time
import uuid

LOCK = threading.RLock()
_session = {"id": uuid.uuid4().hex, "started_at": time.time()}


def status():
    with LOCK:
        return dict(_session)


def reset(reset_simulator=True):
    """Begin a clean demo. Never delete audit evidence or release physical guards."""
    from . import festo_demo_routes, live_monitor_routes, production_routes
    from ..machines.festo_cp_lab import demo_monitor
    from ..machines.festo_cp_lab.opc_simulator import controller

    with LOCK:
        live_monitor_routes.service.reset()
        if reset_simulator:
            controller.reset()
        demo_monitor.reset()
        with festo_demo_routes.LOCK:
            festo_demo_routes.PLANS.clear()
        with production_routes.RESET_PREVIEW_LOCK:
            production_routes.RESET_PREVIEWS.clear()
        _session.update(id=uuid.uuid4().hex, started_at=time.time())
        return dict(_session)
