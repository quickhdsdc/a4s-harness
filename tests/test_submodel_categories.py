import copy
import json

import pytest

from a4s.aasctl import submodel_categories, updates
from a4s.kernel.providers import Completion, ModelConfig
from test_instance_updates import prop


class Model:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def complete(self, messages, tools, config, **kwargs):
        self.calls.append((messages, tools, config))
        return Completion(json.dumps(self.answer))


def inputs():
    templates = [{'id': 'urn:new-imm', 'idShort': 'TechnicalDataIMM',
                  'semanticId': {'keys': [{'value': 'urn:modern-imm'}]},
                  'submodelElements': [prop('MaxClampingForce')]}]
    existing = {'urn:old-imm': {'id': 'urn:old-imm', 'idShort': 'TechnicalData_IMM',
                              'semanticId': {'keys': [{'value': 'urn:legacy-technical'}]},
                              'submodelElements': [prop('MaxClampingForce', '1500')]},
                'urn:opc': {'id': 'urn:opc', 'idShort': 'UAServerDataSheet',
                            'submodelElements': [prop('Endpoint', 'opc.tcp://test:4840')]}}
    return templates, existing


def test_one_model_request_classifies_different_ids_by_meaning_and_keeps_unrelated_sm():
    templates, existing = inputs()
    original = copy.deepcopy((templates, existing))
    model = Model({'replacements': [{'template': 't0', 'replace': ['e0'],
                                    'reason': 'Both describe injection machine clamping specifications'}],
                   'retained': ['e1']})
    result = submodel_categories.classify(templates, existing, model, ModelConfig('fixture'))
    assert result['replacements'][0]['replaces'] == ['urn:old-imm']
    assert result['retainedIds'] == ['urn:opc']
    assert result['method'] == 'llm-batch' and len(model.calls) == 1
    payload = json.loads(model.calls[0][0][1]['content'])
    assert payload['existing'][0]['fields'][0]['path'] == 'MaxClampingForce'
    assert '1500' not in json.dumps(payload)  # Classification does not need value payloads.
    assert original == (templates, existing)


@pytest.mark.parametrize('answer', [
    {'replacements': [{'template': 't0', 'replace': ['e0'], 'reason': 'same'}], 'retained': []},
    {'replacements': [{'template': 't0', 'replace': ['e0', 'e0'], 'reason': 'same'}], 'retained': ['e1']},
    {'replacements': [{'template': 't0', 'replace': ['invented'], 'reason': 'same'}], 'retained': ['e0','e1']},
    {'replacements': [], 'retained': ['e0','e1']},
    {'replacements': [{'template': 't0', 'replace': ['e0'], 'reason': 'same'}], 'retained': ['e0','e1']},
])
def test_incomplete_invented_or_repeated_decisions_are_rejected(answer):
    templates, existing = inputs()
    with pytest.raises(updates.UpdateError, match='compare existing submodel categories'):
        submodel_categories.classify(templates, existing, Model(answer), ModelConfig('fixture'))


def test_no_templates_does_not_call_a_model():
    _, existing = inputs()
    model = Model({})
    result = submodel_categories.classify([], existing, model, ModelConfig('fixture'))
    assert not model.calls and set(result['retainedIds']) == set(existing)
