"""Real institution/coordinator integration using explicitly offline call fixtures.

These checks prove scoped operations and evidence handling, not audio or LLM quality.
"""
import pytest
from sandbox.workflow_services import WorkflowServices
from tests.test_checkpoint_verifier import services,prepare_documents,update


def bound(services,authorized=lambda:True):
 core,env,sim,id,cid,_=services
 return WorkflowServices(core,env,incident_id=id,case_id=cid,tokens=sim['tokens'],authorized=authorized)


def test_services_finish_institution_workflow_without_conflating_dispatch_receipt_or_payment(services):
 core,env,sim,id,cid,verifier=services
 w=prepare_documents(services);executor=bound(services)
 with pytest.raises(PermissionError):executor.dispatch('5b42af61-dd0f-4acc-a7f3-e5c4acf4ceac')
 with pytest.raises(PermissionError):executor.approve_synthetic_packet('f'*64)
 executor.approve_synthetic_packet(w['packet_hash'])
 result=executor.dispatch('5b42af61-dd0f-4acc-a7f3-e5c4acf4ceac')
 assert not result['receipt_verified'] and not core.get(f'/v1/incidents/{id}/complex').json().get('receipt')
 again=executor.dispatch('5b42af61-dd0f-4acc-a7f3-e5c4acf4ceac')
 assert again['dispatch_reference']==result['dispatch_reference']
 update(core,id,'PACKET_SUBMISSION',{'summary':'Synthetic hospital confirms dispatch.','dispatch_reference':result['dispatch_reference']})
 assert verifier.inspect('hospital_dispatch_recorded',id)['passed']
 executor.receive();assert verifier.inspect('recipient_receipt_verified',id)['passed']
 executor.link_enhancement();update(core,id,'TPA_QUERY_FOLLOWUP')
 executor.issue_decision();update(core,id,'INSURER_FOLLOWUP')
 outcome=executor.reconcile();update(core,id,'DISCHARGE_FOLLOWUP')
 update(core,id,'CAREGIVER_COMPLEX_UPDATE')
 assert verifier.audit(id)['passed'] and verifier.audit(id)['fixture_audio_allowed']
 assert outcome['refund_due_inr']==12000 and outcome['refund_payment_state']=='NOT_VERIFIED'
 assert core.get(f'/v1/incidents/{id}').json()['incident']['state']=='DISCHARGE_CLEARED'


def test_revocation_blocks_publication_and_institution_side_effect(services):
 core,env,sim,id,cid,_=services;active=[True]
 executor=bound(services,lambda:active[0]);active[0]=False
 with pytest.raises(PermissionError):executor.release_summary()
 with pytest.raises(PermissionError):executor.publish_document('billing')
 own=env.get(f'/hospital/complex/{cid}/desks/medical_records',headers={'Authorization':'Bearer '+sim['tokens']['hospital']}).json()
 assert not own['documents'][0]['ready']


def test_document_owner_and_service_environment_are_enforced(services):
 core,env,sim,id,cid,_=services;executor=bound(services)
 with pytest.raises(PermissionError):executor.publish_document('hospital_insurance')
 with pytest.raises(ValueError):executor.publish_document('medical_records')
 released=executor.release_summary();assert released['signed_by']=='SYNTHETIC_TREATING_TEAM'
 published=executor.publish_document('medical_records');assert published['document_reference']==released['id']
 original=core.get
 def wrong_environment(path,*args,**kwargs):
  import httpx
  if path=='/health':return httpx.Response(200,json={'environment':'operational'},request=httpx.Request('GET','http://testserver/health'))
  return original(path,*args,**kwargs)
 core.get=wrong_environment
 with pytest.raises(PermissionError):bound(services)
