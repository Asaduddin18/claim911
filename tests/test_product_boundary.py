"""Product roles, ownership and isolated database boundaries."""
import json,os
import hashlib
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from fastapi.testclient import TestClient
from experience.app import create_app
from coordinator.browser_voice import configured as browser_voice_configured

@pytest.fixture
def profiles():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated profile runtime required')
 return {p:json.loads((Path(root)/p/'coordinator.json').read_text())|{'test_mode':True} for p in ['operational','sandbox']}


def test_caregiver_cannot_access_operator_or_other_caregiver_cases(profiles,monkeypatch):
 cfg=profiles['operational']
 monkeypatch.setattr('coordinator.browser_voice.Bolna.agent_configuration_fingerprint',lambda *args:pytest.fail('Unowned case must be rejected before provider access'))
 monkeypatch.setattr('coordinator.browser_voice.Bolna.web_session',lambda *args:pytest.fail('Unowned case must never mint a session'))
 with TestClient(create_app(cfg)) as a,TestClient(create_app(cfg)) as b:
  assert a.get('/v2/caregiver/cases').status_code==401
  assert a.post('/v2/sessions',json={'role':'caregiver'}).status_code==200
  assert b.post('/v2/sessions',json={'role':'caregiver'}).status_code==200
  assert a.post('/v2/sessions',json={'role':'controller','credential':'wrong'}).status_code==403
  body={'name':'Synthetic caregiver','concern':'Synthetic discharge approval is delayed.','investigation_consent':True}
  r=a.post('/v2/caregiver/cases',json=body);assert r.status_code==201
  id=r.json()['id']
  assert a.get('/v2/caregiver/cases/'+id).status_code==200
  assert b.get('/v2/caregiver/cases/'+id).status_code==404
  assert b.post('/v2/caregiver/cases/'+id+'/voice-session',json={'recording_consent':True}).status_code==404
  assert a.get('/v2/controller/cases').status_code==401
  assert a.get('/v2/controller/cases/'+id+'/decisions').status_code==401
  assert b.post('/v2/caregiver/cases/'+id+'/consent',json={'accepted':False}).status_code==404
  assert a.post('/v2/caregiver/cases/'+id+'/consent',json={'accepted':False}).json()['consent_active'] is False
  assert a.post('/v2/caregiver/cases/'+id+'/consent',json={'accepted':True}).json()['consent_active'] is True
  assert a.get('/v2/sandbox/status').status_code==401
  assert a.get('/v1/incidents').status_code==404
  assert a.post('/v2/caregiver/cases',json=body|{'investigation_consent':False}).status_code==422
  assert not r.json()['coordination_available']
  assert r.json()['voice_available'] is browser_voice_configured(cfg)
  assert a.delete('/v2/sessions/caregiver').status_code==200
  assert a.get('/v2/caregiver/cases/'+id).status_code==401


def test_sandbox_cannot_create_operational_session_or_connect_operational_database(profiles):
 op=profiles['operational'];sb=profiles['sandbox']|{'sandbox_execution_enabled':False}
 with TestClient(create_app(sb)) as s,TestClient(create_app(op)) as o:
  assert s.post('/v2/sessions',json={'role':'caregiver'}).status_code==403
  assert s.post('/v2/sessions',json={'role':'sandbox','credential':op['operator_token']}).status_code==403
  assert s.post('/v2/sessions',json={'role':'sandbox','credential':sb['operator_token']}).status_code==200
  assert s.get('/v2/sandbox/status').json()['phone_dispatch_enabled'] is False
  prepared=s.post('/v2/sandbox/runs',json={'language':'en'}).json()
  assert s.post('/v2/sandbox/runs/'+prepared['id']+'/start').status_code==503
  assert s.get('/v2/sandbox/runs/'+prepared['id']).json()['state']=='PREPARED'
  assert s.get('/v2/controller/cases').status_code==401
  o.cookies.update(s.cookies)
  assert o.get('/v2/controller/cases').status_code==401
 from psycopg.conninfo import conninfo_to_dict,make_conninfo
 opdb=conninfo_to_dict(op['dsn'])['dbname']
 with pytest.raises(psycopg.OperationalError):
  psycopg.connect(make_conninfo(sb['dsn'],dbname=opdb))
 with pytest.raises(ValueError):create_app(sb|{'live_calls_enabled':True})
 with pytest.raises(ValueError):create_app(sb|{'bolna_api_key':'must-never-load'})


def test_sandbox_health_reports_its_broker_readiness_without_enabling_phone_dispatch(profiles):
 cfg=profiles['sandbox']|{
  'sandbox_bolna_broker_url':'http://127.0.0.1:8127',
  'sandbox_bolna_broker_token':'synthetic-test-token',
  'sandbox_bolna_agent_config_sha256':'a'*64,
 }
 with TestClient(create_app(cfg)) as client:
  health=client.get('/v2/health').json()
  assert health['environment']=='sandbox'
  assert health['browser_voice_available'] is True
  assert health['phone_dispatch_enabled'] is False
  login=client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  assert login.status_code==200
  assert client.get('/v2/sandbox/status').json()['bolna_browser_available'] is True


def test_document_access_is_case_owned_and_operator_scope_is_separate(profiles):
 cfg=profiles['operational']
 with TestClient(create_app(cfg)) as a,TestClient(create_app(cfg)) as b:
  a.post('/v2/sessions',json={'role':'caregiver'});b.post('/v2/sessions',json={'role':'caregiver'})
  id=a.post('/v2/caregiver/cases',json={'name':'Demo','concern':'Synthetic hospital coordination test','investigation_consent':True}).json()['id']
  r=a.post(f'/v2/caregiver/cases/{id}/documents',files={'file':('synthetic.txt',b'Synthetic receipt test','text/plain')},data={'kind':'other'})
  assert r.status_code==201
  did=r.json()['document_id']
  assert b.get(f'/v2/caregiver/cases/{id}/documents/{did}').status_code==404
  assert a.get(f'/v2/caregiver/cases/{id}/documents/{did}').status_code==200
  assert b.post('/v2/sessions',json={'role':'controller','credential':cfg['operator_token']}).status_code==200
  assert b.get('/v2/controller/cases/'+id).status_code==200
  reasoning=b.get('/v2/controller/cases/'+id+'/decisions')
  assert reasoning.status_code==200
  assert reasoning.json()['proposals'][0]['purpose']=='HOSPITAL_REFERENCE_DISCOVERY'
  assert reasoning.json()['policy_decisions'][0]['state']=='permitted'
  assert reasoning.json()['automatic_dispatch'] is False
  proposal=reasoning.json()['proposals'][0]
  callback={'proposal':proposal,'due_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
  assert a.post(f'/v2/controller/cases/{id}/callbacks',json=callback).status_code==401
  r=b.post(f'/v2/controller/cases/{id}/callbacks',json=callback)
  assert r.status_code==201 and 'lease_token' not in r.json()
  assert b.post(f'/v2/controller/cases/{id}/callbacks',json=callback).json()['id']==r.json()['id']
  assert len(b.get(f'/v2/controller/cases/{id}/callbacks').json())==1
  a.post(f'/v2/caregiver/cases/{id}/consent',json={'accepted':False})
  assert b.get(f'/v2/controller/cases/{id}/callbacks').json()[0]['state']=='CANCELLED'
  assert b.get('/v2/caregiver/cases/'+id).status_code==404


def test_legacy_reader_has_no_write_permission_and_requires_controller(profiles):
 cfg=profiles['operational']
 if not cfg.get('legacy_read_dsn'):pytest.skip('Legacy reader not installed')
 with TestClient(create_app(cfg)) as c:
  c.post('/v2/sessions',json={'role':'caregiver'})
  assert c.get('/v2/controller/legacy/cases').status_code==401
  c.post('/v2/sessions',json={'role':'controller','credential':cfg['operator_token']})
  rows=c.get('/v2/controller/legacy/cases').json()
  if rows:
   d=c.get('/v2/controller/legacy/cases/'+str(rows[0]['id'])).json()
   assert d['read_only'] is True
   if d['documents']:
    did=str(d['documents'][0]['id'])
    assert c.get('/v2/controller/legacy/cases/'+str(rows[0]['id'])+'/documents/'+did).status_code==200
    assert c.get('/v2/controller/legacy/cases/'+str(uuid4())+'/documents/'+did).status_code==404
   assert c.post('/v2/controller/legacy/cases/'+str(rows[0]['id']),json={}).status_code==405
 with psycopg.connect(cfg['legacy_read_dsn']) as conn:
  with pytest.raises(psycopg.errors.InsufficientPrivilege):
   conn.execute("UPDATE coordinator.incidents SET title=title WHERE false")


def test_exact_packet_permission_is_case_owned_current_and_revocable(profiles):
 from coordinator.app import create_app as core_app
 from simulator.app import create_app as institution_app
 from tests.test_complex_coordinator import setup,collect
 cfg=profiles['operational']
 sim=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'operational/simulator.json').read_text())
 with TestClient(core_app(cfg)) as core,TestClient(institution_app(sim)) as env,TestClient(create_app(cfg)) as caregiver,TestClient(create_app(cfg)) as stranger:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  id,cid=setup(core,env,sim);w=collect(core,env,sim,id,cid)
  caregiver.post('/v2/sessions',json={'role':'caregiver'});stranger.post('/v2/sessions',json={'role':'caregiver'})
  token=caregiver.cookies.get('claim911_operational_caregiver')
  with psycopg.connect(cfg['dsn']) as conn:
   sid=conn.execute('SELECT id FROM coordinator.product_sessions WHERE token_hash=%s',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]
   conn.execute("INSERT INTO coordinator.product_cases(incident_id,session_id,name,concern,language) VALUES(%s,%s,'Synthetic caregiver','Synthetic permission check','en')",(id,sid))
  path=f'/v2/caregiver/cases/{id}/packet-permission'
  body={'accepted':True,'packet_hash':w['packet_hash']}
  assert stranger.post(path,json=body).status_code==404
  assert caregiver.post(path,json=body|{'packet_hash':'0'*64}).status_code==409
  before=caregiver.get(f'/v2/caregiver/cases/{id}').json()
  assert before['status']=='Your document-sharing approval is needed'
  assert len(before['packet_permission']['documents'])==3
  assert all(d['evidence_checked'] for d in before['documents'] if d['name'] in {'billing.json','medical_records.json','implant_store.json'})
  response=caregiver.post(path,json=body)
  assert response.status_code==200 and response.json()['packet_permission']['approved']
  assert response.json()['status']=='Your approved packet is ready for hospital submission'
  approval=core.get(f'/v1/incidents/{id}/complex').json()['approval']
  assert approval['recorded_by']=='AUTHENTICATED_CASE_CAREGIVER'
  assert stranger.delete(path).status_code==404
  revoked=caregiver.delete(path).json()
  assert revoked['packet_permission']['approved'] is False
  assert revoked['status']=='Your document-sharing approval is needed'
  assert core.get(f'/v1/incidents/{id}/complex').json()['next_step']=='EXACT_PACKET_APPROVAL'


def test_caregiver_activity_is_paginated_owned_and_contains_no_raw_payloads(profiles):
 cfg=profiles['operational']
 with TestClient(create_app(cfg)) as a,TestClient(create_app(cfg)) as b:
  for client in [a,b]:client.post('/v2/sessions',json={'role':'caregiver'})
  id=a.post('/v2/caregiver/cases',json={'name':'Demo','concern':'Synthetic progress view test','investigation_consent':True}).json()['id']
  assert b.get(f'/v2/caregiver/cases/{id}/activity').status_code==404
  response=a.get(f'/v2/caregiver/cases/{id}/activity?limit=1');assert response.status_code==200
  page=response.json();assert len(page['items'])==1 and page['next_cursor']
  assert set(page['items'][0])=={'id','stage','title','at'}
  older=a.get(f'/v2/caregiver/cases/{id}/activity?limit=1&before={page["next_cursor"]}').json()
  assert older['items'][0]['id']<page['items'][0]['id']
  assert a.get(f'/v2/caregiver/cases/{id}/activity?limit=999').status_code==422
  assert b.get(f'/v2/caregiver/cases/{id}/conversations').status_code==404
  assert a.get(f'/v2/caregiver/cases/{id}/conversations/{uuid4()}').status_code==404


def test_controller_case_evidence_routes_require_role_and_matching_case(profiles):
 cfg=profiles['operational']
 with TestClient(create_app(cfg)) as caregiver,TestClient(create_app(cfg)) as operator:
  caregiver.post('/v2/sessions',json={'role':'caregiver'})
  body={'name':'Local case review','concern':'Synthetic discharge evidence review','investigation_consent':True}
  first=caregiver.post('/v2/caregiver/cases',json=body).json()['id']
  second=caregiver.post('/v2/caregiver/cases',json=body).json()['id']
  document=caregiver.post(f'/v2/caregiver/cases/{first}/documents',files={'file':('proof.txt',b'Local synthetic proof','text/plain')},data={'kind':'other'}).json()['document_id']
  for path in ['activity','conversations','documents/'+document]:
   assert caregiver.get(f'/v2/controller/cases/{first}/{path}').status_code==401
  operator.post('/v2/sessions',json={'role':'controller','credential':cfg['operator_token']})
  assert operator.get(f'/v2/controller/cases/{first}/activity?limit=1').status_code==200
  assert operator.get(f'/v2/controller/cases/{first}/activity?limit=999').status_code==422
  assert operator.get(f'/v2/controller/cases/{first}/conversations').json()['items']==[]
  assert operator.get(f'/v2/controller/cases/{first}/conversations/{uuid4()}').status_code==404
  read=operator.get(f'/v2/controller/cases/{first}/documents/{document}')
  assert read.content==b'Local synthetic proof' and read.headers['cache-control']=='no-store'
  assert operator.get(f'/v2/controller/cases/{second}/documents/{document}').status_code==404
  assert operator.get(f'/v2/controller/cases/{uuid4()}/activity').status_code==404


def test_controller_can_cancel_only_waiting_followups_in_requested_case(profiles):
 cfg=profiles['operational']
 with TestClient(create_app(cfg)) as caregiver,TestClient(create_app(cfg)) as controller:
  caregiver.post('/v2/sessions',json={'role':'caregiver'})
  body={'name':'Synthetic caregiver','concern':'Synthetic cancellation boundary check','investigation_consent':True}
  id=caregiver.post('/v2/caregiver/cases',json=body).json()['id']
  other=caregiver.post('/v2/caregiver/cases',json=body).json()['id']
  controller.post('/v2/sessions',json={'role':'controller','credential':cfg['operator_token']})
  proposal=controller.get(f'/v2/controller/cases/{id}/decisions').json()['proposals'][0]
  scheduled=controller.post(f'/v2/controller/cases/{id}/callbacks',json={'proposal':proposal,'due_at':datetime.now(timezone.utc).isoformat()})
  assert scheduled.status_code==201
  task=scheduled.json()['id'];path=f'/v2/controller/cases/{id}/callbacks/{task}'
  assert caregiver.delete(path).status_code==401
  assert controller.delete(f'/v2/controller/cases/{other}/callbacks/{task}').status_code==404
  assert controller.delete(path).json()['state']=='CANCELLED'
  assert controller.delete(path).json()['state']=='CANCELLED'
  assert controller.get(f'/v2/controller/cases/{id}/callbacks').json()[0]['state']=='CANCELLED'
  activity=controller.get(f'/v2/controller/cases/{id}/activity').json()['items']
  assert sum(item['title']=='A coordinator cancelled a waiting follow-up' for item in activity)==1
