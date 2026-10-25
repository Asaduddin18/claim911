from uuid import uuid4
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from coordinator.bolna import DispatchUnknown, ProviderRejected
from tests.test_browser_voice_adapter import session
from sandbox.bolna_session_broker import create_app


def test_caregiver_final_update_never_restarts_intake():
    from sandbox.bolna_session_broker import greeting
    assert 'holding things up' in greeting(context())
    final=greeting(context(purpose='CAREGIVER_COMPLEX_UPDATE'))
    assert 'verified' in final and 'holding things up' not in final


def test_records_callback_opening_requests_owning_team_action():
    from sandbox.bolna_session_broker import greeting
    initial=greeting(context(purpose='RECORDS_DOCUMENT'))
    callback=greeting(context(purpose='RECORDS_DOCUMENT')|{'workflow':{'active_followup':{'purpose':'RECORDS_DOCUMENT','attempt':1}}})
    assert 'Has the treating team signed' in initial
    assert 'follow up with the treating team' in callback and 'upload' in callback
    assert 'if it can now be released' in callback


def test_browser_seed_excludes_accumulated_history_but_retains_role_evidence():
    from sandbox.bolna_session_broker import initial_voice_context
    source={'purpose':'DISCHARGE_FOLLOWUP','incident_id':'case','simulated':True,'workflow':{'reported_updates':['old']*1000,'clearance':{'refund_payment_state':'NOT_VERIFIED'},'decision':{'payable_inr':230000}},'instructions':'full authenticated context remains on the backend'}
    seed=initial_voice_context(source)
    assert seed['workflow']=={'clearance':{'refund_payment_state':'NOT_VERIFIED'},'decision':{'payable_inr':230000}}
    assert 'reported_updates' in source['workflow'] and 'instructions' not in seed


def config(tmp_path):
    return {
        'environment': 'sandbox_bolna_broker',
        'bolna_api_key': 'bn-synthetic-secret',
        'bolna_agent_id': str(uuid4()),
        'bolna_agent_config_sha256': 'a'*64,
        'broker_token': 'local-sandbox-product-token',
        'gateway_registry_token': 'private-gateway-registry-token',
        'gateway_url': 'https://claim911-demo.trycloudflare.com',
        'broker_registry_db': str(Path(tmp_path)/'broker-sessions.sqlite3'),
    }


def context(role='caregiver', purpose='CAREGIVER_INTAKE'):
    return {'call_id': str(uuid4()), 'incident_id': str(uuid4()), 'simulated': True,
            'participant_role': role, 'purpose': purpose, 'patient_id':'DEMO-PATIENT-84',
            'reference':'FIN63','objective': 'Help with the synthetic discharge case.'}


class Provider:
    def __init__(self, fingerprint='a'*64, error=None, execution_status='completed'):
        self.fingerprint=fingerprint;self.error=error;self.execution_status=execution_status
        self.user_data=None;self.mints=0;self.recording_calls=[];self.execution_calls=[]
    def agent_configuration_fingerprint(self, agent_id):
        return self.fingerprint
    def web_session(self, agent_id, user_data):
        self.mints+=1;self.user_data=user_data
        if self.error:raise self.error
        return session(agent_id)
    def recording(self, execution_id):
        self.recording_calls.append(execution_id)
        return b'RIFFsynthetic-audio','audio/wav'
    def execution(self,execution_id):
        self.execution_calls.append(execution_id)
        transcript=None if self.execution_status=='balance-low' else 'assistant: Synthetic question?\nuser: Synthetic answer.'
        return {'id':execution_id,'status':self.execution_status,'transcript':transcript,'user_data':{'sensitive':'redact'}}


class Registry:
    def __init__(self,status=200,health_status=200):self.status=status;self.health_status=health_status;self.calls=[]
    def get(self,url,headers):
        return type('Response',(),{'status_code':self.health_status,'json':lambda _: {'ready':True,'scope':'sandbox_callback_registry','phone_dispatch':False}})()
    def post(self,url,headers,json):
        self.calls.append((url,headers,json));return type('Response',(),{'status_code':self.status})()


def test_broker_mints_only_ephemeral_session_and_registers_hash_scoped_sandbox_route(tmp_path):
    cfg=config(tmp_path);provider=Provider();registry=Registry()
    token='sbx_'+('k'*48);case=context('hospital','HOSPITAL_REFERENCE_DISCOVERY')
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        assert client.post('/session',json={'call_token':token,'recording_consent':True,'context':case}).status_code==403
        response=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},
            json={'call_token':token,'recording_consent':True,'context':case})
        result=response.json()
        audio=client.post('/recording',headers={'Authorization':'Bearer '+cfg['broker_token']},json={
            'execution_id':result['session']['run_id'],'call_id':case['call_id'],'incident_id':case['incident_id']})
        assert audio.status_code==200 and audio.content==b'RIFFsynthetic-audio'
        assert audio.headers['cache-control']=='private, no-store'
    assert response.status_code==201,response.text
    assert result['transport']=='BOLNA_WEBRTC' and result['synthetic'] and result['phone_dispatch'] is False
    assert result['call_id']==case['call_id']
    assert 'call_token' not in response.text and cfg['bolna_api_key'] not in response.text
    assert provider.user_data['call_token']==token
    assert provider.user_data['claim911_purpose']==case['purpose']
    assert 'patient_id' in provider.user_data['claim911_context']
    assert provider.user_data['claim911_greeting'].startswith('Hi, this is Claim911 calling about patient DEMO-PATIENT-84.')
    assert registry.calls[0][0].endswith('/voice/register-sandbox-session')
    assert registry.calls[0][1]['Authorization']=='Bearer '+cfg['gateway_registry_token']
    assert registry.calls[0][2]=={'execution_id':result['session']['run_id'],'call_token':token}
    assert provider.recording_calls==[result['session']['run_id']]


def test_hospital_discovery_opening_asks_for_case_specific_information_without_field_names(tmp_path):
    cfg=config(tmp_path);provider=Provider();registry=Registry()
    case=context('hospital','HOSPITAL_REFERENCE_DISCOVERY')|{'patient_id':'DEMO-PATIENT-84'}
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        response=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},json={
            'call_token':'sbx_'+('h'*48),'recording_consent':True,'context':case})
    assert response.status_code==201,response.text
    assert provider.user_data['claim911_greeting']==(
        'Hi, this is Claim911 calling about patient DEMO-PATIENT-84. Could you check the admission ID for me?')
    assert 'patient_id' not in provider.user_data['claim911_greeting']


def test_broker_recording_requires_exact_registered_sandbox_call(tmp_path):
    cfg=config(tmp_path);provider=Provider();registry=Registry();case=context()
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        opened=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},json={
            'call_token':'sbx_'+('y'*48),'recording_consent':True,'context':case}).json()
        base={'execution_id':opened['session']['run_id'],'call_id':case['call_id'],'incident_id':case['incident_id']}
        headers={'Authorization':'Bearer '+cfg['broker_token']}
        assert client.post('/recording',json=base).status_code==403
        assert client.post('/recording',headers=headers,json=base|{'incident_id':str(uuid4())}).status_code==404
        assert client.post('/recording',headers=headers,json=base|{'execution_id':str(uuid4())}).status_code==404
    assert provider.recording_calls==[]


def test_broker_execution_transcript_is_sandbox_session_scoped_and_sanitized(tmp_path):
    cfg=config(tmp_path);provider=Provider();registry=Registry();case=context()
    headers={'Authorization':'Bearer '+cfg['broker_token']}
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        opened=client.post('/session',headers=headers,json={
            'call_token':'sbx_'+('e'*48),'recording_consent':True,'context':case}).json()
        body={'execution_id':opened['session']['run_id'],'call_id':case['call_id'],'incident_id':case['incident_id']}
        assert client.post('/execution',json=body).status_code==403
        assert client.post('/execution',headers=headers,json=body|{'incident_id':str(uuid4())}).status_code==404
        response=client.post('/execution',headers=headers,json=body)
    assert response.status_code==200
    assert response.json()=={'execution_id':body['execution_id'],'status':'completed',
        'transcript':'assistant: Synthetic question?\nuser: Synthetic answer.','conversation_duration':None}
    assert 'user_data' not in response.text and cfg['bolna_api_key'] not in response.text
    assert provider.execution_calls==[body['execution_id']]


def test_broker_preserves_provider_balance_low_as_terminal_evidence_without_transcript(tmp_path):
    cfg=config(tmp_path);provider=Provider(execution_status='balance-low');registry=Registry();case=context()
    headers={'Authorization':'Bearer '+cfg['broker_token']}
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        opened=client.post('/session',headers=headers,json={
            'call_token':'sbx_'+('b'*48),'recording_consent':True,'context':case}).json()
        body={'execution_id':opened['session']['run_id'],'call_id':case['call_id'],'incident_id':case['incident_id']}
        response=client.post('/execution',headers=headers,json=body)
    assert response.status_code==200,response.text
    assert response.json()=={'execution_id':body['execution_id'],'status':'balance-low','transcript':'','conversation_duration':None}


def test_configuration_drift_withholds_session_before_mint(tmp_path):
    cfg=config(tmp_path);provider=Provider(fingerprint='b'*64);registry=Registry()
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        response=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},
            json={'call_token':'sbx_'+('m'*48),'recording_consent':True,'context':context()})
    assert response.status_code==409 and provider.mints==0 and registry.calls==[]


def test_broker_rejects_non_synthetic_context_wrong_role_and_missing_recording_consent(tmp_path):
    cfg=config(tmp_path);provider=Provider();registry=Registry()
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        headers={'Authorization':'Bearer '+cfg['broker_token']}
        body={'call_token':'sbx_'+('r'*48),'recording_consent':True,'context':context()}
        assert client.post('/session',headers=headers,json=body|{'context':context()|{'simulated':False}}).status_code==422
        assert client.post('/session',headers=headers,json=body|{'context':context('caregiver','QUERY_DISCOVERY')}).status_code==422
        assert client.post('/session',headers=headers,json={'call_token':body['call_token'],'context':body['context']}).status_code==422
    assert provider.mints==0 and registry.calls==[]


def test_session_is_withheld_when_execution_route_cannot_be_persisted(tmp_path):
    cfg=config(tmp_path);provider=Provider();registry=Registry(status=503)
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        response=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},
            json={'call_token':'sbx_'+('z'*48),'recording_consent':True,'context':context()})
    assert response.status_code==503 and provider.mints==1
    assert 'sip_password' not in response.text and registry.calls
    import sqlite3
    with sqlite3.connect(cfg['broker_registry_db']) as db:
        stage,execution_id=db.execute('SELECT stage,execution_id FROM sandbox_bolna_attempts').fetchone()
    assert stage=='CALLBACK_ROUTE_FAILED' and execution_id


def test_duplicate_session_attempt_never_mints_again_even_after_uncertainty(tmp_path):
    import sqlite3
    cfg=config(tmp_path);provider=Provider(error=DispatchUnknown('uncertain'));case=context()
    with TestClient(create_app(cfg,provider=provider,registry_client=Registry())) as client:
        body={'call_token':'sbx_'+('j'*48),'recording_consent':True,'context':case}
        headers={'Authorization':'Bearer '+cfg['broker_token']}
        assert client.post('/session',headers=headers,json=body).status_code==503
        assert client.post('/session',headers=headers,json=body).status_code==409
    assert provider.mints==1
    with sqlite3.connect(cfg['broker_registry_db']) as db:
        assert db.execute('SELECT stage,execution_id FROM sandbox_bolna_attempts').fetchone()==('MINT_UNCERTAIN',None)


def test_unavailable_callback_gateway_blocks_before_provider_mint(tmp_path):
    cfg=config(tmp_path);provider=Provider()
    with TestClient(create_app(cfg,provider=provider,registry_client=Registry(health_status=503))) as client:
        response=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},json={
            'call_token':'sbx_'+('v'*48),'recording_consent':True,'context':context()})
    assert response.status_code==503 and provider.mints==0
    assert 'no provider session was requested' in response.json()['detail']


@pytest.mark.parametrize('provider_error',[ProviderRejected('rejected'),DispatchUnknown('uncertain')])
def test_provider_rejection_and_uncertain_session_do_not_retry(provider_error,tmp_path):
    cfg=config(tmp_path);provider=Provider(error=provider_error);registry=Registry()
    with TestClient(create_app(cfg,provider=provider,registry_client=registry)) as client:
        response=client.post('/session',headers={'Authorization':'Bearer '+cfg['broker_token']},
            json={'call_token':'sbx_'+('q'*48),'recording_consent':True,'context':context()})
        assert response.status_code==503
    assert provider.mints==1 and registry.calls==[]


@pytest.mark.parametrize('extra',[
    {'dsn':'postgres://operational'}, {'simulator_agent_token':'must-not-enter'},
    {'legacy_read_dsn':'postgres://legacy'}, {'operator_token':'operator'},
])
def test_broker_refuses_configuration_with_operational_or_institution_secrets(extra,tmp_path):
    with pytest.raises(ValueError):create_app(config(tmp_path)|extra,provider=Provider(),registry_client=Registry())
