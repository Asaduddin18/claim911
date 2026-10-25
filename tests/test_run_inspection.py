import base64,hashlib,json,os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
import pytest
from coordinator.app import create_app as core_app
from experience.app import create_app
from sandbox import runs
from tests.test_checkpoint_verifier import services


@pytest.fixture
def cfg():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated profile runtime required')
 return json.loads((Path(root)/'sandbox/coordinator.json').read_text())


def test_run_audio_requires_its_run_call_artifact_and_sandbox_session(cfg):
 with TestClient(core_app(cfg)) as core,TestClient(create_app(cfg)) as product:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':str(uuid4()),'patient_id':'SYN-INSPECT','reference_known':False,'title':'[Integration test] Run audio ownership'}).json()['incident_id']
  core.post(f'/v1/incidents/{id}/consent',json={'accepted':True,'confirmation':'Synthetic fixture permits audio inspection.'})
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as db:
   run=runs.create(db,origin='VERIFICATION_FIXTURE');runs.attach_case(db,run['id'],incident_id=id,institution_case_id=core.get('/v1/incidents/'+id).json()['incident']['case_id'],provider_configuration={'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'})
   other=runs.create(db)
  call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'CAREGIVER_INTAKE'}).json()
  audio=base64.b64encode(b'\0\0'*160).decode()
  finished=core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':[{'speaker':s,'text':'Offline inspection fixture.','pcm_base64':audio} for s in ['participant','assistant']]}).json()
  artifact=finished['artifacts'][0]['id'];path=f'/v2/sandbox/runs/{run["id"]}'
  assert product.get(path).status_code==401
  product.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  listed=product.get('/v2/sandbox/runs').json()
  assert str(run['id']) not in {r['id'] for r in listed}
  assert str(other['id']) not in {r['id'] for r in listed}
  detail=product.get(path).json()
  assert detail['checkpoint']==0 and len(detail['checkpoints'])==13 and not detail['full_case_completed']
  assert detail['outcome'] is None
  assert 'lease_token' not in detail and 'tool_token_hash' not in json.dumps(detail)
  audio_path=path+f'/conversations/{call["call_id"]}/audio/{artifact}'
  response=product.get(audio_path);assert response.status_code==200 and response.headers['content-type']=='audio/wav'
  assert product.get(f'/v2/sandbox/runs/{other["id"]}/conversations/{call["call_id"]}').status_code==404
  assert product.get(path+f'/conversations/{call["call_id"]}/audio/{uuid4()}').status_code==404


def test_provider_execution_is_proxied_through_the_bound_sandbox_session(cfg,monkeypatch):
 cfg=cfg|{'sandbox_bolna_broker_url':'http://127.0.0.1:8127','sandbox_bolna_broker_token':'private-broker-token'}
 with TestClient(core_app(cfg)) as core,TestClient(create_app(cfg)) as product:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  incident=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={
   'case_id':str(uuid4()),'patient_id':'SYN-PROVIDER-EXEC','reference_known':False,
   'title':'[Integration test] Bound provider execution'}).json()['incident_id']
  core.post(f'/v1/incidents/{incident}/consent',json={'accepted':True,'confirmation':'Synthetic provider evidence test.'})
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as db:
   run=runs.create(db,origin='AUDIO_DEMONSTRATION')
   case_id=core.get('/v1/incidents/'+incident).json()['incident']['case_id']
   runs.attach_case(db,run['id'],incident_id=incident,institution_case_id=case_id,
    provider_configuration={'transport':'BOLNA_WEBRTC','assistant_config_sha256':cfg['sandbox_bolna_agent_config_sha256']})
   assert runs.claim(db,run['id'])['state']=='RUNNING'
   other=runs.create(db)
   harness_token='sbxh_'+uuid4().hex
   db.execute('INSERT INTO coordinator.sandbox_harness_tokens(token_hash,run_id) VALUES(%s,%s)',
    (hashlib.sha256(harness_token.encode()).hexdigest(),run['id']))
  call=core.post(f'/v1/sandbox/incidents/{incident}/audio-calls',json={
   'purpose':'CAREGIVER_INTAKE','audio_provenance':'BOLNA_WEBRTC'}).json()
  execution=str(uuid4())
  assert core.post(f'/v1/sandbox/incidents/{incident}/audio-calls/{call["call_id"]}/bind-provider-execution',
   json={'execution_id':execution}).status_code==200
  class Response:
   status_code=200
   def json(self):return {'execution_id':execution,'status':'completed','transcript':'assistant: Synthetic test transcript.','conversation_duration':4}
  class Broker:
   def __init__(self,**kwargs):pass
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def post(self,url,**kwargs):
    assert url=='http://127.0.0.1:8127/execution'
    assert kwargs['json']=={'execution_id':execution,'call_id':call['call_id'],'incident_id':incident}
    return Response()
  monkeypatch.setattr('httpx.Client',Broker)
  login=product.post('/v2/sessions',json={'role':'sandbox_harness','credential':harness_token,'run_id':str(run['id'])})
  assert login.status_code==200,login.text
  assert product.get('/v2/sandbox/runs').json()[0]['id']==str(run['id'])
  path=f'/v2/sandbox/runs/{run["id"]}/conversations/{call["call_id"]}/provider-execution'
  response=product.post(path,json={})
  assert response.status_code==200,response.text
  assert response.json()=={'execution_id':execution,'status':'completed','transcript':'assistant: Synthetic test transcript.','conversation_duration':4}
  assert product.get(f'/v2/sandbox/runs/{other["id"]}').status_code==404
  assert product.post(f'/v2/sandbox/runs/{run["id"]}/control',json={'operation':'cancel'}).status_code==401


def test_completed_fixture_outcome_is_source_backed_and_does_not_claim_refund_payment(services,cfg):
 from tests.test_scenario_executor import setup_executor
 executor,db,run,_=setup_executor(services)
 for _ in range(16):
  result=executor.step()
  if result['state']=='WAITING_CALLBACK':
   with db() as conn:runs.advance_clock(conn,run['id'],60)
  if result['state']=='COMPLETED':break
 with TestClient(create_app(cfg)) as product:
  product.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  detail=product.get('/v2/sandbox/runs/'+str(run['id'])).json()
 assert detail['full_case_completed'] and detail['origin']=='VERIFICATION_FIXTURE'
 outcome=detail['outcome'];assert outcome['synthetic']
 assert outcome['financials']['refund_due_inr']==12000
 assert outcome['financials']['refund_payment_state']=='NOT_VERIFIED'
 assert outcome['summary']['refund_payment_verified'] is False
 assert all(statement['source']['id'] for statement in outcome['summary']['statements'])
