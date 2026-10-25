"""Simulated participants cannot read other desks or bypass disclosure gates."""
import json,os
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from simulator.app import create_app
from sandbox.actors import InstitutionActor,initial_knowledge,scenario_manifest

@pytest.fixture
def sandbox_environment():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated sandbox runtime required')
 cfg=json.loads((Path(root)/'sandbox/simulator.json').read_text())
 with TestClient(create_app(cfg)) as client:
  response=client.post('/evaluator/complex-runs',headers={'Authorization':'Bearer '+cfg['tokens']['evaluator']});assert response.status_code==201
  yield client,cfg,response.json()['case_id']


def test_role_private_knowledge_and_manifest_do_not_leak_hidden_claims_query():
 m=scenario_manifest();assert m['version']==3 and m['environment']=='sandbox'
 assert len(m['participants'])==7
 caregiver=json.dumps(initial_knowledge('caregiver'))
 assert 'QRY25' not in caregiver and '230000' not in caregiver
 assert 'query QRY25' in json.dumps(initial_knowledge('tpa'))
 assert 'QRY25' not in json.dumps(initial_knowledge('billing'))
 with pytest.raises(ValueError):initial_knowledge('administrator')


def test_billing_cannot_release_clinical_document_or_read_other_desks(sandbox_environment):
 client,cfg,cid=sandbox_environment
 billing=InstitutionActor('billing',cid,client,cfg['tokens']['hospital'])
 view=billing.execute('read_status');assert all(d['owner']=='billing' for d in view['documents'])
 assert 'query_state' not in view and 'references' not in view
 with pytest.raises(PermissionError):billing.execute('release_signed_summary')
 with pytest.raises(PermissionError):billing.execute('/claims/complex/'+cid+'/query')
 hospital=InstitutionActor('hospital_insurance',cid,client,cfg['tokens']['hospital'])
 with pytest.raises(PermissionError):hospital.execute('dispatch_approved_packet',{'idempotency_key':str(uuid4())})


def test_insurer_can_read_its_gate_but_cannot_bypass_query_or_issue_as_tpa(sandbox_environment):
 import httpx
 client,cfg,cid=sandbox_environment
 insurer=InstitutionActor('insurer',cid,client,cfg['tokens']['insurer'])
 view=insurer.execute('read_status');assert view['query_state']=='OPEN' and not view['enhancement_linked']
 assert view['references']['final_request']=='FIN63' and view['references']['claim']=='CLM86'
 assert 'receipts' not in view and 'required_documents' not in view
 with pytest.raises(httpx.HTTPStatusError):insurer.execute('issue_fixed_decision')
 tpa=InstitutionActor('tpa',cid,client,cfg['tokens']['claims'])
 with pytest.raises(PermissionError):tpa.execute('issue_fixed_decision')
 assert client.get(f'/insurer/complex/{cid}/review',headers={'Authorization':'Bearer '+cfg['tokens']['hospital']}).status_code==403


def test_broker_passes_only_case_bound_desk_operations_to_synthetic_institutions(sandbox_environment):
 from sandbox.broker import CapabilityRegistry,create_broker
 client,cfg,cid=sandbox_environment
 calls=[]
 def execute(case,role,operation,arguments):
  calls.append((case,role,operation))
  token=cfg['tokens']['hospital']
  return InstitutionActor(role,case,client,token).execute(operation,arguments)
 registry=CapabilityRegistry(execute)
 run=str(uuid4());token=registry.issue(run,cid,'medical_records')
 gateway=TestClient(create_broker(registry,environment='sandbox'))
 headers={'Authorization':'Bearer '+token}
 body={'run_id':run,'case_id':cid,'role':'medical_records','operation':'read_status','request_id':str(uuid4())}
 response=gateway.post('/tools',json=body,headers=headers)
 assert response.status_code==200
 assert all(d['owner']=='medical_records' for d in response.json()['documents'])
 release=body|{'operation':'release_signed_summary','request_id':str(uuid4())}
 assert gateway.post('/tools',json=release,headers=headers).status_code==200
 assert gateway.post('/tools',json=release,headers=headers).status_code==200
 assert len(calls)==2
 assert gateway.post('/tools',json=body|{'case_id':str(uuid4())},headers=headers).status_code==403
 registry.revoke_run(run)
 assert gateway.post('/tools',json=body,headers=headers).status_code==401
