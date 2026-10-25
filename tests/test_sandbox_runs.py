import json,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from coordinator.app import create_app
from experience.app import create_app as product_app
from sandbox import runs

PROVENANCE={'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'}


@pytest.fixture
def run_case():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated sandbox runtime required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text())
 with TestClient(create_app(cfg)) as core:
  core.headers['Authorization']='Bearer '+cfg['operator_token'];case=str(uuid4())
  id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':case,'patient_id':'SYN-RUN-CONTROL','reference_known':False,'title':'[Integration test] Durable run lifecycle'}).json()['incident_id']
  core.post(f'/v1/incidents/{id}/consent',json={'accepted':True,'confirmation':'Synthetic run control investigation permission.'})
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:runs.initialize(conn,environment='sandbox')
  yield cfg,core,id,case


def ready(conn,id,case):
 run=runs.create(conn)
 return runs.attach_case(conn,run['id'],incident_id=id,institution_case_id=case,provider_configuration=PROVENANCE)


def test_pause_requires_acknowledgment_and_lost_worker_never_autorestarts(run_case):
 cfg,_,id,case=run_case;now=datetime.now(timezone.utc)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  run=ready(conn,id,case);leased=runs.claim(conn,run['id'],now=now)
  assert runs.claim(conn,run['id'],now=now) is None
  paused=runs.control(conn,run['id'],'pause');assert paused['state']=='PAUSE_REQUESTED'
  with pytest.raises(HTTPException):runs.control(conn,run['id'],'resume')
  runs.acknowledge_stop(conn,run['id'],leased['lease_token'])
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert runs.get(conn,run['id'])['state']=='PAUSED'
  runs.control(conn,run['id'],'resume');runs.claim(conn,run['id'],now=now)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert runs.claim(conn,run['id'],now=now+timedelta(minutes=4)) is None
  assert runs.get(conn,run['id'])['state']=='UNCERTAIN'
  with pytest.raises(HTTPException):runs.control(conn,run['id'],'resume')
  fresh=runs.control(conn,run['id'],'reset')
  assert fresh['id']!=run['id'] and fresh['state']=='PREPARED'
  assert runs.get(conn,run['id'])['state']=='UNCERTAIN'


def test_checkpoint_needs_independent_evidence_and_cannot_skip_gates(run_case):
 cfg,_,id,case=run_case
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  run=ready(conn,id,case);leased=runs.claim(conn,run['id']);name=run['manifest']['checkpoints'][0]
  with pytest.raises(HTTPException):runs.complete_checkpoint(conn,run['id'],leased['lease_token'],name,['incident:'+id],verify=lambda *a:False)
  with pytest.raises(HTTPException):runs.complete_checkpoint(conn,run['id'],leased['lease_token'],'insurer_decision_verified',['incident:'+id],verify=lambda *a:True)
  assert runs.get(conn,run['id'])['checkpoint']==0
  # Stub verifies only state-machine sequencing, not a real case outcome.
  observed=[]
  updated=runs.complete_checkpoint(conn,run['id'],leased['lease_token'],name,['incident:'+id],verify=lambda *a:observed.append(a) or True)
  assert updated['checkpoint']==1 and updated['state']=='RUNNING'
  assert str(observed[0][1])==id
  assert 'lease_token' not in runs.public(updated)
  with pytest.raises(HTTPException):runs.advance_clock(conn,run['id'],10)


def test_consent_change_and_time_limit_prevent_claim(run_case):
 cfg,core,id,case=run_case
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  run=ready(conn,id,case);runs.advance_clock(conn,run['id'],900)
  assert runs.claim(conn,run['id']) is None
  assert runs.get(conn,run['id'])['state']=='ESCALATED'
  second=ready(conn,id,case)
 core.post(f'/v1/incidents/{id}/consent',json={'accepted':False,'confirmation':'Synthetic caregiver withdrew investigation consent.'})
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert runs.claim(conn,second['id']) is None
  assert runs.get(conn,second['id'])['state']=='CANCELLED'


def test_run_api_is_sandbox_only_and_preparation_does_not_claim_execution(run_case):
 cfg,_,_,_=run_case
 cfg=cfg|{'sandbox_execution_enabled':False}
 with TestClient(product_app(cfg)) as client:
  assert client.post('/v2/sandbox/runs',json={}).status_code==401
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  run=client.post('/v2/sandbox/runs',json={'language':'hi'})
  assert run.status_code==201 and run.json()['state']=='PREPARED'
  assert run.json()['provider_configuration'] is None
  id=run.json()['id']
  assert client.post(f'/v2/sandbox/runs/{id}/clock',json={'seconds':True}).status_code==422
  assert client.post(f'/v2/sandbox/runs/{id}/clock',json={'seconds':30}).json()['elapsed_seconds']==30
  assert client.post(f'/v2/sandbox/runs/{id}/control',json={'operation':'resume'}).status_code==409
  reset=client.post(f'/v2/sandbox/runs/{id}/control',json={'operation':'reset'}).json()
  assert reset['id']!=id and reset['checkpoint']==0
  assert not client.get('/v2/sandbox/status').json()['runner_available']
 op=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'operational/coordinator.json').read_text())
 with TestClient(product_app(op)) as client:
  client.post('/v2/sessions',json={'role':'caregiver'})
  assert client.post('/v2/sandbox/runs',json={}).status_code==401
  assert client.get('/v2/sandbox/runs').status_code==401


@pytest.mark.parametrize('checkpoint,purpose,role',[(0,'CAREGIVER_INTAKE','caregiver'),(1,'HOSPITAL_REFERENCE_DISCOVERY','hospital')])
def test_sandbox_bolna_session_stays_case_scoped_and_never_exposes_call_token(run_case,monkeypatch,checkpoint,purpose,role):
 # Broker is a local test double. Do not unsuspend the real budget.
 monkeypatch.setattr('sandbox.spend.require_testing',lambda conn:None)
 cfg,_,incident_id,case_id=run_case
 fingerprint='b'*64
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  run=ready(conn,incident_id,case_id)
  if checkpoint:
   # Route fixture only. This does not prove that a real checkpoint completed.
   from psycopg.types.json import Jsonb
   conn.execute('UPDATE coordinator.sandbox_runs SET checkpoint=%s,provider_configuration=%s WHERE id=%s',
    (checkpoint,Jsonb({'transport':'BOLNA_WEBRTC','assistant_config_sha256':fingerprint}),run['id']))
   runs.claim(conn,run['id'])
 cfg=cfg|{'sandbox_bolna_broker_url':'http://127.0.0.1:8127','sandbox_bolna_broker_token':'sandbox-product-secret',
  'sandbox_bolna_agent_config_sha256':fingerprint}
 observed={}
 class BrokerResponse:
  status_code=201
  def json(self):return {'call_id':observed['payload']['context']['call_id'],'transport':'BOLNA_WEBRTC',
   'synthetic':True,'phone_dispatch':False,'assistant_config_sha256':fingerprint,
   'session':{'run_id':str(uuid4()),'agent_id':str(uuid4()),'sip_username':'ephemeral','sip_password':'ephemeral',
    'sip_domain':'voice.invalid','wss_url':'wss://voice.invalid','sip_register':False,'expires_in':120,'ice_servers':[]}}
 class BrokerClient:
  def __init__(self,*args,**kwargs):pass
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def post(self,url,headers,json):
   observed.update(url=url,headers=headers,payload=json)
   return BrokerResponse()
 monkeypatch.setattr('httpx.Client',BrokerClient)
 with TestClient(product_app(cfg)) as client:
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  response=client.post(f'/v2/sandbox/runs/{run["id"]}/voice-session',json={'recording_consent':True})
 assert response.status_code==201,response.text
 result=response.json()
 assert result['transport']=='BOLNA_WEBRTC' and result['synthetic'] and result['phone_dispatch'] is False
 assert 'call_token' not in result and 'call_token' not in str(result['session'])
 assert observed['url']=='http://127.0.0.1:8127/session'
 assert observed['headers']['Authorization']=='Bearer sandbox-product-secret'
 assert observed['payload']['call_token'].startswith('sbx_')
 assert observed['payload']['context']['incident_id']==incident_id
 assert observed['payload']['context']['simulated'] is True
 assert observed['payload']['context']['purpose']==purpose
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  saved=runs.get(conn,run['id'])
  assert saved['provider_configuration']=={'transport':'BOLNA_WEBRTC','assistant_config_sha256':fingerprint}
  audio=conn.execute("SELECT mode,sandbox_audio_provenance,participant_role,purpose FROM coordinator.calls WHERE incident_id=%s",(incident_id,)).fetchone()
  assert audio=={'mode':'SANDBOX_AUDIO','sandbox_audio_provenance':'BOLNA_WEBRTC','participant_role':role,'purpose':purpose}


def test_sandbox_bolna_session_requires_local_broker_and_sandbox_role(run_case):
 cfg,_,_,_=run_case
 cfg=cfg|{'sandbox_bolna_broker_url':'','sandbox_bolna_broker_token':'','sandbox_bolna_agent_config_sha256':''}
 with TestClient(product_app(cfg)) as client:
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  run=client.post('/v2/sandbox/runs',json={}).json()
  assert client.post(f'/v2/sandbox/runs/{run["id"]}/voice-session',json={'recording_consent':True}).status_code==503
 op=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'operational/coordinator.json').read_text())
 with TestClient(product_app(op)) as client:
  client.post('/v2/sessions',json={'role':'caregiver'})
  assert client.post(f'/v2/sandbox/runs/{run["id"]}/voice-session',json={'recording_consent':True}).status_code==401


def test_sandbox_bolna_broker_rejects_remote_urls_before_opening_a_call(run_case,monkeypatch):
 cfg,_,_,_=run_case
 cfg=cfg|{'sandbox_bolna_broker_url':'https://untrusted.example/session','sandbox_bolna_broker_token':'do-not-send',
  'sandbox_bolna_agent_config_sha256':'c'*64}
 with TestClient(product_app(cfg)) as client:
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  run=client.post('/v2/sandbox/runs',json={}).json()
  result=client.post(f'/v2/sandbox/runs/{run["id"]}/voice-session',json={'recording_consent':True})
 assert result.status_code==503
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert runs.get(conn,run['id'])['incident_id'] is None


def test_uncertain_bolna_mint_holds_run_without_automatic_retry(run_case,monkeypatch):
 # Broker is a local test double. Do not unsuspend the real budget.
 monkeypatch.setattr('sandbox.spend.require_testing',lambda conn:None)
 cfg,_,incident_id,case_id=run_case
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:run=ready(conn,incident_id,case_id)
 cfg=cfg|{'sandbox_bolna_broker_url':'http://127.0.0.1:8127','sandbox_bolna_broker_token':'sandbox-product-secret',
  'sandbox_bolna_agent_config_sha256':'d'*64}
 class BrokerResponse:
  status_code=503
 class BrokerClient:
  def __init__(self,*args,**kwargs):pass
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def post(self,*args,**kwargs):return BrokerResponse()
 monkeypatch.setattr('httpx.Client',BrokerClient)
 with TestClient(product_app(cfg)) as client:
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  response=client.post(f'/v2/sandbox/runs/{run["id"]}/voice-session',json={'recording_consent':True})
 assert response.status_code==503
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  saved=runs.get(conn,run['id']);assert saved['state']=='UNCERTAIN'
  assert runs.get(conn,run['id'])['provider_configuration']==PROVENANCE
  call=conn.execute("SELECT state,mode,sandbox_audio_provenance FROM coordinator.calls WHERE incident_id=%s ORDER BY created_at DESC LIMIT 1",(incident_id,)).fetchone()
  assert call=={'state':'FAILED','mode':'SANDBOX_AUDIO','sandbox_audio_provenance':'BOLNA_WEBRTC'}
  assert runs.claim(conn,run['id']) is None and runs.get(conn,run['id'])['state']=='UNCERTAIN'


def test_worker_uncertainty_preserves_already_withheld_session(run_case):
 cfg,_,incident_id,case_id=run_case
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  run=ready(conn,incident_id,case_id);leased=runs.claim(conn,run['id'])
  first=runs.mark_uncertain(conn,run['id'],leased['lease_token'],'session creation uncertain')
  second=runs.mark_uncertain(conn,run['id'],leased['lease_token'],'worker transport failure')
  assert first['state']==second['state']=='UNCERTAIN' and second['lease_token'] is None
  count=conn.execute("SELECT count(*) AS n FROM coordinator.sandbox_run_events WHERE run_id=%s AND type='RUN_EXECUTION_UNCERTAIN'",(run['id'],)).fetchone()['n']
  assert count==1


def test_component_run_retains_evidence_gate_and_public_scope(run_case):
 cfg,_,id,case=run_case
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  run=runs.create(conn,origin='AUDIO_DEMONSTRATION',component='hospital_references_reported')
  run=runs.attach_case(conn,run['id'],incident_id=id,institution_case_id=case,provider_configuration=PROVENANCE)
  lease=runs.claim(conn,run['id'])
  with pytest.raises(HTTPException):
   runs.complete_checkpoint(conn,run['id'],lease['lease_token'],'hospital_references_reported',['incident:'+id],verify=lambda *a:False)
  row=runs.get(conn,run['id'])
  assert row['checkpoint']==0
  assert runs.public(row)['execution_scope']=='COMPONENT'
  assert runs.public(row)['checkpoint_count']==1
  assert not runs.full_case_completed(row)


def test_paused_paid_testing_blocks_worker_and_manual_mint_before_any_dispatch(run_case,monkeypatch):
 cfg,_,_,_=run_case
 cfg=cfg|{'sandbox_execution_enabled':True,'sandbox_bolna_broker_url':'http://127.0.0.1:8127',
          'sandbox_bolna_broker_token':'test-only','sandbox_bolna_agent_config_sha256':'e'*64}
 paused={'allowed':False,'code':'PAID_TESTING_PAUSED','message':'Paid testing is paused.'}
 monkeypatch.setattr('sandbox.spend.testing_readiness',lambda conn,now=None:paused)
 monkeypatch.setattr('sandbox.preparation.bind',lambda *a,**kw:pytest.fail('Paused testing cannot prepare or dispatch a case'))
 with TestClient(product_app(cfg)) as client:
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  run=client.post('/v2/sandbox/runs',json={}).json()
  monkeypatch.setattr('httpx.Client',lambda *a,**kw:pytest.fail('Paused testing cannot contact a broker or provider'))
  status=client.get('/v2/sandbox/status').json()
  assert status['paid_testing_allowed'] is False and status['paid_testing_code']=='PAID_TESTING_PAUSED'
  for path in ['start','voice-session']:
   response=client.post(f'/v2/sandbox/runs/{run["id"]}/{path}',json={'recording_consent':True} if path=='voice-session' else None)
   assert response.status_code==503 and 'paused' in response.json()['detail']
  current=client.get(f'/v2/sandbox/runs/{run["id"]}').json()
  assert current['state']=='PREPARED' and current['incident_id'] is None
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert conn.execute("SELECT count(*) AS count FROM coordinator.jobs WHERE payload->>'run_id'=%s",(run['id'],)).fetchone()['count']==0
