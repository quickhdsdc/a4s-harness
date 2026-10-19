from __future__ import annotations

import numpy as np

from a4s.aasctl.index import Index, Node
from a4s.aasctl.match import Entity
from a4s.aasctl.retrieval_match import Retriever


def index(nodes, vectors):
    return Index(submodel_id="urn:sm", id_short="Test", model="fake", nodes=nodes, vectors=np.asarray(vectors, dtype="float32"))


def node(name, **fields):
    return Node(path=name, id_short=name.rsplit(".", 1)[-1], model_type="Property", parent=None, **fields)


def test_unit_filter_removes_semantically_close_but_incompatible_property():
    retriever = Retriever(index([node("RatedCapacity", unit="Ah"), node("CapacityFade", unit="%")], [[.5,.866], [1,0]]))
    decision = retriever.decide(Entity("Nominal capacity", value="120", unit="Ah"), [1,0])
    assert decision.action == "write"
    assert decision.path == "RatedCapacity"
    assert "no LLM" in decision.reason


def test_synonym_and_dense_matching_does_not_require_property_names_to_be_identical():
    retriever = Retriever(index([node("RatedCapacity", unit="Ah"), node("Manufacturer")], [[1,0], [0,1]]))
    result = retriever.decide(Entity("How much charge can it hold", value="120", unit="Ah"), [1,0])
    assert result.path == "RatedCapacity"
    assert result.action == "write"


def test_equal_candidates_remain_unresolved_instead_of_creating_a_duplicate():
    nodes = [node("Cell.Resistance"), node("Pack.Resistance"), Node(path="Electrical", id_short="Electrical", model_type="SubmodelElementCollection", parent=None)]
    retriever = Retriever(index(nodes, [[1,0],[1,0],[1,0]]))
    decision = retriever.decide(Entity("Resistance", value="10"), [1,0])
    assert decision.action == "skip"
    assert len(decision.candidates) == 3


def test_unit_mismatch_cannot_be_accepted_even_with_an_exact_name():
    retriever = Retriever(index([node("InstalledEnergy", unit="Wh")], [[1,0]]))
    assert retriever.decide(Entity("Installed energy", value="84", unit="kWh"), [1,0]).action == "skip"


def test_unrelated_low_score_is_not_forced_into_the_nearest_property():
    retriever = Retriever(index([node("RatedCapacity")], [[0,1]]))
    assert retriever.decide(Entity("Airport runway length", value="10"), [1,0]).action == "skip"


def test_container_retrieval_creates_a_typed_suggestion_without_a_model():
    nodes = [Node(path="Dimensions", id_short="Dimensions", model_type="SubmodelElementCollection", parent=None)]
    retriever = Retriever(index(nodes, [[1,0]]))
    result = retriever.decide(Entity("Dimensions", value="250-550", unit="mm", source="p.2"), [1,0])
    assert result.action == "create"
    assert result.model_type == "Range"
    assert (result.min_value, result.max_value) == ("250", "550")
    assert result.warnings == []  # Review occurs in the UI; it is not a data warning.
    assert retriever.decide(Entity("Dimensions", value="250-550", unit="mm"), [1,0], create=False).action == "skip"


def test_non_scalar_types_are_excluded_and_range_requires_an_interval():
    nodes = [Node(path="Run", id_short="Run", model_type="Operation", parent=None),
             Node(path="Limits", id_short="Limits", model_type="Range", parent=None)]
    retriever = Retriever(index(nodes, [[1,0],[1,0]]))
    assert retriever.decide(Entity("Limits", value="single value"), [1,0]).action == "skip"


def test_boolean_or_numeric_fields_do_not_accept_arbitrary_text():
    retriever = Retriever(index([node("Ready", value_type="xs:boolean"), node("Voltage", value_type="xs:double")], [[1,0],[1,0]]))
    assert retriever.decide(Entity("Ready", value="sometimes"), [1,0]).action == "skip"
    assert retriever.decide(Entity("Voltage", value="unknown"), [1,0]).action == "skip"


def test_graph_ancestor_scope_separates_repeated_leaf_names():
    nodes = [Node(path="A", id_short="A", preferred_name="Battery cell", model_type="SubmodelElementCollection", parent=None),
             Node(path="B", id_short="B", preferred_name="Battery pack", model_type="SubmodelElementCollection", parent=None),
             Node(path="A.Resistance", id_short="Resistance", model_type="Property", parent="A"),
             Node(path="B.Resistance", id_short="Resistance", model_type="Property", parent="B")]
    retriever = Retriever(index(nodes, [[0,1],[0,1],[1,0],[.8,.6]]))
    result = retriever.decide(Entity("Pack resistance", value="10"), [1,0])
    assert result.path == "B.Resistance"
    assert abs(result.score - .8) < 1e-6


def test_unspecified_or_multiple_levels_do_not_force_a_graph_branch():
    retriever = Retriever(index([node("Cell.Resistance"), node("Pack.Resistance")], [[1,0],[1,0]]))
    for name in ("Resistance", "Resistance of pack and cell"):
        result = retriever.decide(Entity(name, value="10"), [1,0])
        assert result.action == "skip"
        assert len(result.candidates) == 2


def test_explicit_lower_limit_excludes_upper_limit_branch():
    retriever = Retriever(index([node("MinVoltage"), node("MaxVoltage")], [[.8,.6],[1,0]]))
    assert retriever.decide(Entity("Minimum voltage", value="200"), [1,0]).path == "MinVoltage"


def test_interval_cannot_populate_numeric_scalar():
    retriever = Retriever(index([node("OperatingTemperature", value_type="xs:double")], [[1,0]]))
    assert retriever.decide(Entity("Operating temperature", value="-20 to 40", unit="C"), [1,0]).action == "skip"


def test_incompatible_list_child_type_cannot_be_proposed_as_host():
    nodes = [Node(path="Files", id_short="Files", model_type="SubmodelElementList", parent=None, type_value_list_element="File")]
    retriever = Retriever(index(nodes, [[1,0]]))
    assert retriever.decide(Entity("Files", value="100"), [1,0]).action == "skip"


def test_label_equality_does_not_override_embedding_order():
    retriever = Retriever(index([node("Capacity"), node("ChargeStorage")], [[.5,.866],[1,0]]))
    result = retriever.decide(Entity("Capacity", value="100"), [1,0])
    assert result.path == "ChargeStorage"


def test_every_eligible_leaf_competes_without_a_lexical_shortlist():
    nodes = [node(f"RepeatedLabel{i}") for i in range(60)] + [node("DifferentWording")]
    retriever = Retriever(index(nodes, [[0,1]]*60 + [[1,0]]))
    assert retriever.decide(Entity("Repeated label", value="100"), [1,0]).path == "DifferentWording"


def test_empty_submodel_is_unresolved():
    retriever = Retriever(index([], []))
    assert retriever.decide(Entity("Capacity", value="100"), [1,0]).action == "skip"
