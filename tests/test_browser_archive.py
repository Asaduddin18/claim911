import base64,hashlib,json
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest
from tests.test_native_sandbox_calls import sandbox_core

TRANSCRIPT='assistant: Synthetic question?\nuser: Synthetic answer.\nassistant: Synthetic confirmation.'


@pytest.fixture
def browser_archive_case(sandbox_core,monkeypatch):
    core,cfg,incident=sandbox_core
    call=core.post(f'/v1/sandbox/incidents/{incident}/audio-calls',json={'purpose':'CAREGIVER_INTAKE','audio_provenance':'BOLNA_WEBRTC'}).json()
    execution=str(uuid4())
    core.post(f'/v1/sandbox/incidents/{incident}/audio-calls/{call["call_id"]}/bind-provider-execution',json={'execution_id':execution}).raise_for_status()
    # Stub provider-completion fixture only, never evidence of an actual call.
    with psycopg.connect(cfg['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET state='COMPLETED',transcript=%s WHERE id=%s",
            (Jsonb([{'speaker':'provider_transcript','text':TRANSCRIPT}]),call['call_id']))
    evidence={'execution_id':execution,'status':'completed','transcript':TRANSCRIPT}
    class Broker:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,headers,json):
            assert url=='http://127.0.0.1:8127/execution'
            assert json=={'execution_id':execution,'call_id':call['call_id'],'incident_id':incident}
            class Response:
                def raise_for_status(self):pass
                def json(self):return evidence
            return Response()
    monkeypatch.setattr('coordinator.browser_archive.httpx.Client',Broker)
    pcm=base64.b64encode(b'\x10\0'*160).decode()
    body={'execution_id':execution,'assistant_config_sha256':cfg['sandbox_bolna_agent_config_sha256'],
        'provider_transcript_sha256':hashlib.sha256(TRANSCRIPT.encode()).hexdigest(),
        'turns':[{'speaker':speaker,'text':text,'pcm_base64':pcm} for speaker,text in
            [('assistant','Synthetic question?'),('participant','Synthetic answer.'),('assistant','Synthetic confirmation.')]]}
    path=f'/v1/sandbox/incidents/{incident}/audio-calls/{call["call_id"]}/browser-archive'
    return core,cfg,incident,call,path,body,evidence


def test_browser_archive_preserves_provider_original_and_is_immutable(browser_archive_case):
    core,cfg,incident,call,path,body,_=browser_archive_case
    response=core.post(path,json=body);assert response.status_code==200,response.text
    assert response.json()['provider_transcript_preserved'] and not response.json()['verified_institution_outcome']
    assert core.post(path,json=body).json()==response.json()
    saved=core.get(path).json();assert saved['execution_id']==body['execution_id'] and len(saved['turns'])==3
    with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
        original=conn.execute('SELECT transcript FROM coordinator.calls WHERE id=%s',(call['call_id'],)).fetchone()['transcript']
        assert original==[{'speaker':'provider_transcript','text':TRANSCRIPT}]
        assert conn.execute('SELECT count(*) AS n FROM coordinator.sandbox_audio_artifacts WHERE call_id=%s',(call['call_id'],)).fetchone()['n']==3
    body['turns'][0]['pcm_base64']=base64.b64encode(b'\x20\0'*160).decode()
    assert core.post(path,json=body).status_code==409


@pytest.mark.parametrize('field,value',[('execution_id',str(uuid4())),('assistant_config_sha256','0'*64),('provider_transcript_sha256','0'*64)])
def test_wrong_provider_config_or_original_transcript_cannot_be_archived(browser_archive_case,field,value):
    core,_,_,_,path,body,_=browser_archive_case
    body[field]=value;assert core.post(path,json=body).status_code==409
    assert core.get(path).status_code==404


def test_provider_failure_or_rewritten_spoken_outcome_cannot_be_archived(browser_archive_case):
    core,_,_,_,path,body,evidence=browser_archive_case
    evidence['status']='failed';assert core.post(path,json=body).status_code==409
    evidence['status']='completed';body['turns'][-1]['text']='The insurer approved this claim.'
    assert core.post(path,json=body).status_code==409
    assert core.get(path).status_code==404


def test_local_finish_cannot_forge_bolna_completion(browser_archive_case):
    core,_,_,_,path,body,_=browser_archive_case
    assert core.post(path.replace('/browser-archive','/finish'),json={'turns':body['turns']}).status_code==409


def test_one_hundred_second_participant_recording_is_accepted_without_extending_assistant_limit(browser_archive_case):
    core,_,_,_,path,body,_=browser_archive_case
    body['turns'][1]['pcm_base64']=base64.b64encode(b'\x10\0'*(16000*100)).decode()
    assert core.post(path,json=body).status_code==200


def test_participant_audio_above_one_hundred_seconds_is_rejected(browser_archive_case):
    core,_,_,_,path,body,_=browser_archive_case
    body['turns'][1]['pcm_base64']=base64.b64encode(b'\x10\0'*(16000*100+1)).decode()
    assert core.post(path,json=body).status_code in {413,422}
