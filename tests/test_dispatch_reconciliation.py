import pytest
from fastapi import HTTPException
from sandbox.reconciliation import reconcile_dispatch
from tests.test_scenario_executor import setup_executor
from tests.test_checkpoint_verifier import services
from tests.test_workflow_services import bound


def test_insurer_resume_confirms_existing_verified_decision_without_reissuing(services):
 from sandbox import runs
 from tests.test_checkpoint_verifier import open_call
 executor,db,run,_=setup_executor(services)
 for _ in range(14):
  result=executor.step()
  if result['state']=='WAITING_CALLBACK':
   with db() as conn:runs.advance_clock(conn,run['id'],60)
  if result['checkpoint']==10:break
 core,env,sim,id,cid,_=services
 call=open_call(core,id,'INSURER_FOLLOWUP')
 first=core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).json()
 assert 'keep internal UUIDs in the evidence upload' in first['objective']
 issued=bound(services).issue_decision()
 current=core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).json()
 assert 'already independently verified' in current['objective']
 assert 'Do not ask for another review' in current['objective']
 assert current['workflow']['decision']==issued['envelope']
 assert env.get('/insurer/complex/'+cid+'/review',headers={'Authorization':'Bearer '+sim['tokens']['insurer']}).json()['decision']['envelope']==issued['envelope']


def test_pending_insurer_report_requests_owning_review_without_issuing_decision(services):
 from coordinator.model_tools import ScopedToolModel
 from tests.test_scoped_model_tools import tool
 from sandbox import runs
 executor,db,run,_=setup_executor(services)
 for _ in range(13):
  result=executor.step()
  if result['state']=='WAITING_CALLBACK':
   with db() as conn:runs.advance_clock(conn,run['id'],60)
  if result['checkpoint']==10:break
 core,env,sim,id,cid,_=services
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'INSURER_FOLLOWUP'}).json()
 bridge=ScopedToolModel(core,call['call_token'],lambda *args:tool('claim911_report_update',{'summary':'The reviewer confirms no decision has been issued yet.'}))
 response=bridge.reply([{'role':'user','content':'No final decision has been issued.'}])
 assert 'review the complete packet' in response['text'] and 'if eligible' in response['text']
 assert bridge.audit[-1]['result']['call_complete'] is False
 own=env.get('/insurer/complex/'+cid+'/review',headers={'Authorization':'Bearer '+sim['tokens']['insurer']}).json()
 assert own['decision'] is None and not core.get('/v1/incidents/'+id).json()['complex_workflow'].get('decision')


def test_followup_recovery_rechecks_prior_evidence_without_writing_institution(services):
 from sandbox.reconciliation import reconcile_followup
 from sandbox import runs
 executor,db,run,_=setup_executor(services)
 for _ in range(12):
  result=executor.step()
  if result['state']=='WAITING_CALLBACK':
   with db() as conn:runs.advance_clock(conn,run['id'],60)
  if result['checkpoint']==9:break
 core,env,sim,id,cid,verifier=services
 with db() as conn:conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN' WHERE id=%s",(run['id'],))
 with db() as conn:
  result=reconcile_followup(conn,run['id'],core=core,institutions=env,claims_token=sim['tokens']['claims'],hospital_token=sim['tokens']['hospital'],verifier=verifier)
 assert result['state']=='PAUSED' and not result['checkpoint_advanced'] and not result['institution_write']
 assert result['institution_state']['query_state']=='RESPONSE_RECEIVED' and not result['institution_state']['enhancement_linked']


def test_dispatch_recovery_preserves_submission_and_requires_matching_proof(services):
 executor,db,run,_=setup_executor(services)
 for _ in range(10):
  result=executor.step()
  if result['state']=='WAITING_CALLBACK':
   from sandbox import runs
   with db() as conn:runs.advance_clock(conn,run['id'],60)
  if result['checkpoint']==7:break
 core,env,sim,id,cid,_=services
 with db() as conn:conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN' WHERE id=%s",(run['id'],))
 with db() as conn,pytest.raises(HTTPException):reconcile_dispatch(conn,run['id'],core=core,institutions=env,hospital_token=sim['tokens']['hospital'])
 dispatched=bound(services).dispatch(str(run['id']))
 with db() as conn:
  recovered=reconcile_dispatch(conn,run['id'],core=core,institutions=env,hospital_token=sim['tokens']['hospital'])
  saved=conn.execute('SELECT checkpoint,state FROM coordinator.sandbox_runs WHERE id=%s',(run['id'],)).fetchone()
 assert recovered['dispatch_reference']==dispatched['dispatch_reference'] and not recovered['resubmitted']
 assert saved['checkpoint']==7 and saved['state']=='PAUSED'
 own=env.get('/hospital/complex/'+cid+'/desks/insurance',headers={'Authorization':'Bearer '+sim['tokens']['hospital']}).json()
 assert len(own['dispatches'])==1
 assert recovered['dispatch_id']==own['dispatches'][0]['id']
 from coordinator.model_tools import ScopedToolModel
 from tests.test_scoped_model_tools import tool
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'PACKET_SUBMISSION'}).json()
 context=core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).json()
 assert context['uploaded_dispatch_candidates'][0]['dispatch_reference']==dispatched['dispatch_reference']
 bridge=ScopedToolModel(core,call['call_token'],lambda *args:tool('claim911_report_update',{'summary':'Spoken reference rendering is uncertain.','dispatch_reference':'incorrect spaced reference'}))
 rejected=bridge.reply([{'role':'user','content':'The identifier was not clear.'}])
 assert rejected['report_recorded'] is False and bridge.audit[-1]['result']['recorded'] is False
 bridge.invoke=lambda *args:tool('claim911_report_update',{'summary':'Staff explicitly confirmed the exact uploaded dispatch identifier.','dispatch_reference':dispatched['dispatch_reference']})
 assert bridge.reply([{'role':'user','content':'Yes, that exact reference matches our record.'}])['report_recorded'] is True


def test_saved_claims_report_recovers_same_case_without_repeating_verified_phases(services):
 from sandbox.reconciliation import reconcile_followup
 from tests.test_checkpoint_verifier import open_call,refresh
 from tests.test_workflow_voice import QUERY
 executor,db,run,purposes=setup_executor(services)
 assert executor.step()['checkpoint']==1
 assert executor.step()['checkpoint']==2
 core,env,sim,id,cid,verifier=services
 original=open_call(core,id,'QUERY_DISCOVERY')
 saved=core.post('/v1/tools/workflow',headers=refresh(core,original),json={'operation':'REPORT_QUERY','details':QUERY})
 assert saved.status_code==200
 before=saved.json()
 assert core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{original["call_id"]}/abort').status_code==200
 assert not verifier.inspect('claims_query_discovered',id)['passed']
 with db() as conn:conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN' WHERE id=%s",(run['id'],))
 with db() as conn:
  result=reconcile_followup(conn,run['id'],core=core,institutions=env,claims_token=sim['tokens']['claims'],hospital_token=sim['tokens']['hospital'],verifier=verifier)
  assert result['state']=='PAUSED' and not result['checkpoint_advanced']
 resumed=executor.step()
 assert resumed['checkpoint']==3 and resumed['verified_checkpoint']=='claims_query_discovered'
 after=core.get(f'/v1/incidents/{id}/complex').json()
 assert after['query']==before['query']
 assert after['query_document_id']==before['query_document_id']
 assert after['query_call_id']==original['call_id']
 assert after['query_confirmation_call_id']!=original['call_id']
 assert purposes.count('CAREGIVER_INTAKE')==1 and purposes.count('HOSPITAL_REFERENCE_DISCOVERY')==1
 assert verifier.inspect('claims_query_discovered',id)['passed']
