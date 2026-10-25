"""Browser sessions require case ownership and cannot create telephone jobs."""
import json,os
from pathlib import Path
from uuid import uuid4
import psycopg,pytest
from fastapi.testclient import TestClient
from experience.app import create_app
from coordinator.bolna import DispatchUnknown
from coordinator.agent_fingerprint import fingerprint
from tests.test_browser_voice_adapter import session


@pytest.fixture
def browser_config(monkeypatch):
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated profile runtime required')
 cfg=json.loads((Path(root)/'operational/coordinator.json').read_text())|{
  'browser_voice_enabled':True,'bolna_api_key':'synthetic-browser-key','bolna_agent_id':str(uuid4()),'outbound_paused':False,'test_mode':True}
 agent=json.loads((Path(root)/'bolna-agent.json').read_text())
 cfg['bolna_agent_config_sha256']=fingerprint(agent)
 monkeypatch.setattr('coordinator.browser_voice.Bolna.agent_configuration_fingerprint',lambda self,agent_id:cfg['bolna_agent_config_sha256'])
 monkeypatch.setattr('coordinator.browser_voice.check_gateway',lambda cfg:{'ready':True})
 return cfg


def case(client):
 client.post('/v2/sessions',json={'role':'caregiver'})
 return client.post('/v2/caregiver/cases',json={'name':'Synthetic caregiver','concern':'Synthetic discharge coordination','investigation_consent':True}).json()['id']


def test_browser_session_is_case_owned_ephemeral_and_never_queues_phone(browser_config,monkeypatch):
 cfg=browser_config;seen=[]
 def mint(self,agent,data):seen.append(data);return session(agent)
 monkeypatch.setattr('coordinator.browser_voice.Bolna.web_session',mint)
 with TestClient(create_app(cfg)) as owner,TestClient(create_app(cfg)) as stranger:
  id=case(owner);stranger.post('/v2/sessions',json={'role':'caregiver'})
  path=f'/v2/caregiver/cases/{id}/voice-session'
  assert stranger.post(path,json={'recording_consent':True}).status_code==404
  assert owner.post(path,json={'recording_consent':False}).status_code==422
  assert owner.post(path,json={'recording_consent':True,'user_data':{}}).status_code==422
  response=owner.post(path,json={'recording_consent':True})
  assert response.status_code==201 and response.headers['cache-control']=='no-store'
  assert response.json()['transport']=='BOLNA_WEBRTC'
  assert 'call_token' not in response.text and cfg['bolna_api_key'] not in response.text
  assert owner.post(path,json={'recording_consent':True}).status_code==409
  assert len(seen)==1 and seen[0]['claim911_purpose']=='CAREGIVER_INTAKE'
  assert len(seen[0]['call_token'])>=20 and json.loads(seen[0]['claim911_context'])['participant_role']=='caregiver'
  assert json.loads(seen[0]['claim911_context'])['investigation_consent_active'] is True
  assert stranger.post(path+'/'+response.json()['call_id']+'/stop').status_code==404
  assert owner.post(path+'/'+response.json()['call_id']+'/stop').status_code==202
  assert owner.post(path+'/'+response.json()['call_id']+'/stop').status_code==202
  with psycopg.connect(cfg['dsn']) as db:
   assert db.execute("SELECT count(*) FROM coordinator.jobs WHERE incident_id=%s AND kind='OUTBOUND_CALL'",(id,)).fetchone()[0]==0
  owner.post(f'/v2/caregiver/cases/{id}/consent',json={'accepted':False})
  with psycopg.connect(cfg['dsn']) as db:
   assert db.execute("SELECT count(*) FROM coordinator.jobs WHERE incident_id=%s AND kind='STOP_CALL'",(id,)).fetchone()[0]==1


def test_unknown_browser_mint_is_preserved_and_never_automatically_repeated(browser_config,monkeypatch):
 seen=[]
 def mint(*args):seen.append(1);raise DispatchUnknown('Synthetic timeout')
 monkeypatch.setattr('coordinator.browser_voice.Bolna.web_session',mint)
 with TestClient(create_app(browser_config)) as client:
  id=case(client);path=f'/v2/caregiver/cases/{id}/voice-session'
  assert client.post(path,json={'recording_consent':True}).status_code==502
  assert client.post(path,json={'recording_consent':True}).status_code==409
  assert len(seen)==1
  with psycopg.connect(browser_config['dsn']) as db:
   assert db.execute("SELECT state,tool_expires_at<=now() FROM coordinator.calls WHERE incident_id=%s",(id,)).fetchone()==('DISPATCH_UNKNOWN',True)


def test_revocation_during_mint_withholds_browser_credentials(browser_config,monkeypatch):
 cfg=browser_config
 def mint(self,agent,data):
  with psycopg.connect(cfg['dsn']) as db:
   db.execute('UPDATE coordinator.incidents SET consent_active=false,consent_version=consent_version+1 WHERE id=%s',(data['claim911_case_id'],))
  return session(agent)
 monkeypatch.setattr('coordinator.browser_voice.Bolna.web_session',mint)
 with TestClient(create_app(cfg)) as client:
  id=case(client)
  response=client.post(f'/v2/caregiver/cases/{id}/voice-session',json={'recording_consent':True})
  assert response.status_code==409 and 'sip_password' not in response.text
  with psycopg.connect(cfg['dsn']) as db:
   assert db.execute("SELECT count(*) FROM coordinator.jobs WHERE incident_id=%s AND kind='STOP_CALL'",(id,)).fetchone()[0]==1


def test_browser_sessions_fail_closed_when_disabled_or_gateway_unavailable(browser_config,monkeypatch):
 def fail(*args):pytest.fail('Provider must not be reached')
 monkeypatch.setattr('coordinator.browser_voice.Bolna.web_session',fail)
 for disabled in (True,False):
  cfg=browser_config|{'browser_voice_enabled':not disabled}
  monkeypatch.setattr('coordinator.browser_voice.check_gateway',lambda cfg:{'ready':False})
  with TestClient(create_app(cfg)) as client:
   id=case(client)
   assert client.post(f'/v2/caregiver/cases/{id}/voice-session',json={'recording_consent':True}).status_code==503


def test_browser_voice_can_be_enabled_while_phone_dispatch_stays_paused(browser_config):
 assert browser_config['live_calls_enabled'] is False
 config=browser_config|{'outbound_paused':True,'browser_voice_enabled':False}
 from coordinator.browser_voice import configured
 assert configured(config) is False
 config['browser_voice_enabled']=True
 assert configured(config) is True
 assert config['live_calls_enabled'] is False


def test_agent_configuration_drift_fails_closed_before_session_mint(browser_config,monkeypatch):
 monkeypatch.setattr('coordinator.browser_voice.Bolna.agent_configuration_fingerprint',lambda *args:'0'*64)
 monkeypatch.setattr('coordinator.browser_voice.check_gateway',lambda cfg:pytest.fail('Gateway should not be checked after drift'))
 monkeypatch.setattr('coordinator.browser_voice.Bolna.web_session',lambda *args:pytest.fail('No session may be minted after drift'))
 with TestClient(create_app(browser_config)) as client:
  id=case(client)
  assert client.post(f'/v2/caregiver/cases/{id}/voice-session',json={'recording_consent':True}).status_code==409
