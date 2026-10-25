"""State/crypto verifier integration. Silent PCM fixtures are not real voice proof."""
import base64,json,os
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
from coordinator.app import create_app
from simulator.app import create_app as institution_app
from sandbox.checkpoints import CheckpointVerifier
from tests.test_coordinator import document
from tests.test_environment import auth


def test_release_verifier_requires_bolna_by_default():
 verifier=CheckpointVerifier(None,None,read_tokens={'hospital':'h','claims':'c','insurer':'i'},
  public_keys={'claims':'c','hospital':'h','insurer':'i'})
 assert verifier.required_audio_provenance=='BOLNA_WEBRTC'
 assert verifier.require_real_audio


@pytest.fixture
def services(request):
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated sandbox runtime required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text())
 sim=json.loads((Path(root)/'sandbox/simulator.json').read_text())
 with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as env:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  if hasattr(request,'param'):
   seeded=env.post('/sandbox/scenarios/'+str(uuid4()),headers=auth(sim,'sandbox_runner'),json={'faults':request.param}).json()
  else:seeded=env.post('/evaluator/complex-runs',headers=auth(sim,'evaluator')).json()
  cid=seeded['case_id']
  id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':cid,'patient_id':seeded['patient_id'],'reference_known':False,'title':'[Integration test] Independent checkpoint verifier'}).json()['incident_id']
  core.post(f'/v1/incidents/{id}/consent',json={'accepted':True,'confirmation':'Explicit synthetic evaluator caregiver permission fixture.'})
  verifier=CheckpointVerifier(core,env,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']},require_real_audio=False)
  yield core,env,sim,id,cid,verifier


def open_call(core,id,purpose):
 r=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':purpose});assert r.status_code==201
 return r.json()


def refresh(core,call):
 h={'X-Call-Token':call['call_token']};assert core.get('/v1/tools/context',headers=h).status_code==200;return h


def finish(core,id,call):
 # Explicit offline archive fixture for verifier mechanics only.
 turns=[{'speaker':speaker,'text':'Offline synthetic verifier audio fixture.','pcm_base64':base64.b64encode(b'\0\0'*160).decode()} for speaker in ['assistant','participant']]
 assert core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':turns}).status_code==200


def update(core,id,purpose,details=None):
 call=open_call(core,id,purpose)
 r=core.post('/v1/tools/workflow',headers=refresh(core,call),json={'operation':'REPORT_UPDATE','details':details or {'summary':'Synthetic institution status report from the authorized desk.'}})
 assert r.status_code==200
 finish(core,id,call)


def prepare_documents(services):
 core,env,sim,id,cid,v=services
 update(core,id,'CAREGIVER_INTAKE')
 assert v.inspect('caregiver_intake_confirmed',id)['passed']
 h=env.get(f'/hospital/complex/{cid}/desks/insurance',headers=auth(sim,'hospital')).json()
 call=open_call(core,id,'HOSPITAL_REFERENCE_DISCOVERY')
 r=core.post('/v1/tools/references',headers=refresh(core,call),json={'admission_id':h['admission_id'],
  'initial_reference':h['references']['preauthorization'],'enhancement_reference':h['references']['enhancement'],
  'final_reference':h['references']['final_request'],'submission_status':'UNKNOWN','summary':'Synthetic hospital confirmed three distinct references.'})
 assert r.status_code==200;finish(core,id,call)
 assert v.inspect('hospital_references_reported',id)['passed']
 q=env.get(f'/claims/complex/{cid}/query',headers=auth(sim,'claims')).json()
 call=open_call(core,id,'QUERY_DISCOVERY')
 r=core.post('/v1/tools/workflow',headers=refresh(core,call),json={'operation':'REPORT_QUERY','details':{
  'query_reference':q['references']['query'],'claim_reference':q['references']['claim'],'admission_id':q['admission_id'],
  'enhancement_reference':q['references']['enhancement'],'received_at':q['received_at'],
  'required_documents':q['required_documents'],'enhancement_linked':q['enhancement_linked']}})
 assert r.status_code==200;finish(core,id,call)
 assert v.inspect('claims_query_discovered',id)['passed']
 assert not v.inspect('signed_summary_checked',id)['passed']
 env.post(f'/hospital/complex/{cid}/documents/summary-signed/release',headers=auth(sim,'hospital'))
 for desk,purpose,checkpoint in [('billing','BILLING_DOCUMENT','bill_checked'),('medical_records','RECORDS_DOCUMENT','signed_summary_checked'),('implant_store','IMPLANT_DOCUMENT','implant_invoice_checked')]:
  record=env.get(f'/hospital/complex/{cid}/desks/{desk}',headers=auth(sim,'hospital')).json()['documents'][0]
  document(core,id,desk+'.json',record,'other')
  call=open_call(core,id,purpose)
  r=core.post('/v1/tools/workflow',headers=refresh(core,call),json={'operation':'REPORT_DOCUMENT','details':{
   'document_kind':record['kind'],'document_reference':record['id'],'ready':True,'summary':'Authorized desk confirms this released document.'}})
  assert r.status_code==200 and r.json()['reported_document_result']=='UPLOADED_DOCUMENT_CHECKED'
  finish(core,id,call)
  checked=v.inspect(checkpoint,id);assert checked['passed'],checked
 return core.get(f'/v1/incidents/{id}/complex').json()


def test_independent_verifier_rejects_missing_receipt_and_confirms_institution_outcomes(services):
 core,env,sim,id,cid,v=services;w=prepare_documents(services)
 base=f'/v1/incidents/{id}/complex'
 assert not v.inspect('exact_packet_approved',id)['passed']
 assert core.post(base+'/approve',json={'accepted':True,'packet_hash':w['packet_hash'],'source':'SYNTHETIC_REHEARSAL_FIXTURE','confirmation':'Explicit synthetic caregiver-role fixture approves only the displayed packet.'}).status_code==200
 assert v.inspect('exact_packet_approved',id)['passed']
 packet=w['packet'];sub=env.post(f'/hospital/complex/{cid}/dispatches',headers={**auth(sim,'hospital'),'Idempotency-Key':str(uuid4())},json={k:packet[k] for k in ['query_id','claim_id','reference','documents']}).json()
 update(core,id,'PACKET_SUBMISSION',{'summary':'Hospital confirms the exact synthetic dispatch.','dispatch_reference':sub['submission_reference']})
 assert v.inspect('hospital_dispatch_recorded',id)['passed']
 assert not v.inspect('recipient_receipt_verified',id)['passed']
 did=document(core,id,'dispatch.json',sub,'dispatch')
 ack=env.post(f'/claims/complex/{cid}/receive/{sub["id"]}',headers=auth(sim,'claims')).json()
 assert core.post(base+'/verify',json={'dispatch_document_id':did,'receipt':ack}).status_code==200
 check=v.inspect('recipient_receipt_verified',id);assert check['passed'],check
 assert not v('recipient_receipt_verified',id,['incident:'+id])
 assert v('recipient_receipt_verified',id,check['evidence_references'])
 resolution=env.post(f'/claims/complex/{cid}/link-enhancement',headers=auth(sim,'claims')).json()
 did=document(core,id,'resolution.json',resolution,'other')
 assert core.post(base+'/query-resolution',json={'document_id':did}).status_code==200
 update(core,id,'TPA_QUERY_FOLLOWUP')
 check=v.inspect('query_and_enhancement_verified',id);assert check['passed'],check
 decision=env.post(f'/insurer/complex/{cid}/decision',headers=auth(sim,'insurer'),json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Fixed synthetic institution decision, not an agent decision.'}).json()
 did=document(core,id,'decision.json',decision,'other');assert core.post(base+'/decision',json={'document_id':did}).status_code==200
 update(core,id,'INSURER_FOLLOWUP')
 check=v.inspect('insurer_decision_verified',id);assert check['passed'],check
 clearance=env.post(f'/hospital/complex/{cid}/reconcile',headers=auth(sim,'hospital')).json()
 did=document(core,id,'clearance.json',clearance,'other');assert core.post(base+'/clearance',json={'document_id':did}).status_code==200
 update(core,id,'DISCHARGE_FOLLOWUP')
 check=v.inspect('hospital_reconciliation_verified',id);assert check['passed'],check
 assert not v.inspect('caregiver_handoff_completed',id)['passed']
 update(core,id,'CAREGIVER_COMPLEX_UPDATE')
 check=v.inspect('caregiver_handoff_completed',id);assert check['passed'],check
 assert v.audit(id)['passed']
 assert v.audit(id)['fixture_audio_allowed']
 v.required_audio_provenance='BOLNA_WEBRTC';v.require_real_audio=True
 assert not v.inspect('caregiver_handoff_completed',id)['passed']
 assert clearance['refund_due_inr']==12000 and clearance['refund_payment_state']=='NOT_VERIFIED'


def test_verifier_rejects_uploaded_document_that_no_longer_matches_owning_desk(services):
 core,env,sim,id,cid,v=services;w=prepare_documents(services)
 # Role-allowed institution state changes cannot be hidden by old core evidence.
 original=env.get
 def revised(path,*args,**kwargs):
  response=original(path,*args,**kwargs)
  if path.endswith('/desks/billing'):
   import httpx
   body=response.json();body['documents'][0]['revision']=3
   return httpx.Response(200,json=body,request=response.request)
  return response
 env.get=revised
 result=v.inspect('bill_checked',id)
 assert not result['passed'] and result['reason']=='DOCUMENT_DIFFERS_FROM_OWNING_DESK'
