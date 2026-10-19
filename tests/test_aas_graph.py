import json
from contextlib import nullcontext
from dataclasses import asdict
import pytest

from a4s.aasctl.index import Node
from a4s.aasctl.client import AasHttpError
from a4s.server import aas_graph, aas_routes


class Repository:
    def __init__(self):
        self.shell = {'id': 'https://example/aas/one', 'idShort': 'One'}
        self.submodel = {'id': 'urn:technical', 'idShort': 'TechnicalData', 'submodelElements': [
            {'idShort': 'Group', 'modelType': 'SubmodelElementCollection', 'value': [
                {'idShort': 'Voltage', 'modelType': 'Property', 'valueType': 'xs:double', 'value': '24'}]}]}
    def get_shell(self, identifier): return self.shell
    def list_submodel_refs(self, identifier): return [{'keys': [{'value': self.submodel['id']}]}]
    def get_submodel(self, identifier): return self.submodel
    def list_concept_descriptions(self): return []


def test_parse_refreshes_scoped_graph_and_keeps_parent_and_sme_type(monkeypatch, tmp_path):
    monkeypatch.setenv('A4S_WEB_WORKSPACE', str(tmp_path))
    repository = Repository()
    monkeypatch.setattr(aas_routes, '_client', lambda endpoint: nullcontext(repository))
    first = aas_routes.parse_aas(repository.shell['id'], 'http://target:8081')
    assert first['success']
    graph = json.loads(open(first['graphPath'], encoding='utf-8').read())
    voltage = next(n for n in graph['nodes'] if n.get('path') == 'Group.Voltage')
    assert voltage['type'] == 'Property'
    assert voltage['parent'] == 'urn:technical::Group'
    assert graph['aasId'] == repository.shell['id']
    assert graph['endpoint'] == 'http://target:8081'
    repository.submodel['submodelElements'][0]['value'].append(
        {'idShort': 'Communication', 'modelType': 'Property', 'valueType': 'xs:string'})
    refreshed = aas_routes.parse_aas(repository.shell['id'], 'http://target:8081')
    assert refreshed['graphPath'] == first['graphPath']
    assert refreshed['count'] == first['count'] + 1
    other = aas_routes.parse_aas(repository.shell['id'], 'http://other:8081')
    assert other['graphPath'] != first['graphPath']


def test_descriptor_cache_detects_structure_changes_but_ignores_unembedded_values():
    node = Node(path='Group.Voltage', id_short='Voltage', model_type='Property', parent='Group', value='24')
    expected = asdict(node)
    expected['value'] = '48'
    assert aas_graph.same_structure([node], [expected])
    assert not aas_graph.same_structure([node], [expected], with_values=True)
    expected['path'] = 'Group.NominalVoltage'
    assert not aas_graph.same_structure([node], [expected])


def test_parse_keeps_existing_targets_when_shell_has_missing_submodels(monkeypatch, tmp_path):
    monkeypatch.setenv('A4S_WEB_WORKSPACE', str(tmp_path))
    repository = Repository()
    repository.list_submodel_refs = lambda _: [
        {'keys': [{'type': 'Submodel', 'value': 'urn:missing'}]},
        {'keys': [{'type': 'AssetAdministrationShell', 'value': repository.shell['id']},
                  {'type': 'Submodel', 'value': repository.submodel['id']}]},
        {'keys': [{'type': 'Submodel', 'value': repository.submodel['id']}]},
    ]
    reads = []
    def read(identifier):
        reads.append(identifier)
        if identifier == 'urn:missing':
            raise AasHttpError(404, 'http://target/submodels/missing', 'Not found')
        assert identifier == repository.submodel['id']
        return repository.submodel
    repository.get_submodel = read
    monkeypatch.setattr(aas_routes, '_client', lambda endpoint: nullcontext(repository))
    result = aas_routes.parse_aas(repository.shell['id'], 'http://target:8081')
    assert result['success'] and result['count'] == 2
    assert result['missingSubmodels'] == [{'id': 'urn:missing', 'status': 404}]
    graph = json.loads(open(result['graphPath'], encoding='utf-8').read())
    assert graph['endpoint'] == 'http://target:8081'
    assert list(graph['indexNodes']) == [repository.submodel['id']]
    assert reads == ['urn:missing', repository.submodel['id']]


@pytest.mark.parametrize('status', [401, 403, 500])
def test_parse_does_not_hide_repository_failures(monkeypatch, tmp_path, status):
    monkeypatch.setenv('A4S_WEB_WORKSPACE', str(tmp_path))
    repository = Repository()
    def read(_):
        raise AasHttpError(status, 'http://target/submodels/technical', 'Failure')
    repository.get_submodel = read
    with pytest.raises(AasHttpError) as exc:
        aas_graph.parse(repository, repository.shell, 'http://target:8081')
    assert exc.value.status == status
    assert not list(tmp_path.rglob('*_graph.json'))
