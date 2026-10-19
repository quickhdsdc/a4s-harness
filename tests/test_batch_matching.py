import json
from types import SimpleNamespace

import numpy as np
import pytest

from a4s.extract import Extracted, ExtractError, consolidate, merge_reporting
from a4s.aasctl.batch_match import match_all
from a4s.aasctl.index import Index, Node
from a4s.aasctl.match import Entity, value_for_write, element_for_create


class Reply:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def complete(self, messages, tools, config, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(text=json.dumps(self.body), finish_reason="stop")


CONFIG = SimpleNamespace(model="fake", max_tokens=32000)


def group(indices, mode="keep", selected=None):
    return dict(indices=indices, mode=mode, selected_index=indices[0] if selected is None else selected)


def test_supported_options_become_one_string_and_keep_both_sources():
    provider = Reply({"groups": [group([0, 1], "options")]})
    rows, _ = consolidate([Extracted("Communication", "CAN", source="p1"),
                           Extracted("Communication", "ModBus", source="p2")], provider, CONFIG)
    assert len(provider.calls) == 1
    assert len(rows) == 1
    assert rows[0].value == "CAN / ModBus"
    assert rows[0].source == "p1; p2"


def test_manufacturer_alias_keeps_complete_existing_value():
    provider = Reply({"groups": [group([0, 1], "equivalent", 1)]})
    rows, _ = consolidate([Extracted("Manufacturer", "PRIME"),
                           Extracted("Manufacturer", "PRIME Batteries Technology")], provider, CONFIG)
    assert rows[0].value == "PRIME Batteries Technology"


@pytest.mark.parametrize("rows", [
    [Extracted("Energy", "84", unit="Wh"), Extracted("Energy", "84", unit="kWh")],
    [Extracted("Voltage", "12", variant="A"), Extracted("Voltage", "24", variant="B")],
    [Extracted("Voltage", "12"), Extracted("Voltage", "24")],
])
def test_invalid_consolidation_cannot_hide_units_variants_or_numeric_conflicts(rows):
    with pytest.raises(ExtractError):
        consolidate(rows, Reply({"groups": [group([0, 1], "options")]}), CONFIG)


def test_exact_merge_preserves_distinct_units():
    rows, _ = merge_reporting([[Extracted("Energy", "84", unit="Wh"),
                                Extracted("Energy", "84", unit="kWh")]])
    assert len(rows) == 2


def test_equal_minimum_and_maximum_are_distinct_facts():
    rows = [Extracted("Minimum voltage", "12", unit="V"), Extracted("Maximum voltage", "12", unit="V")]
    assert len(merge_reporting([rows])[0]) == 2
    with pytest.raises(ExtractError, match="scopes"):
        consolidate(rows, Reply({"groups": [group([0, 1], "equivalent")]}), CONFIG)


def test_consolidation_cannot_omit_a_fact():
    with pytest.raises(ExtractError, match="omitted"):
        consolidate([Extracted("Communication", "CAN"), Extracted("Cooling", "Liquid")],
                    Reply({"groups": [group([0])]}), CONFIG)


def test_created_unique_name_survives_review_table_round_trip():
    from a4s.server.wizard_routes import _row_of, _decision_of
    from a4s.aasctl.match import Decision
    class Lookup:
        def resolve(self, row, target): return "urn:sm"
    decision = Decision(entity="Communication", value="CAN / ModBus", unit="", source="pdf",
                        action="create", band="hosted", reason="technical option", path="Group",
                        model_type="Property", container_type="SubmodelElementCollection",
                        id_short="Communication_2", value_type="xs:string")
    _, restored = _decision_of(_row_of(decision, "urn:sm", "TechnicalData"), Lookup())
    assert restored.id_short == "Communication_2"


def index(smid, nodes):
    return Index(submodel_id=smid, id_short=smid, model="fake", nodes=nodes,
                 vectors=np.array([[0., 1.] for _ in nodes], dtype="float32"))


def test_global_batch_returns_one_row_per_fact_with_typed_write_and_creation():
    indexes = [index("nameplate", [Node("ManufacturerName", "ManufacturerName", "MultiLanguageProperty", None)]),
               index("technical", [Node("TechnicalPropertyAreas", "TechnicalPropertyAreas", "SubmodelElementCollection", None)])]
    provider = Reply({"placements": [
        {"index": 0, "action": "write", "target": "s0n0", "model_type": "MultiLanguageProperty", "reason": "manufacturer"},
        {"index": 1, "action": "create", "target": "s1n0", "model_type": "Property", "reason": "supported communication"},
        {"index": 2, "action": "create", "target": "s1n0", "model_type": "Range", "reason": "temperature interval"},
    ]})
    entities = [Entity("Manufacturer", "PRIME"), Entity("Communication", "CAN / ModBus"),
                Entity("Operating temperature range", "-20 - 60", unit="C")]
    plans = match_all(indexes, entities, {"fake": np.array([[1., 0.]] * 3)}, provider, CONFIG)
    decisions = [d for p in plans for d in p.decisions]
    assert len(decisions) == 3
    assert len(provider.calls) == 1
    assert value_for_write(decisions[0]) == [{"en": "PRIME"}]
    assert decisions[1].action == "create"
    assert element_for_create(decisions[1])["value"] == "CAN / ModBus"
    assert element_for_create(decisions[2])["modelType"] == "Range"
    assert value_for_write(decisions[2]) == {"min": "-20", "max": "60"}


def test_model_cannot_override_incompatible_unit_filter_or_write_twice():
    indexes = [index("electrical", [Node("Energy", "Energy", "Property", None, unit="Wh")])]
    provider = Reply({"placements": [
        {"index": 0, "action": "write", "target": "s0n0", "reason": "energy"},
        {"index": 1, "action": "write", "target": "s0n0", "reason": "energy"},
        {"index": 2, "action": "write", "target": "s0n0", "reason": "energy"},
    ]})
    entities = [Entity("Energy", "84", unit="kWh"), Entity("Energy", "84", unit="Wh"), Entity("Energy", "90", unit="Wh")]
    plan = match_all(indexes, entities, {"fake": np.array([[1., 0.]] * 3)}, provider, CONFIG)[0]
    assert [d.action for d in plan.decisions] == ["skip", "write", "skip"]
