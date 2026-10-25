from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
from sandbox.broker import CapabilityRegistry, create_broker


def setup_gateway(executor=None, max_calls=2):
    now = [0]
    calls = []
    def execute(*args):
        calls.append(args)
        return {'synthetic': True, 'state': 'reported'}
    registry = CapabilityRegistry(executor or execute, clock=lambda: now[0])
    run, case = str(uuid4()), str(uuid4())
    token = registry.issue(run, case, 'billing', ttl=10, max_calls=max_calls)
    client = TestClient(create_broker(registry, environment='sandbox'))
    headers = {'Authorization': 'Bearer '+token}
    body = dict(run_id=run, case_id=case, role='billing', operation='read_status', arguments={}, request_id=str(uuid4()))
    return registry, client, headers, body, now, calls


def test_run_role_case_and_operation_boundaries():
    registry, client, headers, body, now, calls = setup_gateway()
    assert client.post('/tools', json=body).status_code == 401
    for changes in ({'run_id':str(uuid4())}, {'case_id':str(uuid4())}, {'role':'insurer'}, {'operation':'issue_fixed_decision'}):
        assert client.post('/tools', json=body|changes, headers=headers).status_code == 403
    assert client.post('/tools', json=body|{'url':'http://host.docker.internal:8120'}, headers=headers).status_code == 422
    assert client.post('/mint', json={}, headers=headers).status_code == 404
    assert not calls
    with pytest.raises(ValueError): create_broker(registry, environment='operational')


def test_idempotency_budget_expiry_and_revocation():
    registry, client, headers, body, now, calls = setup_gateway()
    assert client.post('/tools', json=body, headers=headers).status_code == 200
    assert client.post('/tools', json=body, headers=headers).status_code == 200
    assert len(calls) == 1
    assert client.post('/tools', json=body|{'arguments':{'changed':True}}, headers=headers).status_code == 409
    assert client.post('/tools', json=body|{'request_id':str(uuid4())}, headers=headers).status_code == 200
    assert client.post('/tools', json=body|{'request_id':str(uuid4())}, headers=headers).status_code == 429
    now[0] = 10
    assert client.post('/tools', json=body, headers=headers).status_code == 401
    registry, client, headers, body, _, _ = setup_gateway()
    registry.revoke_run(body['run_id'])
    assert client.post('/tools', json=body, headers=headers).status_code == 401


def test_unknown_result_never_reexecutes_and_errors_do_not_leak_secrets():
    calls = []
    def fail(*args):
        calls.append(args)
        raise RuntimeError('PRIVATE-INSTITUTION-SECRET')
    _, client, headers, body, _, _ = setup_gateway(fail)
    for _ in range(2):
        response = client.post('/tools', json=body, headers=headers)
        assert response.status_code == 409
        assert 'PRIVATE-INSTITUTION-SECRET' not in response.text
    assert len(calls) == 1
    assert client.post('/tools', content=b'x'*20001, headers=headers).status_code == 413
