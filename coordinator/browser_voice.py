"""Case-bound browser voice sessions. This module never schedules phone calls."""
import hashlib,json,secrets
from uuid import UUID,uuid4
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict
from typing import Literal
from psycopg.types.json import Jsonb
from coordinator.bolna import Bolna,ProviderRejected
from coordinator.workflow_calls import prepare_context
from coordinator.gateway_preflight import check_gateway


class BrowserSessionInput(BaseModel):
 model_config=ConfigDict(extra='forbid')
 recording_consent:Literal[True]


def configured(config):
 return bool(config.get('environment')=='operational' and config.get('browser_voice_enabled')
  and config.get('bolna_api_key') and config.get('bolna_agent_id'))


def caregiver_greeting(purpose):
 if purpose=='CAREGIVER_COMPLEX_UPDATE':return "Hi, I'm Claim911. I've checked the latest case updates. Would you like a short summary?"
 return "Hi, I'm Claim911. Tell me what's holding up the hospital discharge."


def install(app,db,operator,incident,require_consent,event,config):
 if config.get('environment')!='operational':return

 @app.post('/v1/incidents/{id}/browser-session',dependencies=[Depends(operator)],status_code=201)
 def mint(id:UUID,body:BrowserSessionInput):
  if not configured(config):raise HTTPException(503,'Browser voice is not configured')
  provider=Bolna(config['bolna_api_key'])
  try:current_fingerprint=provider.agent_configuration_fingerprint(config['bolna_agent_id'])
  except Exception:raise HTTPException(503,'The reviewed assistant configuration could not be verified') from None
  if not secrets.compare_digest(current_fingerprint,config.get('bolna_agent_config_sha256','')):
   raise HTTPException(409,'The assistant configuration changed; review it before starting voice')
  if not check_gateway(config)['ready']:raise HTTPException(503,'The scoped voice connection is unavailable')
  call_id=uuid4();token=secrets.token_urlsafe(40)
  with db() as conn:
   row=incident(conn,id,True);require_consent(row)
   if row['state'] in {'HUMAN_REVIEW','PAUSED_REVOKED'}:raise HTTPException(409,'Case requires review')
   active=conn.execute("SELECT id FROM coordinator.calls WHERE incident_id=%s AND mode='BOLNA_WEBRTC' AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER')",(id,)).fetchone()
   if active:raise HTTPException(409,'Finish or reconcile the existing browser session first')
   count=conn.execute("SELECT count(*) AS n FROM coordinator.calls WHERE incident_id=%s AND mode='BOLNA_WEBRTC'",(id,)).fetchone()['n']
   if count>=config.get('max_browser_sessions_per_case',4):raise HTTPException(409,'Browser session limit reached; coordinator review required')
   workflow=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone()
   purpose='CAREGIVER_COMPLEX_UPDATE' if workflow else 'CAREGIVER_INTAKE'
   context=prepare_context(row,workflow['data'] if workflow else None,purpose)
   conn.execute("""INSERT INTO coordinator.calls(id,incident_id,participant_role,purpose,mode,state,
    tool_token_hash,consent_version,tool_expires_at,recording_consent)
    VALUES(%s,%s,'caregiver',%s,'BOLNA_WEBRTC','DISPATCHING',%s,%s,now()+interval '10 minutes',true)""",
    (call_id,id,purpose,hashlib.sha256(token.encode()).hexdigest(),row['consent_version']))
   event(conn,id,'BROWSER_SESSION_REQUESTED',{'call_id':str(call_id),'purpose':purpose,'phone_dispatch':False,'recording_consent':True})
   version=row['consent_version']
  # Persist intent before requesting an ephemeral session. No provider credentials
  # or reusable session password is written to events or command-result caches.
  state='QUEUED';session=None
  try:
   session=provider.web_session(config['bolna_agent_id'],{
    'call_token':token,'claim911_greeting':caregiver_greeting(purpose),'claim911_objective':context['objective'],
    'claim911_context':json.dumps({'incident_id':str(id),'call_id':str(call_id),'purpose':purpose,
     'participant_role':'caregiver','simulated':True,'investigation_consent_active':row['consent_active'],**context},default=str),
    'claim911_case_id':str(id),'claim911_purpose':purpose})
  except ProviderRejected:state='FAILED'
  except Exception:state='DISPATCH_UNKNOWN'
  revoked=False
  with db() as conn:
   current=incident(conn,id,True)
   revoked=not current['consent_active'] or current['consent_version']!=version
   conn.execute("UPDATE coordinator.calls SET state=%s,execution_id=%s,tool_expires_at=CASE WHEN %s THEN now() ELSE tool_expires_at END WHERE id=%s",
    (state,session['run_id'] if session else None,revoked or state!='QUEUED',call_id))
   if revoked and session:
    conn.execute("INSERT INTO coordinator.jobs(id,incident_id,kind,payload) VALUES(%s,%s,'STOP_CALL',%s)",
     (uuid4(),id,Jsonb({'call_id':str(call_id),'execution_id':session['run_id']})))
   event(conn,id,'BROWSER_SESSION_RESULT',{'call_id':str(call_id),'state':state,'consent_current':not revoked,
   'phone_dispatch':False,'automatic_retry':False,'assistant_config_sha256':current_fingerprint})
  if revoked:raise HTTPException(409,'Permission changed while preparing voice; session withheld')
  if state!='QUEUED':raise HTTPException(502,'Voice session unavailable; reconcile before trying again' if state=='DISPATCH_UNKNOWN' else 'Voice provider rejected this session')
  return {'call_id':str(call_id),'transport':'BOLNA_WEBRTC','session':session}

 @app.post('/v1/incidents/{id}/browser-session/{call_id}/stop',dependencies=[Depends(operator)],status_code=202)
 def stop(id:UUID,call_id:UUID):
  with db() as conn:
   incident(conn,id,True)
   call=conn.execute("SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='BOLNA_WEBRTC' FOR UPDATE",(call_id,id)).fetchone()
   if not call:raise HTTPException(404,'Browser session not found')
   conn.execute('UPDATE coordinator.calls SET tool_expires_at=now() WHERE id=%s',(call_id,))
   if call['execution_id'] and call['state'] not in {'COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER'}:
    existing=conn.execute("SELECT id FROM coordinator.jobs WHERE kind='STOP_CALL' AND payload->>'call_id'=%s",(str(call_id),)).fetchone()
    if not existing:
     conn.execute("INSERT INTO coordinator.jobs(id,incident_id,kind,payload) VALUES(%s,%s,'STOP_CALL',%s)",
      (uuid4(),id,Jsonb({'call_id':str(call_id),'execution_id':call['execution_id']})))
     event(conn,id,'CALL_STOP_REQUESTED',{'call_id':str(call_id),'confirmed_stopped':False,'transport':'BOLNA_WEBRTC'})
  return {'stop_requested':True,'provider_stop_confirmed':False}
