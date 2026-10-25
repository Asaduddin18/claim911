"""Complete synthetic workflow composition over existing core and institution gates.

Conversation is a trusted transport adapter, not an LLM verdict. It must archive
its own provenance. Each checkpoint is independently verified after execution.
"""
from datetime import datetime,timezone,timedelta
from uuid import UUID
import time
import threading
from coordinator import callbacks
from coordinator.reasoning import propose
from sandbox import runs

PHASES={
 'caregiver_intake_confirmed':('CAREGIVER_INTAKE','caregiver'),
 'hospital_references_reported':('HOSPITAL_REFERENCE_DISCOVERY','hospital_insurance'),
 'claims_query_discovered':('QUERY_DISCOVERY','tpa'),
 'bill_checked':('BILLING_DOCUMENT','billing'),
 'signed_summary_checked':('RECORDS_DOCUMENT','medical_records'),
 'implant_invoice_checked':('IMPLANT_DOCUMENT','implant_store'),
 'exact_packet_approved':(None,'caregiver'),
 'hospital_dispatch_recorded':('PACKET_SUBMISSION','hospital_insurance'),
 'recipient_receipt_verified':(None,'tpa'),
 'query_and_enhancement_verified':('TPA_QUERY_FOLLOWUP','tpa'),
 'insurer_decision_verified':('INSURER_FOLLOWUP','insurer'),
 'hospital_reconciliation_verified':('DISCHARGE_FOLLOWUP','billing'),
 'caregiver_handoff_completed':('CAREGIVER_COMPLEX_UPDATE','caregiver'),
}
DOCUMENTS={'bill_checked':'itemized_bill','signed_summary_checked':'signed_discharge_summary','implant_invoice_checked':'implant_invoice'}


class CheckpointFailure(RuntimeError):
 def __init__(self,key,reason):
  super().__init__('Independent checkpoint verification failed')
  self.diagnostic={'checkpoint':key,'verification_reason':reason}


class ScenarioExecutor:
 def __init__(self,*,db,run_id,services,verifier,conversation,clock_start):
  self.db=db;self.run_id=str(UUID(str(run_id)));self.services=services;self.verifier=verifier;self.conversation=conversation
  self.clock_start=datetime.fromisoformat(clock_start) if isinstance(clock_start,str) else clock_start
  if self.clock_start.tzinfo is None:raise ValueError('Timezone-aware synthetic clock required')
  self.lease=None;self._heartbeat_stop=None;self._heartbeat_failed=None;self._heartbeat_thread=None

 def authorized(self):
  if not self.lease or (self._heartbeat_failed and self._heartbeat_failed.is_set()):return False
  with self.db() as db:
   r=runs.get(db,self.run_id)
   i=db.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(r['incident_id'],)).fetchone()
  return bool(r['state']=='RUNNING' and r['lease_token']==self.lease['lease_token'] and r['lease_until']>datetime.now(timezone.utc)
   and i['consent_active'] and i['consent_version']==r['consent_version'])

 def _start_heartbeat(self):
  self._heartbeat_stop=threading.Event();self._heartbeat_failed=threading.Event()
  token=self.lease['lease_token']
  def beat():
   while not self._heartbeat_stop.wait(30):
    try:
     with self.db() as db:
      if not runs.renew(db,self.run_id,token):
       self._heartbeat_failed.set();return
    except Exception:
     self._heartbeat_failed.set();return
  self._heartbeat_thread=threading.Thread(target=beat,name='claim911-sandbox-lease',daemon=True)
  self._heartbeat_thread.start()

 def _stop_heartbeat(self):
  if self._heartbeat_stop:self._heartbeat_stop.set()
  if self._heartbeat_thread:self._heartbeat_thread.join(timeout=2)
  self._heartbeat_thread=None

 def _check(self):
  if not self.authorized():raise PermissionError('Current synthetic execution lease required')

 def _pause(self):
  with self.db() as db:
   r=runs.get(db,self.run_id)
   if r['lease_token']!=self.lease['lease_token']:return
   if r['state']=='RUNNING':runs.control(db,self.run_id,'pause')
   if r['state'] in {'RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'}:runs.acknowledge_stop(db,self.run_id,self.lease['lease_token'])

 def _time(self,run):return self.clock_start+timedelta(seconds=run['elapsed_seconds'])

 def step(self):
  started=time.monotonic()
  with self.db() as db:
   run=runs.get(db,self.run_id)
   if run['state']=='COMPLETED':return {'state':'COMPLETED','checkpoint':run['checkpoint']}
   if run['state']=='PAUSED':runs.control(db,self.run_id,'resume')
   elif run['state'] not in {'READY','RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'}:raise RuntimeError('Inspect the current run before continuing; no uncertain execution is restarted')
   # claim classifies an expired worker as uncertain without acquiring a new
   # lease. Commit that classification before raising outside this transaction.
   self.lease=runs.claim(db,self.run_id)
  if not self.lease:raise RuntimeError('The run is not eligible for execution')
  self._start_heartbeat()
  run=self.lease;key=run['manifest']['checkpoints'][run['checkpoint']];purpose,role=PHASES[key]
  callback=None
  try:
   self._check();snapshot=self.services.snapshot()
   if key=='exact_packet_approved':
    self.services.approve_synthetic_packet(snapshot['complex_workflow']['packet_hash'])
   elif key=='recipient_receipt_verified':self.services.receive()
   else:
    operations={};kind=DOCUMENTS.get(key);followup=False
    if kind:
     with self.db() as db:
      previous=db.execute('SELECT id,state FROM coordinator.workflow_callbacks WHERE incident_id=%s AND purpose=%s ORDER BY created_at DESC LIMIT 1',(run['incident_id'],purpose)).fetchone()
     if previous:
      if previous['state']=='ESCALATED':return self._waiting(run,key)
      if previous['state']!='WAITING':raise RuntimeError('Document callback requires reconciliation before another conversation')
      with self.db() as db:callback=callbacks.claim(db,snapshot,now=self._time(run))
      if not callback:return self._waiting(run,key)
      followup=True
     own=self.services.actor(role).execute('read_status')['documents'][0]
     if own['ready']:
      self.services.publish_document(role)
      operations['publish_own_document']=lambda:self.services.publish_document(role)
     elif followup and role=='medical_records':
      def release_and_publish():
       record=self.services.release_summary();uploaded=self.services.publish_document(role)
       return {**record,**uploaded}
      operations['release_signed_summary']=release_and_publish
    elif key=='hospital_dispatch_recorded':
     # A stable run-owned idempotency key survives caller/process restarts.
     operations['dispatch_approved_packet']=lambda:self.services.dispatch(self.run_id)
    elif key=='query_and_enhancement_verified':operations['link_enhancement']=self.services.link_enhancement
    elif key=='insurer_decision_verified':operations['issue_fixed_decision']=self.services.issue_decision
    elif key=='hospital_reconciliation_verified':operations['reconcile']=self.services.reconcile
    result=self.conversation(purpose=purpose,role=role,operations=operations,followup=followup,authorized=self.authorized)
    self._check()
    if not result.get('archived'):raise RuntimeError('A conversation must be archived before its outcome is inspected')
    if kind and kind not in (self.services.snapshot().get('complex_workflow') or {}).get('documents',{}):
     if callback:
      with self.db() as db:callbacks.finish(db,callback['id'],callback['lease_token'],'failed','The owning desk has not released the required evidence.',next_at=self._time(run)+timedelta(seconds=60),now=self._time(run))
     else:
      fresh=self.services.snapshot();proposal=next(p for p in propose(fresh) if p.purpose==purpose)
      with self.db() as db:callbacks.schedule(db,fresh,proposal,self._time(run)+timedelta(seconds=60))
     return self._waiting(run,key)
    if callback:
     with self.db() as db:callbacks.finish(db,callback['id'],callback['lease_token'],'reported','The callback produced a report; checkpoint verification remains separate.',now=self._time(run))
   checked=self.verifier.inspect(key,str(run['incident_id']))
   if not checked['passed']:raise CheckpointFailure(key,checked['reason'])
   with self.db() as db:
    result=runs.complete_checkpoint(db,self.run_id,self.lease['lease_token'],key,checked['evidence_references'],verify=self.verifier)
    runs.event(db,self.run_id,'PHASE_EXECUTED',{'checkpoint':key,'elapsed_seconds':round(time.monotonic()-started,3),'verified':True})
   if result['state']!='COMPLETED':self._pause()
   return {'state':result['state'],'checkpoint':result['checkpoint'],'verified_checkpoint':key}
  except Exception as exc:
   if callback:
    with self.db() as db:
     current=db.execute('SELECT state FROM coordinator.workflow_callbacks WHERE id=%s',(callback['id'],)).fetchone()
     if current['state']=='RUNNING':callbacks.finish(db,callback['id'],callback['lease_token'],'uncertain','Execution interrupted; inspect institution state before another attempt.',now=self._time(run))
   with self.db() as db:runs.event(db,self.run_id,'PHASE_EXECUTION_REVIEW_REQUIRED',{'checkpoint':key,'error_type':type(exc).__name__,'automatic_retry':False})
   with self.db() as db:runs.mark_uncertain(db,self.run_id,self.lease['lease_token'],type(exc).__name__)
   raise
  finally:self._stop_heartbeat()

 def _waiting(self,run,key):
  with self.db() as db:
   callback=db.execute('SELECT id,state FROM coordinator.workflow_callbacks WHERE incident_id=%s AND purpose=%s ORDER BY created_at DESC LIMIT 1',(run['incident_id'],PHASES[key][0])).fetchone()
   if callback and callback['state']=='ESCALATED':
    result=runs.escalate_callback(db,self.run_id,self.lease['lease_token'],callback['id'])
    return {'state':'ESCALATED','checkpoint':result['checkpoint'],'next_action':'human_review'}
  with self.db() as db:runs.event(db,self.run_id,'DOCUMENT_CALLBACK_WAITING',{'checkpoint':key,'receiving_time_preserved':True})
  self._pause()
  return {'state':'WAITING_CALLBACK','checkpoint':run['checkpoint'],'next_action':'advance_synthetic_clock'}
