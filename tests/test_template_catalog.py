from contextlib import nullcontext

import pytest
from fastapi import HTTPException

from a4s.aasctl.client import AasHttpError
from a4s.server import aas_routes


def test_templates_are_only_unique_template_refs_from_collection(monkeypatch):
    monkeypatch.setenv('A4S_SMT_COLLECTION', 'https://example.com/ids/aas/CollectionofSMTs')
    endpoints, reads = [], []
    class Repository:
        def list_submodel_refs(self, shell):
            assert shell == 'https://example.com/ids/aas/CollectionofSMTs'
            return [
                {'keys': [{'type': 'Submodel', 'value': 'urn:nameplate'}]},
                {'keys': [{'type': 'Submodel', 'value': 'urn:nameplate'}]},
                {'keys': [{'type': 'AssetAdministrationShell', 'value': 'urn:shell'}]},
                {'keys': [{'type': 'Submodel', 'value': 'urn:technical'}]},
                {'keys': [{'type': 'Submodel', 'value': 'urn:instance'}]},
            ]
        def get_submodel(self, identifier):
            reads.append(identifier)
            return {'id': identifier, 'idShort': identifier.split(':')[1],
                    'kind': 'Instance' if identifier == 'urn:instance' else 'Template',
                    'administration': {'version':'2','revision':'0'}}
        def list_submodels(self, **kwargs):
            pytest.fail('Must not enumerate unrelated blueprint templates')
    def client(endpoint):
        endpoints.append(endpoint)
        return nullcontext(Repository())
    monkeypatch.setattr(aas_routes, '_client', client)
    monkeypatch.setenv('A4S_SMT_ENDPOINT', 'http://templates:8081')
    rows = aas_routes.templates()
    assert [r['id'] for r in rows] == ['urn:nameplate', 'urn:technical']
    assert all(r['version']=='2' and r['revision']=='0' for r in rows)
    assert reads == ['urn:nameplate', 'urn:technical', 'urn:instance']
    assert endpoints == ['http://templates:8081']
    assert len(aas_routes.templates('http://explicit:8081', limit=1)) == 1
    assert endpoints[-1] == 'http://explicit:8081'


def test_missing_catalog_fails_without_repository_wide_fallback(monkeypatch):
    monkeypatch.setenv('A4S_SMT_COLLECTION', 'https://example.com/ids/aas/CollectionofSMTs')
    class Repository:
        def list_submodel_refs(self, shell):
            raise AasHttpError(404, 'http://templates/shells/catalog', 'Catalog missing')
        def list_submodels(self, **kwargs):
            pytest.fail('Missing catalog must not expose other templates')
    monkeypatch.setattr(aas_routes, '_client', lambda endpoint: nullcontext(Repository()))
    with pytest.raises(HTTPException) as exc:
        aas_routes.templates('http://templates:8081')
    assert exc.value.status_code == 404
