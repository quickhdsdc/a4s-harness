"""Regression checks for repeated identities in actual seed configuration."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "validate_basyx_seeds", Path(__file__).resolve().parents[1] / "scripts/validate-basyx-seeds.py"
)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


@pytest.mark.parametrize(
    "resources, second_id, expected",
    [
        ("file:aas", "urn:template", 1),
        ("file:aas/catalog.json,file:aas", "urn:device-instance", 1),
        ("file:aas", "urn:device-instance", 0),
    ],
)
def test_configured_seed_batch(tmp_path, capsys, resources, second_id, expected):
    seeds = tmp_path / "aas"
    seeds.mkdir()
    for name, identifier in [("catalog.json", "urn:template"), ("device.json", second_id)]:
        (seeds / name).write_text(json.dumps({
            "submodels": [{"id": identifier, "idShort": "TechnicalDataAGV"}],
            # Shared dictionary definitions are allowed between packages.
            "conceptDescriptions": [{"id": "urn:shared-dictionary-entry"}],
        }), encoding="utf-8")
    (tmp_path / "aas-env.properties").write_text(
        "basyx.environment=" + resources, encoding="utf-8"
    )
    assert validator.check(seeds) == expected
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is (expected == 0)
    if expected:
        assert any(item.get("duplicateId") == "urn:template" for item in report["failures"])
