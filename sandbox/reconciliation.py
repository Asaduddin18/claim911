"""Narrow recovery after an interrupted dispatch conversation, without resubmission."""
import json
from fastapi import HTTPException
from sandbox import runs


def reconcile_verified_checkpoint(conn,run_id,*,verifier):
 """Advance only already archived, independently verified evidence after a stop.

 No provider session, report mutation or institution action is performed.
 The original failure event remains in the run history.
 """
 run=runs.get(conn,run_id,True)
 if run['state']!='UNCERTAIN' or run['lease_token'] is not None:
  raise HTTPException(409,'A stopped uncertain run is required')
 if conn.execute("SELECT 1 FROM coordinator.calls WHERE incident_id=%s AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER') LIMIT 1",(run['incident_id'],)).fetchone():
  raise HTTPException(409,'Reconcile active conversations first')
 key=run['manifest']['checkpoints'][run['checkpoint']]
 checked=verifier.inspect(key,str(run['incident_id']))
 if not checked['passed']:raise HTTPException(409,'The current checkpoint still lacks verified evidence')
 conn.execute("UPDATE coordinator.sandbox_runs SET state='PAUSED',updated_at=now() WHERE id=%s",(run_id,))
 runs.event(conn,run_id,'CAPTURED_CHECKPOINT_RECONCILED',{'checkpoint':key,'new_provider_session':False,'original_failure_preserved':True})
 runs.control(conn,run_id,'resume');lease=runs.claim(conn,run_id)
 result=runs.complete_checkpoint(conn,run_id,lease['lease_token'],key,checked['evidence_references'],verify=verifier)
 if result['state']!='COMPLETED':
  runs.control(conn,run_id,'pause');runs.acknowledge_stop(conn,run_id,lease['lease_token'])
 return {'checkpoint':result['checkpoint'],'verified_checkpoint':key,'new_provider_sessions':0}


def reconcile_followup(conn,run_id,*,core,institutions,claims_token,hospital_token,verifier):
 run=runs.get(conn,run_id,True)
 phases={'claims_query_discovered','query_and_enhancement_verified','insurer_decision_verified','hospital_reconciliation_verified','caregiver_handoff_completed'}
 if run['state']!='UNCERTAIN' or run['manifest']['checkpoints'][run['checkpoint']] not in phases:
  raise HTTPException(409,'An uncertain institution follow-up is required')
 for client in [core,institutions]:
  response=client.get('/health');response.raise_for_status()
  if response.json().get('environment')!='sandbox':raise PermissionError('Sandbox services required')
 if conn.execute("SELECT 1 FROM coordinator.calls WHERE incident_id=%s AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER') LIMIT 1",(run['incident_id'],)).fetchone():
  raise HTTPException(409,'An active conversation requires reconciliation first')
 response=core.get('/v1/incidents/'+str(run['incident_id']));response.raise_for_status();snapshot=response.json();incident=snapshot['incident']
 if not incident['is_test'] or not incident['consent_active'] or incident['consent_version']!=run['consent_version']:
  raise HTTPException(409,'Current synthetic consent required')
 for key in run['manifest']['checkpoints'][:run['checkpoint']]:
  if not verifier.inspect(key,str(run['incident_id']))['passed']:raise HTTPException(409,'Earlier evidence no longer verifies')
 cid=str(run['institution_case_id'])
 q=institutions.get('/claims/complex/'+cid+'/query',headers={'Authorization':'Bearer '+claims_token});q.raise_for_status();q=q.json()
 h=institutions.get('/hospital/complex/'+cid+'/desks/insurance',headers={'Authorization':'Bearer '+hospital_token});h.raise_for_status();h=h.json()
 if q['patient_id']!=incident['patient_id'] or h['patient_id']!=incident['patient_id']:raise HTTPException(409,'Institution identity mismatch')
 if run['manifest']['checkpoints'][run['checkpoint']]=='claims_query_discovered':
  from sandbox.checkpoints import same_instant
  recorded=(snapshot.get('complex_workflow') or {}).get('query') or {}
  if recorded and (recorded.get('patient_id')!=q['patient_id'] or recorded.get('admission_id')!=q['admission_id']
      or any(recorded.get('references',{}).get(key)!=q['references'][key] for key in ('query','claim','enhancement','final_request')) or set(recorded.get('required_documents',[]))!=set(q['required_documents'])
      or not same_instant(recorded.get('received_at'),q['received_at'])):
   raise HTTPException(409,'Recorded claims facts differ from the institution; human review required')
 state={'query_state':q['query_state'],'enhancement_linked':q['enhancement_linked'],'decision_present':bool(q.get('decision')),'clearance_present':bool(h.get('clearance'))}
 conn.execute("UPDATE coordinator.sandbox_runs SET state='PAUSED',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s",(run_id,))
 runs.event(conn,run_id,'INSTITUTION_FOLLOWUP_RECONCILED',{'institution_state':state,'checkpoint_advanced':False,'institution_write':False})
 return {'state':'PAUSED','institution_state':state,'checkpoint_advanced':False,'institution_write':False}


def reconcile_dispatch(conn,run_id,*,core,institutions,hospital_token):
 run=runs.get(conn,run_id,True)
 if run['state']!='UNCERTAIN' or run['manifest']['checkpoints'][run['checkpoint']]!='hospital_dispatch_recorded':
  raise HTTPException(409,'Only an uncertain dispatch phase can use this recovery')
 for client in [core,institutions]:
  response=client.get('/health');response.raise_for_status()
  if response.json().get('environment')!='sandbox':raise PermissionError('Sandbox services required')
 response=core.get('/v1/incidents/'+str(run['incident_id']));response.raise_for_status();case=response.json();incident=case['incident'];workflow=case['complex_workflow']
 if not incident['consent_active'] or incident['consent_version']!=run['consent_version'] or not workflow['approval_current']:
  raise HTTPException(409,'Current consent and exact packet approval required')
 if conn.execute("SELECT 1 FROM coordinator.calls WHERE incident_id=%s AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER') LIMIT 1",(run['incident_id'],)).fetchone():
  raise HTTPException(409,'Close or reconcile active conversations first')
 response=institutions.get('/hospital/complex/'+str(run['institution_case_id'])+'/desks/insurance',headers={'Authorization':'Bearer '+hospital_token});response.raise_for_status()
 matches=[d for d in response.json()['dispatches'] if d.get('idempotency_key')==str(run_id)]
 if len(matches)!=1 or matches[0]['packet']!=workflow['packet']:
  raise HTTPException(409,'A single institution dispatch matching the approved packet is required')
 dispatch=matches[0];proof=None
 for doc in conn.execute("SELECT id,data FROM coordinator.documents WHERE incident_id=%s AND kind='dispatch'",(run['incident_id'],)):
  try:value=json.loads(bytes(doc['data']))
  except (ValueError,TypeError):continue
  if value==dispatch:proof=str(doc['id']);break
 if not proof:raise HTTPException(409,'Matching uploaded dispatch proof required')
 conn.execute("UPDATE coordinator.sandbox_runs SET state='PAUSED',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s",(run_id,))
 runs.event(conn,run_id,'DISPATCH_EXECUTION_RECONCILED',{'dispatch_id':dispatch['id'],'document_id':proof,'next_action':'CONFIRM_EXISTING_DISPATCH','resubmitted':False,'receipt_verified':False})
 from coordinator.reference_evidence import hospital_dispatch_reference
 return {'state':'PAUSED','dispatch_id':dispatch['id'],'dispatch_reference':hospital_dispatch_reference(dispatch),'resubmitted':False,'checkpoint_advanced':False}
