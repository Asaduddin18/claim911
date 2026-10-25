import json,os,secrets
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient
from coordinator.app import create_app
from simulator.app import create_app as simulator
from sandbox.preparation import bind
from sandbox import runs


def test_scoped_preparation_is_idempotent_and_exposes_no_hidden_answers():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated runtime required')
 root=Path(root);cfg=json.loads((root/'sandbox/coordinator.json').read_text());sim=json.loads((root/'sandbox/simulator.json').read_text())
 token=secrets.token_urlsafe(32);sim['tokens']['sandbox_runner']=token
 with TestClient(create_app(cfg)) as core,TestClient(simulator(sim)) as institutions:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   runs.initialize(conn,environment='sandbox');run=runs.create(conn,origin='USER_PREPARED')
   bound=bind(conn,run['id'],core=core,institutions=institutions,seed_token=token)
   again=bind(conn,run['id'],core=core,institutions=institutions,seed_token=token)
   assert bound['state']=='READY' and bound['incident_id']==again['incident_id']
  route='/sandbox/scenarios/'+str(run['id'])
  assert institutions.post(route,headers={'Authorization':'Bearer '+sim['tokens']['agent']}).status_code==403
  public=institutions.post(route,headers={'Authorization':'Bearer '+token}).json()
  assert set(public)=={'case_id','patient_id','synthetic','execution_mode'}
  assert public['case_id']==str(run['id'])
 with TestClient(simulator({**sim,'environment':'operational'})) as operational:
  assert operational.post(route,headers={'Authorization':'Bearer '+token}).status_code==404
