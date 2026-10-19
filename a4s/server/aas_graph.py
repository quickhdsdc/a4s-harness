"""Repository-scoped AAS structure snapshots for the wizard's matching input."""
from dataclasses import asdict
import hashlib
import json
import os
import time
import uuid

from ..aasctl import index
from ..aasctl.client import AasHttpError, Endpoint
from . import workspace


def parse(client, shell, endpoint=None):
    repository = Endpoint.from_env(endpoint).base_url.rstrip('/')
    key = 'aas_' + hashlib.sha256((repository + '\0' + shell['id']).encode()).hexdigest()[:24]
    identifiers = list(dict.fromkeys(
        k['value'] for ref in client.list_submodel_refs(shell['id'])
        for k in ref.get('keys', [])
        if k.get('value') and k.get('type', 'Submodel') == 'Submodel'
    ))
    submodels, missing_submodels = [], []
    for identifier in identifiers:
        try:
            submodels.append(client.get_submodel(identifier))
        except AasHttpError as exc:
            if exc.status != 404:
                raise
            # A shell can retain references to deleted/unpublished submodels.
            # Only existing submodels in this repository are matching targets.
            missing_submodels.append({'id': identifier, 'status': 404})
    concepts = index.concept_map(client.list_concept_descriptions())
    nodes = [{'id': 'aas:' + shell['id'], 'type': 'AssetAdministrationShell', 'idShort': shell.get('idShort')}]
    edges = []
    by_submodel = {}
    for sm in submodels:
        identifier = sm['id']
        walked = index.walk(sm)
        index.enrich(walked, concepts)
        by_submodel[identifier] = [asdict(node) for node in walked]
        nodes.append({'id': identifier, 'type': 'Submodel', 'idShort': sm.get('idShort')})
        edges.append({'source': 'aas:' + shell['id'], 'target': identifier, 'relation': 'hasSubmodel'})
        for node in walked:
            token = identifier + '::' + node.path
            parent = identifier + '::' + node.parent if node.parent else identifier
            nodes.append({**asdict(node), 'id': token, 'parent': parent, 'type': node.model_type})
            edges.append({'source': parent, 'target': token, 'relation': 'contains'})
    graph = {'schemaVersion': 1, 'endpoint': repository, 'aasId': shell['id'],
             'aasIdShort': shell.get('idShort'), 'workspaceKey': key, 'parsedAt': time.time(),
             'submodels': submodels, 'missingSubmodels': missing_submodels,
             'concepts': concepts, 'indexNodes': by_submodel,
             'nodes': nodes, 'edges': edges}
    directory = workspace.root() / 'graphs'
    directory.mkdir(parents=True, exist_ok=True)
    path = workspace.under(directory, key + '_graph.json')
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.partial')
    try:
        temporary.write_text(json.dumps(graph, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return graph, path


def same_structure(nodes, expected, with_values=False):
    def structural(rows):
        return [{k: v for k, v in row.items() if with_values or k != 'value'} for row in rows]
    return structural([asdict(n) for n in nodes]) == structural(expected)
