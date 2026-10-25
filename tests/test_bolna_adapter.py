from uuid import uuid4
import httpx
import pytest
from coordinator.bolna import Bolna,DispatchUnknown,ProviderRejected


def adapter(handler):
    return Bolna('test-only',httpx.Client(base_url='https://api.bolna.ai',transport=httpx.MockTransport(handler)))


def test_accepted_call_keeps_execution_identity():
    expected=str(uuid4());seen=[]
    def handler(r):
        seen.append(r)
        return httpx.Response(200,json={'status':'queued','execution_id':expected})
    b=adapter(handler)
    assert b.call(str(uuid4()),'+919999999999',{'purpose':'synthetic-test'})==expected
    assert len(seen)==1 and seen[0].url.path=='/call'


@pytest.mark.parametrize('status',[500,502,503])
def test_server_errors_are_uncertain_without_retry(status):
    seen=[]
    def handler(r):
        seen.append(r);return httpx.Response(status,json={})
    with pytest.raises(DispatchUnknown):
        adapter(handler).call(str(uuid4()),'+919999999999',{})
    assert len(seen)==1


def test_transport_timeout_never_retries():
    seen=[]
    def handler(r):
        seen.append(r);raise httpx.ReadTimeout('test',request=r)
    with pytest.raises(DispatchUnknown):
        adapter(handler).call(str(uuid4()),'+919999999999',{})
    assert len(seen)==1


def test_trial_or_configuration_rejection_is_explicit():
    with pytest.raises(ProviderRejected):
        adapter(lambda r:httpx.Response(403,json={})).call(str(uuid4()),'+919999999999',{})


def test_missing_execution_id_is_uncertain():
    with pytest.raises(DispatchUnknown):
        adapter(lambda r:httpx.Response(200,json={'status':'queued'})).call(str(uuid4()),'+919999999999',{})


def test_invalid_destination_rejected_before_network():
    with pytest.raises(ValueError):
        adapter(lambda r:pytest.fail('No network request expected')).call(str(uuid4()),'123',{})


def test_recording_uses_only_provider_execution_path():
    id=str(uuid4());seen=[]
    def handler(r):
        seen.append(r)
        return httpx.Response(200,headers={'content-type':'audio/wav'},content=b'RIFF-demo-audio')
    audio,mime=adapter(handler).recording(id)
    assert audio==b'RIFF-demo-audio' and mime=='audio/wav'
    assert seen[0].url.host=='api.bolna.ai' and seen[0].url.path=='/recordings/call/'+id


def test_recording_rejects_non_audio():
    with pytest.raises(ValueError):
        adapter(lambda r:httpx.Response(200,headers={'content-type':'text/html'},content=b'<html>')).recording(str(uuid4()))


def test_stop_requires_exact_provider_confirmation():
    id=str(uuid4());seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'execution_id':id,'status':'stopped'})
    assert adapter(handler).stop(id)['status']=='stopped'
    assert seen[0].method=='POST' and seen[0].url.path=='/call/'+id+'/stop'
    with pytest.raises(ValueError):
        adapter(lambda r:httpx.Response(200,json={'execution_id':str(uuid4()),'status':'stopped'})).stop(id)


def test_recording_redirect_does_not_forward_provider_key():
    id=str(uuid4());seen=[]
    def handler(request):
        seen.append(request)
        if request.url.host=='api.bolna.ai':
            return httpx.Response(307,headers={'location':'https://bolna-recordings-india.s3.amazonaws.com/test.mp3?signature=synthetic'})
        assert 'authorization' not in request.headers
        return httpx.Response(200,headers={'content-type':'audio/mpeg'},content=b'synthetic-audio')
    assert adapter(handler).recording(id)==(b'synthetic-audio','audio/mpeg')
    assert len(seen)==2


def test_recording_redirect_rejects_untrusted_host_before_request():
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(307,headers={'location':'https://untrusted.invalid/audio'})
    with pytest.raises(ValueError):
        adapter(handler).recording(str(uuid4()))
    assert len(seen)==1
