import asyncio
import copy
import json
from pathlib import Path

from a4s.machines.festo_cp_lab import recorder
from a4s.machines.festo_cp_lab.model import operational_data
from a4s.server.write_routes import _copy_submodel


def test_bg8_bindings_survive_blueprint_instance_recreation():
    document = json.loads((Path(__file__).resolve().parents[1] / "BaSyxMinimal/aas/festo-cp-lab.json").read_text(encoding="utf-8"))
    model = next(sm for sm in document["submodels"] if sm["idShort"] == "OperationalData")
    original = copy.deepcopy(model)
    instance = _copy_submodel(model, "urn:new:device")
    expected = operational_data()
    for cell in ("Press", "Turning"):
        wanted = next(g for g in expected["submodelElements"] if g["idShort"] == cell)
        actual = next(g for g in instance["submodelElements"] if g["idShort"] == cell)
        for name in ("BG8", "BG8Auxiliary"):
            a = next(v for v in actual["value"] if v["idShort"] == name)
            b = next(v for v in wanted["value"] if v["idShort"] == name)
            assert a["qualifiers"] == b["qualifiers"]
            assert a["valueType"] == "xs:boolean"
            assert not a.get("value")
    assert model == original
    targets = recorder.targets()
    assert sum(len(t.signals) for t in targets) == 82
    press = next(t for t in targets if t.station == "PressPLC")
    turning = next(t for t in targets if t.station == "TurningPLC")
    assert 'ns=3;s="xHL_BG8"' in dict(press.signals).values()
    assert 'ns=3;s="xGM_BG8"' in dict(turning.signals).values()
    assert 'ns=3;s="xGM_BG8"' not in dict(press.signals).values()


def test_recorder_reconnects_after_a_dead_node_session(monkeypatch, tmp_path):
    import asyncua

    clock = [0]
    attempts = []

    class Client:
        def __init__(self, **kwargs):
            attempts.append(kwargs["url"])
            self.broken = len(attempts) == 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def get_node(self, node):
            return self

        async def read_value(self):
            if self.broken:
                raise ConnectionError("Session closed")
            return True

    async def sleep(seconds):
        clock[0] += 20 if seconds == 0.5 else seconds

    monkeypatch.setattr(asyncua, "Client", Client)
    monkeypatch.setattr(recorder.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(recorder.asyncio, "sleep", sleep)
    db = recorder.open_db(tmp_path / "capture.db")
    try:
        asyncio.run(recorder._watch(recorder.Target("TurningPLC", "opc.tcp://test", [("BG8", "node")]),
            db, interval=0.5, heartbeat=10, deadline=10))
        assert attempts == ["opc.tcp://test", "opc.tcp://test"]
        assert db.execute("SELECT value FROM readings WHERE kind='change'").fetchall() == [("True",)]
        assert db.execute("SELECT signal FROM readings WHERE kind='error'").fetchall() == [("_connection",)]
    finally:
        db.close()
