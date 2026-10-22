import copy

import pytest

from a4s.aasctl import updates
from test_instance_updates import Repository, prop


def test_review_repairs_legacy_semantic_key_without_changing_identity_or_live_data(tmp_path):
    repo = Repository()
    model = repo.models['urn:plate']
    model['semanticId'] = {'type': 'ExternalReference', 'keys': [
        {'type': 'Submodel', 'value': 'https://standard/Nameplate/1/0/Submodel'}]}
    model['submodelElements'][0]['category'] = ''
    before = copy.deepcopy(model)
    store = updates.Store(tmp_path / 'revisions.sqlite3')
    draft = updates.prepare(store, repo, 'http://target', 'urn:device', [])
    result = updates.review(store, draft['id'], [])
    candidate = result['reviewed']['submodels']['urn:plate']
    assert candidate['semanticId']['keys'][0]['type'] == 'GlobalReference'
    assert candidate['semanticId']['keys'][0]['value'] == before['semanticId']['keys'][0]['value']
    assert 'category' not in candidate['submodelElements'][0]
    assert candidate['id'] == before['id']
    assert result['before']['submodels']['urn:plate'] == before
    assert repo.models['urn:plate'] == before and not repo.writes
    assert any(c['action'] == 'schema-update' for c in result['changes'])
    assert result['compatibilityRepairs']


def test_review_does_not_relax_unrelated_type_errors(tmp_path):
    repo = Repository()
    repo.models['urn:plate']['submodelElements'] = [dict(prop('Count','invalid'), valueType='xs:integer')]
    store = updates.Store(tmp_path / 'revisions.sqlite3')
    draft = updates.prepare(store, repo, 'http://target', 'urn:device', [])
    with pytest.raises(updates.UpdateError, match='SME types'):
        updates.review(store, draft['id'], [])
    assert not repo.writes
