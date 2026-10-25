"""Full executor integration with offline report/audio fixtures, not voice proof."""
import json,os
from datetime import datetime
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import pytest
from sandbox import runs
from sandbox.executor import ScenarioExecutor
from sandbox.workflow_services import WorkflowServices
from tests.test_checkpoint_verifier import services,open_call,refresh,finish


def setup_executor(services):
 core,env,sim,id,cid,verifier=services
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'sandbox/coordinator.json').read_text())
 def db():return psycopg.connect(cfg['dsn'],row_factory=dict_row)
 with db() as conn:
  runs.initialize(conn,environment='sandbox');run=runs.create(conn,origin='VERIFICATION_FIXTURE')
  runs.attach_case(conn,run['id'],incident_id=id,institution_case_id=cid,provider_configuration={'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'})
 holder={}
 institution=WorkflowServices(core,env,incident_id=id,case_id=cid,tokens=sim['tokens'],authorized=lambda:bool(holder) and holder['executor'].authorized())
 purposes=[]
 def conversation(*,purpose,role,operations,followup,authorized):
  assert authorized();purposes.append(purpose);call=open_call(core,id,purpose)
  details={'summary':'Offline synthetic participant report for executor integration only.'};operation='REPORT_UPDATE'
  if purpose=='HOSPITAL_REFERENCE_DISCOVERY':
   own=institution.actor(role).execute('read_status')
   result=core.post('/v1/tools/references',headers=refresh(core,call),json={'admission_id':own['admission_id'],'initial_reference':own['references']['preauthorization'],
    'enhancement_reference':own['references']['enhancement'],'final_reference':own['references']['final_request'],'submission_status':'UNKNOWN','summary':'Synthetic hospital references confirmed.'})
  else:
   if purpose=='QUERY_DISCOVERY':
    own=institution.actor(role).execute('read_status');operation='REPORT_QUERY'
    details={'query_reference':own['references']['query'],'claim_reference':own['references']['claim'],'admission_id':own['admission_id'],
     'enhancement_reference':own['references']['enhancement'],'received_at':own['received_at'],'required_documents':own['required_documents'],'enhancement_linked':own['enhancement_linked']}
   elif purpose in {'BILLING_DOCUMENT','RECORDS_DOCUMENT','IMPLANT_DOCUMENT'}:
    if followup and 'release_signed_summary' in operations:operations['release_signed_summary']()
    own=institution.actor(role).execute('read_status')['documents'][0]
    if own['ready']:
     operation='REPORT_DOCUMENT';details={'document_kind':own['kind'],'document_reference':own['id'],'ready':True,'summary':'Owning desk confirms its released uploaded document.'}
    else:details={'summary':'The summary is awaiting the treating team signature; please follow up.'}
   elif purpose=='PACKET_SUBMISSION':details['dispatch_reference']=operations['dispatch_approved_packet']()['dispatch_reference']
   elif purpose=='TPA_QUERY_FOLLOWUP':operations['link_enhancement']()
   elif purpose=='INSURER_FOLLOWUP':operations['issue_fixed_decision']()
   elif purpose=='DISCHARGE_FOLLOWUP':operations['reconcile']()
   result=core.post('/v1/tools/workflow',headers=refresh(core,call),json={'operation':operation,'details':details})
  assert result.status_code==200
  finish(core,id,call)
  return {'archived':True,'provenance':'OFFLINE_FIXTURE'}
 executor=ScenarioExecutor(db=db,run_id=run['id'],services=institution,verifier=verifier,conversation=conversation,clock_start='2026-10-23T11:40:00+05:30')
 holder['executor']=executor
 return executor,db,run,purposes


def test_full_executor_recovers_unsigned_summary_preserves_query_clock_and_verifies_all_gates(services):
 executor,db,run,purposes=setup_executor(services)
 waiting=[]
 for _ in range(16):
  result=executor.step()
  if result['state']=='WAITING_CALLBACK':
   waiting.append(result)
   with db() as conn:runs.advance_clock(conn,run['id'],60)
  if result['state']=='COMPLETED':break
 assert result['state']=='COMPLETED' and result['checkpoint']==13
 assert len(waiting)==1 and purposes.count('RECORDS_DOCUMENT')==2
 core,_,_,id,_,verifier=services
 assert verifier.audit(id)['passed'] and verifier.audit(id)['fixture_audio_allowed']
 with db() as conn:
  callback=conn.execute('SELECT state,attempts,original_received_at FROM coordinator.workflow_callbacks WHERE incident_id=%s',(id,)).fetchone()
 assert callback['state']=='REPORTED' and callback['attempts']==1
 assert callback['original_received_at']==datetime.fromisoformat('2026-10-23T10:20:00+05:30')
 assert core.get('/v1/incidents/'+id).json()['incident']['state']=='DISCHARGE_CLEARED'


def test_uncertain_run_is_not_restarted_by_executor(services):
 executor,db,run,_=setup_executor(services)
 with db() as conn:conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN' WHERE id=%s",(run['id'],))
 with pytest.raises(RuntimeError):executor.step()
 assert not executor.authorized()


def test_scheduled_records_call_receives_followup_in_primary_objective(services):
 from coordinator import callbacks
 from datetime import timedelta
 executor,db,run,_=setup_executor(services)
 for _ in range(5):result=executor.step()
 assert result['state']=='WAITING_CALLBACK'
 core,_,_,id,_,_=services
 with db() as conn:
  runs.advance_clock(conn,run['id'],60)
  task=callbacks.claim(conn,core.get('/v1/incidents/'+id).json(),now=executor.clock_start+timedelta(seconds=60))
 assert task
 call=open_call(core,id,'RECORDS_DOCUMENT')
 context=core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).json()
 assert context['objective'].startswith('SCHEDULED MEDICAL-RECORDS FOLLOW-UP')
 assert context['workflow']['active_followup']['attempt']==1


def test_reviewed_callback_replacement_preserves_attempt_history_and_current_policy(services):
 from coordinator import callbacks
 from datetime import timedelta
 from fastapi import HTTPException
 executor,db,run,_=setup_executor(services)
 for _ in range(5):result=executor.step()
 core,_,_,id,_,_=services
 snapshot=core.get('/v1/incidents/'+id).json()
 with db() as conn:
  task=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE incident_id=%s',(id,)).fetchone()
  with pytest.raises(HTTPException):callbacks.reschedule_after_review(conn,snapshot,task['id'],'Reviewed missing call context and verified no institution action.')
  conn.execute("UPDATE coordinator.workflow_callbacks SET state='ESCALATED',attempts=2 WHERE id=%s",(task['id'],))
  replacement=callbacks.reschedule_after_review(conn,snapshot,task['id'],'Reviewed missing call context and verified no institution action.',now=executor.clock_start+timedelta(seconds=60))
  old=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s',(task['id'],)).fetchone()
  assert old['attempts']==2 and old['state']=='SUPERSEDED'
  assert replacement['attempts']==0 and replacement['id']!=task['id']
  assert replacement['original_received_at']==task['original_received_at']
  assert replacement['target_at']==task['target_at']


def test_reconcile_archived_checkpoint_does_not_repeat_a_completed_conversation(services):
 from sandbox.reconciliation import reconcile_verified_checkpoint
 executor,db,run,purposes=setup_executor(services);original=executor.conversation
 def interrupted_after_archive(**kwargs):
  original(**kwargs)
  raise RuntimeError('Synthetic export interruption after actual archive fixture')
 executor.conversation=interrupted_after_archive
 with pytest.raises(RuntimeError):executor.step()
 with db() as conn:result=reconcile_verified_checkpoint(conn,run['id'],verifier=executor.verifier)
 assert result['checkpoint']==1 and result['new_provider_sessions']==0
 assert purposes==['CAREGIVER_INTAKE']
 executor.conversation=original;executor.step()
 assert purposes==['CAREGIVER_INTAKE','HOSPITAL_REFERENCE_DISCOVERY']


def test_reconciliation_cannot_advance_an_uncertain_checkpoint_without_its_evidence(services):
 from sandbox.reconciliation import reconcile_verified_checkpoint
 from fastapi import HTTPException
 executor,db,run,purposes=setup_executor(services)
 with db() as conn:conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN' WHERE id=%s",(run['id'],))
 with db() as conn,pytest.raises(HTTPException):reconcile_verified_checkpoint(conn,run['id'],verifier=executor.verifier)
 with db() as conn:assert runs.get(conn,run['id'])['checkpoint']==0
 assert not purposes


def test_expired_worker_is_persisted_as_uncertain_without_restart(services):
 executor,db,run,purposes=setup_executor(services)
 with db() as conn:
  runs.claim(conn,run['id'])
  conn.execute("UPDATE coordinator.sandbox_runs SET lease_until=now()-interval '1 second' WHERE id=%s",(run['id'],))
 with pytest.raises(RuntimeError):executor.step()
 with db() as conn:
  current=runs.get(conn,run['id'])
 assert current['state']=='UNCERTAIN' and current['lease_token'] is None
 assert purposes==[] and not executor.authorized()


def test_sandbox_queue_deduplicates_and_rejects_uncertain_execution(services):
 executor,db,run,_=setup_executor(services)
 with db() as conn:
  first=runs.enqueue(conn,run['id']);second=runs.enqueue(conn,run['id'])
  assert first['new_job'] and not second['new_job'] and first['job_id']==second['job_id']
  job=conn.execute('SELECT kind,payload FROM coordinator.jobs WHERE id=%s',(first['job_id'],)).fetchone()
  assert job['kind']=='SANDBOX_PHASE' and job['payload']['transport']=='PIPECAT_STDIO'
  conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN' WHERE id=%s",(run['id'],))
 from fastapi import HTTPException
 with db() as conn,pytest.raises(HTTPException):runs.enqueue(conn,run['id'])


def test_sandbox_worker_checks_authoritative_progress_and_never_repeats_job(services):
 from coordinator.worker import sandbox_once
 executor,db,run,purposes=setup_executor(services)
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'sandbox/coordinator.json').read_text())
 with db() as conn:job=runs.enqueue(conn,run['id'])
 assert sandbox_once(cfg,lambda id:executor.step(),job['job_id'])
 assert not sandbox_once(cfg,lambda id:pytest.fail('Completed job repeated'),job['job_id'])
 with db() as conn:
  saved=conn.execute('SELECT state FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()
  queued=conn.execute("SELECT count(*) AS n FROM coordinator.jobs WHERE kind='SANDBOX_PHASE' AND incident_id=%s AND state='QUEUED'",(executor.services.incident_id,)).fetchone()
 assert saved['state']=='DONE' and queued['n']==1 and purposes==['CAREGIVER_INTAKE']


def test_sandbox_worker_does_not_trust_success_return_without_evidence(services):
 from coordinator.worker import sandbox_once
 executor,db,run,_=setup_executor(services)
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'sandbox/coordinator.json').read_text())
 with db() as conn:job=runs.enqueue(conn,run['id'])
 assert sandbox_once(cfg,lambda id:{'success':True},job['job_id'])
 with db() as conn:saved=conn.execute('SELECT state FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()
 assert saved['state']=='DISPATCH_UNKNOWN'
 with pytest.raises(PermissionError):sandbox_once({**cfg,'environment':'operational'},lambda id:None)


def test_worker_accelerates_only_synthetic_callback_clock_and_completes_fixture(services):
 from coordinator.worker import sandbox_once
 executor,db,run,_=setup_executor(services)
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'sandbox/coordinator.json').read_text())|{'sandbox_accelerate_callbacks':True}
 with db() as conn:job=runs.enqueue(conn,run['id'])
 for _ in range(16):
  assert sandbox_once(cfg,lambda id:executor.step(),job['job_id'])
  with db() as conn:
   current=runs.get(conn,run['id'])
   if current['state']=='COMPLETED':break
   queued=conn.execute("SELECT id FROM coordinator.jobs WHERE kind='SANDBOX_PHASE' AND payload->>'run_id'=%s AND state='QUEUED' ORDER BY created_at LIMIT 1",(str(run['id']),)).fetchone()
  assert queued;job={'job_id':str(queued['id'])}
 assert current['checkpoint']==13 and current['elapsed_seconds']==60
 with db() as conn:
  callback=conn.execute('SELECT state,attempts,original_received_at FROM coordinator.workflow_callbacks WHERE incident_id=%s',(executor.services.incident_id,)).fetchone()
 assert callback['state']=='REPORTED' and callback['attempts']==1
 assert callback['original_received_at']==datetime.fromisoformat('2026-10-23T10:20:00+05:30')


def test_disabled_or_suspended_worker_leaves_real_queue_untouched(services,monkeypatch):
 from coordinator.worker import sandbox_once
 executor,db,run,_=setup_executor(services)
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'sandbox/coordinator.json').read_text())
 with db() as conn:
  # Real-origin routing fixture only. No provider or actual voice evidence.
  conn.execute("UPDATE coordinator.sandbox_runs SET origin='USER_PREPARED' WHERE id=%s",(run['id'],))
  job=runs.enqueue(conn,run['id'])
 paused={'allowed':False,'code':'PAID_TESTING_PAUSED','message':'Paid testing is paused.'}
 monkeypatch.setattr('sandbox.spend.testing_readiness',lambda conn,now=None:paused)
 for enabled in [False,True]:
  assert not sandbox_once({**cfg,'sandbox_execution_enabled':enabled},lambda id:pytest.fail('Paused/disabled worker cannot launch a phase'),job['job_id'])
  with db() as conn:
   current=conn.execute('SELECT state,attempts,lease_until FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()
   assert current=={'state':'QUEUED','attempts':0,'lease_until':None}
   assert runs.get(conn,run['id'])['state']=='READY'


def test_unreleased_document_escalates_after_two_callbacks_without_another_job(services):
 from coordinator.worker import sandbox_once
 executor,db,run,purposes=setup_executor(services)
 original=executor.conversation
 def unavailable(**kwargs):
  if kwargs['purpose']=='RECORDS_DOCUMENT':kwargs={**kwargs,'operations':{}}
  return original(**kwargs)
 executor.conversation=unavailable
 cfg=json.loads((Path(os.environ['CLAIM911_PROFILE_ROOT'])/'sandbox/coordinator.json').read_text())|{'sandbox_accelerate_callbacks':True}
 with db() as conn:job=runs.enqueue(conn,run['id'])
 for _ in range(12):
  assert sandbox_once(cfg,lambda id:executor.step(),job['job_id'])
  with db() as conn:
   current=runs.get(conn,run['id'])
   if current['state']=='ESCALATED':break
   queued=conn.execute("SELECT id FROM coordinator.jobs WHERE kind='SANDBOX_PHASE' AND payload->>'run_id'=%s AND state='QUEUED' ORDER BY created_at LIMIT 1",(str(run['id']),)).fetchone()
  assert queued;job={'job_id':str(queued['id'])}
 assert current['state']=='ESCALATED' and current['checkpoint']==4 and current['lease_token'] is None
 assert purposes.count('RECORDS_DOCUMENT')==3
 with db() as conn:
  callback=conn.execute('SELECT state,attempts,original_received_at FROM coordinator.workflow_callbacks WHERE incident_id=%s',(executor.services.incident_id,)).fetchone()
  assert callback['state']=='ESCALATED' and callback['attempts']==2
  assert callback['original_received_at']==datetime.fromisoformat('2026-10-23T10:20:00+05:30')
  assert conn.execute("SELECT state FROM coordinator.jobs WHERE id=%s",(job['job_id'],)).fetchone()['state']=='ESCALATED'
  assert conn.execute("SELECT count(*) AS n FROM coordinator.jobs WHERE payload->>'run_id'=%s AND state='QUEUED'",(str(run['id']),)).fetchone()['n']==0
 with pytest.raises(RuntimeError):executor.step()


@pytest.mark.parametrize('services',[['desk_unavailable']],indirect=True)
def test_unavailable_billing_never_gets_clinical_release_and_escalates(services):
 executor,db,run,purposes=setup_executor(services)
 executor.services.release_summary=lambda:pytest.fail('Billing callback cannot release a clinical summary')
 for _ in range(12):
  result=executor.step()
  if result['state']=='ESCALATED':break
  if result['state']=='WAITING_CALLBACK':
   with db() as conn:runs.advance_clock(conn,run['id'],60)
 assert result['state']=='ESCALATED' and result['checkpoint']==3
 assert purposes.count('BILLING_DOCUMENT')==3 and 'RECORDS_DOCUMENT' not in purposes
 with db() as conn:
  callback=conn.execute('SELECT purpose,state,attempts FROM coordinator.workflow_callbacks WHERE incident_id=%s',(executor.services.incident_id,)).fetchone()
  assert callback['purpose']=='BILLING_DOCUMENT' and callback['state']=='ESCALATED' and callback['attempts']==2
