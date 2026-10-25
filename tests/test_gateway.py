from fastapi.testclient import TestClient
import httpx
import hashlib,sqlite3,time
from uuid import uuid4
from coordinator.gateway import create_app


def test_update_tool_preserves_confirmed_dispatch_and_callback_without_granting_completion():
    captured=[]
    class Core:
        def request(self,method,path,**kwargs):
            captured.append(kwargs['json'])
            return httpx.Response(200,json={'recorded':True,'verified_state_changed':False})
    with TestClient(create_app({'gateway_token':'synthetic','webhook_token':'synthetic'},client=Core())) as gateway:
        body={'call_token':'x'*30,'summary':'Hospital confirmed dispatch.','dispatch_reference':'DISP-SYN-1',
              'callback_at':'2026-10-24T19:00:00+05:30'}
        result=gateway.post('/voice/update',headers={'Authorization':'Bearer synthetic'},json=body)
        assert result.status_code==200
        assert captured[-1]['details']['dispatch_reference']=='DISP-SYN-1'
        assert captured[-1]['details']['callback_at']==body['callback_at']
        assert result.json()['verified_state_changed'] is False
        assert 'all I need for this call' in result.json()['call_closing_note']
        body.update(dispatch_reference='',callback_at='')
        gateway.post('/voice/update',headers={'Authorization':'Bearer synthetic'},json=body)
        assert set(captured[-1]['details'])=={'summary'}


def test_gateway_does_not_expose_private_surfaces():
    with TestClient(create_app({'gateway_token':'test-gateway','webhook_token':'test-webhook'})) as g:
        for path in ['/docs','/openapi.json','/v1/incidents','/hospital/cases','/evaluator/runs']:
            assert g.get(path).status_code==404


def test_gateway_requires_both_static_and_call_scoped_auth(core,core_config):
    with TestClient(create_app(core_config|{'environment':'operational','gateway_token':'test-gateway'},client=core)) as g:
        body={'call_token':'nonexistent-call-token-123456'}
        assert g.post('/voice/context',json=body).status_code==403
        assert g.post('/voice/context',json=body,headers={'Authorization':'Bearer test-gateway'}).status_code==403


def test_gateway_cannot_accept_arbitrary_privileged_operations(core,core_config):
    with TestClient(create_app(core_config|{'environment':'operational','gateway_token':'test-gateway'},client=core)) as g:
        assert g.post('/voice/statement',headers={'Authorization':'Bearer test-gateway'},json={
            'call_token':'nonexistent-call-token-123456','predicate':'APPROVE_CLAIM','reference':'DEMO',
            'fact_value':'approved'}).status_code==422
        assert g.post('/voice/webhook',json={'id':'unknown'}).status_code==403


def test_scoped_sandbox_token_routes_only_to_isolated_coordinator(tmp_path):
    class Upstream:
        def __init__(self,name):self.name=name;self.requests=[]
        def request(self,method,path,headers=None,**kwargs):
            self.requests.append((method,path,headers,kwargs))
            return httpx.Response(200,json={'target':self.name})
    operational=Upstream('operational');sandbox=Upstream('sandbox')
    config={'environment':'operational','core_url':'http://127.0.0.1:8124',
        'sandbox_core_url':'http://127.0.0.1:8126','gateway_token':'shared-gateway',
        'webhook_token':'operational-hook','sandbox_webhook_token':'sandbox-hook',
        'sandbox_route_db':str(tmp_path/'sandbox-routes.sqlite3'),'sandbox_route_registry_token':'broker-registry-token'}
    with TestClient(create_app(config,client=operational,sandbox_client=sandbox)) as gateway:
        headers={'Authorization':'Bearer shared-gateway'}
        response=gateway.post('/voice/context',headers=headers,json={'call_token':'sbx_short-lived-sandbox-capability'})
        assert response.status_code==200 and response.json()=={'target':'sandbox'}
        assert sandbox.requests[0][1]=='/v1/tools/context'
        assert sandbox.requests[0][2]['X-Call-Token']=='sbx_short-lived-sandbox-capability'
        assert operational.requests==[]
        response=gateway.post('/voice/context',headers=headers,json={'call_token':'op_short-lived-operational-capability'})
        assert response.status_code==200 and response.json()=={'target':'operational'}
        assert len(operational.requests)==1


def test_sandbox_webhook_uses_persisted_execution_route_and_separate_secret(tmp_path):
    class Upstream:
        def __init__(self,name):self.name=name;self.requests=[]
        def request(self,method,path,headers=None,**kwargs):
            self.requests.append((method,path,headers,kwargs))
            return httpx.Response(200,json={'target':self.name})
    operational=Upstream('operational');sandbox=Upstream('sandbox')
    config={'environment':'operational','core_url':'http://127.0.0.1:8124',
        'sandbox_core_url':'http://127.0.0.1:8126','gateway_token':'shared-gateway',
        'webhook_token':'operational-hook','sandbox_webhook_token':'sandbox-hook',
        'sandbox_route_db':str(tmp_path/'sandbox-routes.sqlite3'),'sandbox_route_registry_token':'broker-registry-token'}
    with TestClient(create_app(config,client=operational,sandbox_client=sandbox)) as gateway:
        execution_id=str(uuid4());call_token='sbx_'+('a'*48)
        assert gateway.get('/voice/sandbox-readiness').status_code==403
        readiness=gateway.get('/voice/sandbox-readiness',headers={'Authorization':'Bearer broker-registry-token'})
        assert readiness.json()=={'ready':True,'scope':'sandbox_callback_registry','phone_dispatch':False}
        assert gateway.post('/voice/register-sandbox-session',json={'execution_id':execution_id,'call_token':call_token}).status_code==403
        registered=gateway.post('/voice/register-sandbox-session',headers={'Authorization':'Bearer broker-registry-token'},
            json={'execution_id':execution_id,'call_token':call_token})
        assert registered.status_code==200 and registered.json()['phone_dispatch'] is False
        with sqlite3.connect(config['sandbox_route_db']) as db:
            value,expires_at=db.execute('SELECT call_token_hash,expires_at FROM sandbox_voice_routes WHERE execution_id=?',(execution_id,)).fetchone()
        assert value==hashlib.sha256(call_token.encode()).hexdigest()
        assert time.time()+890<expires_at<time.time()+910
        body={'execution_id':execution_id,'status':'completed'}
        response=gateway.post('/voice/webhook',headers={'X-Webhook-Token':'operational-hook'},json=body)
        assert response.status_code==200 and response.json()=={'target':'sandbox'}
        assert sandbox.requests[0][2]['X-Webhook-Token']=='sandbox-hook'
        assert operational.requests==[]


def test_unregistered_sandbox_webhook_fails_closed_without_operational_fallback(tmp_path):
    class Upstream:
        def __init__(self):self.requests=[]
        def request(self,method,path,headers=None,**kwargs):
            self.requests.append((method,path,headers,kwargs));return httpx.Response(200,json={'accepted':True})
    operational=Upstream();sandbox=Upstream()
    config={'environment':'operational','core_url':'http://127.0.0.1:8124',
        'sandbox_core_url':'http://127.0.0.1:8126','gateway_token':'shared-gateway',
        'webhook_token':'operational-hook','sandbox_webhook_token':'sandbox-hook',
        'sandbox_route_db':str(tmp_path/'sandbox-routes.sqlite3'),'sandbox_route_registry_token':'broker-registry-token'}
    with TestClient(create_app(config,client=operational,sandbox_client=sandbox)) as gateway:
        body={'id':str(uuid4()),'user_data':{'call_token':'sbx_'+('b'*48)}}
        response=gateway.post('/voice/webhook',headers={'X-Webhook-Token':'operational-hook'},json=body)
        assert response.status_code==403
        assert operational.requests==[] and sandbox.requests==[]


def test_sandbox_scope_fails_closed_when_separate_upstream_is_not_configured():
    with TestClient(create_app({'gateway_token':'shared-gateway','webhook_token':'operational-hook'})) as gateway:
        response=gateway.post('/voice/context',headers={'Authorization':'Bearer shared-gateway'},
            json={'call_token':'sbx_scoped-sandbox-capability'})
        assert response.status_code==503


def test_gateway_rejects_oversized_requests():
    with TestClient(create_app({'gateway_token':'test','webhook_token':'test'})) as g:
        assert g.post('/voice/context',content=b'x'*(1024*1024+1)).status_code==413


def test_hospital_can_record_unconfirmed_submission_without_claims_impersonation(core,env,cfg,core_config):
    from tests.test_worker import queued,enabled,FakeProvider
    from coordinator.worker import work_once
    import psycopg
    from psycopg.rows import dict_row
    id,job=queued(core,env,cfg);work_once(enabled(core_config),FakeProvider(),job['job_id'])
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        token=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']['user_data']['call_token']
    with TestClient(create_app(core_config|{'environment':'operational','gateway_token':'text-fixture'},client=core)) as gateway:
        context=gateway.post('/voice/context',json={'call_token':token},headers={'Authorization':'Bearer text-fixture'}).json()
        assert 'SUBMISSION_UNKNOWN' in context['allowed_statement_predicates']
        assert 'NOT_RECEIVED' not in context['allowed_statement_predicates']
        response=gateway.post('/voice/statement',headers={'Authorization':'Bearer text-fixture'},json={
            'call_token':token,'predicate':'SUBMISSION_UNKNOWN','reference':'HOSP-FINAL-1042','request_type':'FINAL_AUTHORIZATION',
            'fact_value':'Hospital checked records but cannot confirm final submission.'})
        assert response.status_code==201,response.text
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']=='HUMAN_REVIEW'
    assert detail['next_step']['kind']=='HUMAN_REVIEW'
    assert detail['assertions'][-1]['value']['confirmed'] is False
    assert not detail['actions'] and not detail['verified_receipts']
