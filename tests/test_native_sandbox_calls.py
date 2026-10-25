import base64,io,json,os,wave
from pathlib import Path
from uuid import uuid4
import psycopg
from fastapi.testclient import TestClient
import pytest
from coordinator.app import create_app


@pytest.fixture
def sandbox_core():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated sandbox profile required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text())
 with TestClient(create_app(cfg)) as core:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':str(uuid4()),'patient_id':'SYN-NATIVE-AUDIO','reference_known':False,'title':'[Integration test] Native sandbox audio'}).json()['incident_id']
  core.post(f'/v1/incidents/{id}/consent',json={'accepted':True,'confirmation':'Synthetic case audio investigation permission.'})
  yield core,cfg,id


def test_audio_call_uses_scoped_report_tools_without_phone_participant_or_job(sandbox_core):
 core,cfg,id=sandbox_core
 opened=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'})
 assert opened.status_code==201
 call=opened.json();assert call['mode']=='SANDBOX_AUDIO' and not call['phone_dispatch']
 token={'X-Call-Token':call['call_token']}
 assert core.post('/v1/tools/propose',headers=token).status_code==403
 body={'admission_id':'ADM-SYN-84','initial_reference':'INIT-SYN-1','enhancement_reference':'ENH-SYN-2',
       'final_reference':'FINAL-SYN-3','submission_status':'UNKNOWN','summary':'Synthetic staff confirmed three separate references.'}
 assert core.post('/v1/tools/references',json=body,headers=token).status_code==409
 assert core.get('/v1/tools/context',headers=token).status_code==200
 core.post(f'/v1/incidents/{id}/documents',files={'file':('new-evidence.txt',b'New synthetic evidence','text/plain')},data={'kind':'other'})
 assert core.post('/v1/tools/references',json=body,headers=token).status_code==409
 assert core.get('/v1/tools/context',headers=token).status_code==200
 assert core.post('/v1/tools/references',json=body,headers=token).status_code==200
 assert core.post('/v1/tools/workflow',headers=token,json={'operation':'REPORT_QUERY','details':{}}).status_code in {403,422}
 with psycopg.connect(cfg['dsn']) as conn:
  assert conn.execute('SELECT count(*) FROM coordinator.jobs WHERE incident_id=%s',(id,)).fetchone()[0]==0
  assert conn.execute('SELECT count(*) FROM coordinator.participants WHERE incident_id=%s',(id,)).fetchone()[0]==0
 assert cfg['outbound_paused'] is True and not cfg['live_calls_enabled']


def test_archived_audio_is_case_bound_immutable_and_not_institution_verification(sandbox_core):
 core,cfg,id=sandbox_core
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).json()
 assert core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).status_code==409
 body={'turns':[{'speaker':'participant','text':'Synthetic audio fixture only.','pcm_base64':base64.b64encode(b'\0\0'*160).decode()}]}
 path=f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish'
 response=core.post(path,json=body);assert response.status_code==200
 archive=response.json();assert archive['verified_institution_outcome'] is False
 artifact=archive['artifacts'][0]['id']
 r=core.get(f'/v1/sandbox/incidents/{id}/audio/{artifact}')
 assert r.status_code==200 and r.headers['content-type']=='audio/wav'
 with wave.open(io.BytesIO(r.content)) as wav:assert wav.getframerate()==16000 and wav.getnframes()==160
 assert core.get(f'/v1/sandbox/incidents/{uuid4()}/audio/{artifact}').status_code==404
 assert core.post(path,json=body).json()['artifacts']==archive['artifacts']
 body['turns'][0]['text']='Changed after archival'
 assert core.post(path,json=body).status_code==409
 assert core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).status_code==403
 detail=core.get(f'/v1/incidents/{id}').json()
 assert detail['incident']['state']=='INVESTIGATING' and detail['incident']['decision_state']=='PENDING'


def test_operational_profile_cannot_open_native_sandbox_calls(sandbox_core):
 _,_,id=sandbox_core
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'operational/coordinator.json').read_text())
 with TestClient(create_app(cfg)) as operational:
  operational.headers['Authorization']='Bearer '+cfg['operator_token']
  assert operational.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).status_code==404


def test_bolna_browser_audio_provenance_is_sandbox_scoped_and_never_queues_a_phone_call(sandbox_core):
 core,cfg,id=sandbox_core
 response=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={
  'purpose':'CAREGIVER_INTAKE','audio_provenance':'BOLNA_WEBRTC'})
 assert response.status_code==201,response.text
 call=response.json()
 assert call['mode']=='SANDBOX_AUDIO' and call['phone_dispatch'] is False
 assert core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).status_code==200
 with psycopg.connect(cfg['dsn']) as conn:
  row=conn.execute('SELECT mode,sandbox_audio_provenance,state FROM coordinator.calls WHERE id=%s',(call['call_id'],)).fetchone()
  jobs=conn.execute("SELECT count(*) FROM coordinator.jobs WHERE incident_id=%s AND kind='OUTBOUND_CALL'",(id,)).fetchone()[0]
 assert row==('SANDBOX_AUDIO','BOLNA_WEBRTC','IN_PROGRESS')
 assert jobs==0


def test_bolna_execution_is_bound_to_one_consented_sandbox_conversation(sandbox_core):
 core,cfg,id=sandbox_core
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={
  'purpose':'CAREGIVER_INTAKE','audio_provenance':'BOLNA_WEBRTC'}).json()
 execution=str(uuid4())
 path=f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/bind-provider-execution'
 response=core.post(path,json={'execution_id':execution})
 assert response.status_code==200,response.text
 assert response.json()=={'bound':True,'transport':'BOLNA_WEBRTC','phone_dispatch':False}
 assert core.post(path,json={'execution_id':execution}).status_code==200
 assert core.post(path,json={'execution_id':str(uuid4())}).status_code==409
 assert core.post(f'/v1/sandbox/incidents/{uuid4()}/audio-calls/{call["call_id"]}/bind-provider-execution',
  json={'execution_id':str(uuid4())}).status_code==404
 with psycopg.connect(cfg['dsn']) as conn:
  row=conn.execute('SELECT execution_id,mode,sandbox_audio_provenance FROM coordinator.calls WHERE id=%s',(call['call_id'],)).fetchone()
  assert row==(execution,'SANDBOX_AUDIO','BOLNA_WEBRTC')
  assert conn.execute("SELECT count(*) FROM coordinator.jobs WHERE incident_id=%s AND kind='OUTBOUND_CALL'",(id,)).fetchone()[0]==0


def test_interrupted_call_can_be_closed_without_fabricated_audio_or_outcome(sandbox_core):
 core,cfg,id=sandbox_core
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).json()
 path=f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/abort'
 assert core.post(f'/v1/sandbox/incidents/{uuid4()}/audio-calls/{call["call_id"]}/abort').status_code==404
 response=core.post(path);assert response.status_code==200
 assert response.json()['requires_reconciliation'] and not response.json()['verified_institution_outcome']
 assert core.post(path).json()==response.json()
 assert core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).status_code==403
 with psycopg.connect(cfg['dsn']) as db:
  assert db.execute('select count(*) from coordinator.sandbox_audio_artifacts where call_id=%s',(call['call_id'],)).fetchone()[0]==0
 assert core.get(f'/v1/incidents/{id}').json()['incident']['decision_state']=='PENDING'


def test_interrupted_audio_stays_playable_but_cannot_be_upgraded_to_completed(sandbox_core):
 core,cfg,id=sandbox_core
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'CAREGIVER_INTAKE'}).json()
 body={'outcome':'INTERRUPTED','turns':[{'speaker':s,'text':'Explicit offline partial-audio fixture.','pcm_base64':base64.b64encode(b'\0\0'*160).decode()} for s in ['participant','assistant']]}
 path=f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish'
 result=core.post(path,json=body);assert result.status_code==200 and result.json()['state']=='FAILED'
 assert core.post(path,json=body).json()==result.json()
 body['outcome']='COMPLETED';assert core.post(path,json=body).status_code==409
 artifact=result.json()['artifacts'][0]['id']
 assert core.get(f'/v1/sandbox/incidents/{id}/audio/{artifact}').status_code==200
 assert core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).status_code==403
