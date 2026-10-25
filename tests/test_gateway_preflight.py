import httpx
from coordinator.gateway_preflight import check_gateway


CONFIG={'gateway_url':'https://synthetic-test.trycloudflare.com','gateway_token':'synthetic-gateway-token'}


def test_preflight_checks_only_invalid_scopes_and_no_patient_data():
    seen=[]
    def handler(request):
        seen.append(request)
        if request.url.path=='/v1/incidents':return httpx.Response(404)
        if 'authorization' not in request.headers:return httpx.Response(403,json={'detail':'Voice gateway authentication required'})
        return httpx.Response(403,json={'detail':'Call context is missing, expired, inactive or revoked'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check_gateway(CONFIG,client)['ready']
    assert len(seen)==3
    assert b'gateway-preflight-invalid-scope-token' in seen[0].content
    assert all(r.url.path in ['/voice/context','/v1/incidents'] for r in seen)


def test_sandbox_preflight_requires_its_own_call_scope_to_reject_invalid_token():
    seen=[]
    def handler(request):
        seen.append(request)
        if request.url.path=='/v1/incidents':return httpx.Response(404)
        if request.headers.get('authorization')!='Bearer '+CONFIG['gateway_token']:
            return httpx.Response(403,json={'detail':'Voice gateway authentication required'})
        return httpx.Response(403,json={'detail':'Call context is missing, expired, inactive or revoked'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check_gateway(CONFIG,client,include_sandbox=True)['ready']
    assert len([r for r in seen if r.url.path=='/voice/context'])==3
    assert b'sbx_gateway-preflight-invalid-scope-token' in seen[3].content


def test_preflight_blocks_unreachable_tunnel_without_exposing_credentials():
    def handler(request):raise httpx.ConnectError('Private diagnostic detail',request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=check_gateway(CONFIG,client)
    assert not result['ready']
    assert 'Private diagnostic' not in result['reason']


def test_preflight_rejects_public_dashboard_and_unenforced_authentication():
    def handler(request):
        return httpx.Response(403,text='expired') if request.headers.get('authorization') else httpx.Response(200)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not check_gateway(CONFIG,client)['ready']
    def dashboard(request):
        return httpx.Response(200) if request.url.path=='/v1/incidents' else httpx.Response(403,text='expired')
    with httpx.Client(transport=httpx.MockTransport(dashboard)) as client:
        assert not check_gateway(CONFIG,client)['ready']
