import json,os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient
from simulator.app import create_app as institution_app
from coordinator.app import create_app as core_app
from experience.app import create_app as product_app
from sandbox import runs
from tests.test_coordinator import document,consent


@pytest.fixture
def profiles():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated local runtime required')
 return tuple(json.loads((Path(root)/'sandbox'/name).read_text()) for name in ['coordinator.json','simulator.json'])


def test_seed_faults_change_only_role_owned_records_and_cannot_change_existing_case(profiles):
 cfg,sim=profiles
 with TestClient(institution_app(sim)) as env:
  route='/sandbox/scenarios/'+str(uuid4());seed={'Authorization':'Bearer '+sim['tokens']['sandbox_runner']}
  assert env.post(route,headers={'Authorization':'Bearer '+sim['tokens']['agent']},json={'faults':[]}).status_code==403
  result=env.post(route,headers=seed,json={'faults':['wrong_admission_invoice','old_bill']})
  assert result.status_code==201
  cid=result.json()['case_id'];headers={'Authorization':'Bearer '+sim['tokens']['hospital']}
  bill=env.get(f'/hospital/complex/{cid}/desks/billing',headers=headers).json()['documents'][0]
  invoice=env.get(f'/hospital/complex/{cid}/desks/implant_store',headers=headers).json()['documents'][0]
  summary=env.get(f'/hospital/complex/{cid}/desks/medical_records',headers=headers).json()['documents'][0]
  assert bill['revision']==1 and bill['amount_inr']==252000
  assert invoice['admission_id']=='ADM-SYN-OTHER'
  assert summary['ready'] and summary['signed_by']=='SYNTHETIC_TREATING_TEAM'
  assert env.post(route,headers=seed,json={'faults':['old_bill','wrong_admission_invoice']}).status_code==201
  assert env.post(route,headers=seed,json={'faults':[]}).status_code==409
  assert env.post('/sandbox/scenarios/'+str(uuid4()),headers=seed,json={'faults':['invented']}).status_code==422


def test_real_document_gate_rejects_injected_old_bill_and_wrong_admission(profiles):
 cfg,sim=profiles
 with TestClient(institution_app(sim)) as env,TestClient(core_app(cfg)) as core:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  cid=str(uuid4());seed={'Authorization':'Bearer '+sim['tokens']['sandbox_runner']}
  assert env.post('/sandbox/scenarios/'+cid,headers=seed,json={'faults':['old_bill','wrong_admission_invoice']}).status_code==201
  id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':cid,'patient_id':'DEMO-PATIENT-84','reference':'FIN63','title':'Synthetic seeded faults'}).json()['incident_id'];consent(core,id)
  call=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'claims','purpose':'Offline fault test','transcript':[{'speaker':'participant','text':'Synthetic document query.'}]}).json()['call_id']
  query=env.get(f'/claims/complex/{cid}/query',headers={'Authorization':'Bearer '+sim['tokens']['claims']}).json()
  did=document(core,id,'query.json',query,'other')
  assert core.post(f'/v1/incidents/{id}/complex/query',json={'call_id':call,'document_id':did}).status_code==201
  for desk,reason in [('billing','Current revised'),('implant_store','different patient or admission')]:
   record=env.get(f'/hospital/complex/{cid}/desks/{desk}',headers={'Authorization':'Bearer '+sim['tokens']['hospital']}).json()['documents'][0]
   did=document(core,id,desk+'.json',record,'other')
   response=core.post(f'/v1/incidents/{id}/complex/documents',json={'document_id':did})
   assert response.status_code==422 and reason in response.json()['detail']
  assert core.get(f'/v1/incidents/{id}/complex').json()['documents']=={}


def test_fault_configuration_is_sandbox_operator_only_and_frozen_after_binding(profiles):
 cfg,sim=profiles
 with TestClient(product_app(cfg)) as client:
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  run=client.post('/v2/sandbox/runs',json={}).json();path=f'/v2/sandbox/runs/{run["id"]}/faults'
  changed=client.post(path,json={'faults':['old_bill']});assert changed.status_code==200 and changed.json()['faults']==['old_bill']
  assert client.post(path,json={'faults':['old_bill','old_bill']}).status_code==422
  from sandbox.preparation import bind
  with TestClient(core_app(cfg)) as core,TestClient(institution_app(sim)) as institutions:
   core.headers['Authorization']='Bearer '+cfg['operator_token']
   with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
    bound=bind(conn,run['id'],core=core,institutions=institutions,seed_token=sim['tokens']['sandbox_runner'])
    assert bound['state']=='READY'
   bill=institutions.get('/hospital/complex/'+run['id']+'/desks/billing',headers={'Authorization':'Bearer '+sim['tokens']['hospital']}).json()['documents'][0]
   assert bill['revision']==1
  assert client.post(path,json={'faults':[]}).status_code==409
 with TestClient(product_app(cfg)) as stranger:
  stranger.post('/v2/sessions',json={'role':'caregiver'})
  assert stranger.post(path,json={'faults':[]}).status_code==401


def test_concurrent_seed_attempts_cannot_acknowledge_different_conditions(profiles):
 from concurrent.futures import ThreadPoolExecutor
 _,sim=profiles
 with TestClient(institution_app(sim)) as env:
  cid=str(uuid4());headers={'Authorization':'Bearer '+sim['tokens']['sandbox_runner']}
  def seed(faults):return env.post('/sandbox/scenarios/'+cid,headers=headers,json={'faults':faults}).status_code
  with ThreadPoolExecutor(max_workers=2) as executor:
   results=list(executor.map(seed,[['old_bill'],['wrong_admission_invoice']]))
  assert sorted(results)==[201,409]


@pytest.mark.parametrize('fault',['withheld_receipt','pending_insurer','denied_insurer'])
def test_institution_outcome_faults_cannot_be_replaced_by_agent_success(profiles,fault):
 from sandbox.actors import InstitutionActor
 import httpx
 cfg,sim=profiles
 with TestClient(institution_app(sim)) as env:
  cid=str(uuid4());seed={'Authorization':'Bearer '+sim['tokens']['sandbox_runner']}
  assert env.post('/sandbox/scenarios/'+cid,headers=seed,json={'faults':[fault]}).status_code==201
  hospital={'Authorization':'Bearer '+sim['tokens']['hospital']};claims={'Authorization':'Bearer '+sim['tokens']['claims']};insurer={'Authorization':'Bearer '+sim['tokens']['insurer']}
  response=env.post(f'/hospital/complex/{cid}/dispatches',headers=hospital|{'Idempotency-Key':str(uuid4())},json={'query_id':'QRY25','claim_id':'CLM86','reference':'FIN63','documents':['bill-v2','summary-signed','implant-invoice']})
  assert response.status_code==201;sub=response.json()['id']
  receipt=env.post(f'/claims/complex/{cid}/receive/{sub}',headers=claims)
  if fault=='withheld_receipt':
   assert receipt.status_code==409
   query=env.get(f'/claims/complex/{cid}/query',headers=claims).json()
   assert query['receipts']==[] and query['query_state']=='OPEN'
   assert env.post(f'/claims/complex/{cid}/link-enhancement',headers=claims).status_code==409
   return
  assert receipt.status_code==200
  assert env.post(f'/claims/complex/{cid}/link-enhancement',headers=claims).status_code==200
  actor=InstitutionActor('insurer',cid,env,sim['tokens']['insurer'])
  if fault=='pending_insurer':
   with pytest.raises(httpx.HTTPStatusError):actor.execute('issue_fixed_decision')
   assert env.get(f'/insurer/complex/{cid}/review',headers=insurer).json()['decision'] is None
   assert env.post(f'/hospital/complex/{cid}/reconcile',headers=hospital).status_code==409
  else:
   decision=actor.execute('issue_fixed_decision')
   assert decision['outcome']=='DENIED' and decision['payable_inr']==0
   assert actor.execute('issue_fixed_decision')['id']==decision['id']
   assert env.post(f'/insurer/complex/{cid}/decision',headers=insurer,json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Attempt to replace fixed denial'}).status_code==409
   reconciliation=env.post(f'/hospital/complex/{cid}/reconcile',headers=hospital).json()
   assert reconciliation['discharge_clearance']=='BALANCE_PENDING'
   assert reconciliation['balance_due_inr']==218000 and reconciliation['refund_payment_state']=='NOT_VERIFIED'


def test_contradictory_insurer_faults_are_rejected_before_case_creation(profiles):
 _,sim=profiles
 with TestClient(institution_app(sim)) as env:
  response=env.post('/sandbox/scenarios/'+str(uuid4()),headers={'Authorization':'Bearer '+sim['tokens']['sandbox_runner']},json={'faults':['pending_insurer','denied_insurer']})
  assert response.status_code==422
