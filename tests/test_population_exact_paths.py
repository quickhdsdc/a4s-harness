import json
import httpx

from a4s.aasctl.client import BasyxClient, Endpoint
from a4s.aasctl.match import Decision
from a4s.aasctl.paths import ElementPath
from a4s.server import wizard_routes


def test_reviewed_write_preserves_nonconforming_idshort_through_http(monkeypatch):
    path = 'TechnicalPropertyAreas.Lifetime.ExpectedLifetimeInCalendarYears '
    calls = []

    def respond(request):
        calls.append(request)
        # The real repository contains the name WITH its final space.
        if request.url.path.endswith(path + '/$value'):
            return httpx.Response(204)
        return httpx.Response(404, json={'error': 'ElementDoesNotExistException'})

    client = BasyxClient(Endpoint('http://basyx.test'))
    client.close()
    client._http = httpx.Client(base_url='http://basyx.test', transport=httpx.MockTransport(respond))
    monkeypatch.setattr(wizard_routes, '_client', lambda endpoint: client)
    decision = Decision(entity='Design service life', value='10', unit='years', source='pdf',
                        action='write', band='auto', reason='Exact existing element',
                        path=path, model_type='Property', value_type='xs:unsignedInt')
    wizard_routes._apply_one('urn:technical', decision, 'http://basyx.test')
    assert calls[0].method == 'PATCH'
    assert calls[0].url.raw_path.endswith(b'ExpectedLifetimeInCalendarYears%20/$value')
    assert json.loads(calls[0].content) == '10'
    assert ElementPath.parse(path).render() == path
