import pytest
from a4s.aasctl.match import Decision, Plan
from a4s.server.wizard_routes import _SubmodelLookup, _Unresolved


def test_legacy_review_reminder_is_removed_without_suppressing_actual_warnings():
    decision = Decision(entity="Voltage",value="24",unit="V",source="pdf",action="write",
        band="arbitrated",reason="matched",warnings=[
            "Review model placement and SME type before population", "unit mismatch: V vs kV"])
    assert decision.warnings == ["unit mismatch: V vs kV"]
    decision.warnings = ["Review model placement and SME type before population"]
    restored = Plan.from_json(Plan("urn:sm",1,0,None,[decision]).to_json())
    assert restored.decisions[0].warnings == []


class Scoped(_SubmodelLookup):
    def _submodels(self):
        return [{"id":"urn:one","idShort":"TechnicalData"},
                {"id":"urn:two","idShort":"TechnicalData"}]


def test_selected_canonical_id_disambiguates_two_same_named_submodels():
    lookup = Scoped(None,"TargetAAS")
    assert lookup.resolve({"submodelId":"urn:one"},
                          {"submodelId":"urn:two","semanticPath":"TechnicalData/Voltage"}) == "urn:two"


def test_submodel_outside_selected_aas_is_rejected_even_when_its_name_matches():
    with pytest.raises(_Unresolved,match="does not belong"):
        Scoped(None,"TargetAAS").resolve({}, {"submodelId":"urn:outside","semanticPath":"TechnicalData/Voltage"})


def test_unresolvable_selected_aas_never_falls_back_to_entire_repository(monkeypatch):
    from a4s.server import aas_routes
    from fastapi import HTTPException
    monkeypatch.setattr(aas_routes,"_resolve_shell",lambda *a: (_ for _ in ()).throw(HTTPException(404)))
    class Client:
        def list_submodels(self,**kwargs): pytest.fail("repository-wide lookup must not run")
    with pytest.raises(_Unresolved,match="refusing repository-wide"):
        _SubmodelLookup(Client(),"MissingAAS").resolve({}, {"submodelId":"urn:sm"})
