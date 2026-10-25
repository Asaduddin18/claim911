import hashlib,json,os,secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID,uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI,HTTPException,Request,Response,UploadFile,File,Form,Query
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field,ConfigDict,AwareDatetime
from coordinator.reasoning import ActionProposal
from experience.presentation import activity,financials,CHECKPOINTS,EVENTS
from coordinator.app import create_app as coordinator
from coordinator.browser_voice import configured as browser_voice_configured


class Input(BaseModel):
 model_config=ConfigDict(extra='forbid')


class SessionInput(Input):
 role:Literal['caregiver','controller','sandbox','sandbox_harness']='caregiver'
 credential:str=''
 run_id:UUID|None=None


class Intake(Input):
 name:str=Field(min_length=1,max_length=100)
 concern:str=Field(min_length=5,max_length=2000)
 language:Literal['en','hi']='en'
 investigation_consent:bool


class CallbackInput(Input):
 proposal:ActionProposal
 due_at:AwareDatetime


class ConsentInput(Input):
 accepted:bool


class BrowserSessionInput(Input):
 recording_consent:Literal[True]


class PacketPermissionInput(Input):
 accepted:Literal[True]
 packet_hash:str=Field(pattern='^[a-f0-9]{64}$')


class PrepareRun(Input):
 language:Literal['en','hi']='en'


class ScenarioFaultInput(Input):
 faults:list[Literal['unsigned_summary','wrong_admission_invoice','old_bill','withheld_receipt','pending_insurer','denied_insurer','desk_unavailable']]=Field(max_length=7)


class RunControl(Input):
 operation:Literal['pause','resume','cancel','reset']


class AdvanceClock(Input):
 seconds:int=Field(strict=True,gt=0,le=900)


class SandboxVoiceSessionInput(Input):
 recording_consent:Literal[True]


def create_app(config=None):
 cfg=config or json.loads(Path(os.environ['CLAIM911_PROFILE_CONFIG']).read_text())
 environment=cfg['environment']
 if environment not in {'operational','sandbox'}:raise ValueError('Explicit isolated environment required')
 if environment=='sandbox' and (cfg.get('live_calls_enabled') or cfg.get('bolna_api_key')):
  raise ValueError('Sandbox must have no live calling credentials')
 def browser_voice_available():
  if environment=='sandbox':
   return bool(cfg.get('sandbox_bolna_broker_url') and cfg.get('sandbox_bolna_broker_token') and cfg.get('sandbox_bolna_agent_config_sha256'))
  return browser_voice_configured(cfg)
 core=TestClient(coordinator(cfg));core.headers['Authorization']='Bearer '+cfg['operator_token']
 app=FastAPI(title='Claim911 '+environment+' product API',docs_url=None,redoc_url=None,openapi_url=None)
 @contextmanager
 def db():
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:yield conn
 with db() as conn:
  conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.product_sessions(
   id uuid PRIMARY KEY,token_hash text UNIQUE NOT NULL,role text NOT NULL,
   expires_at timestamptz NOT NULL DEFAULT now()+interval '12 hours')''')
  conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.product_cases(
   incident_id uuid PRIMARY KEY REFERENCES coordinator.incidents(id),session_id uuid NOT NULL REFERENCES coordinator.product_sessions(id),
   name text NOT NULL,concern text NOT NULL,language text NOT NULL)''')
  conn.execute('ALTER TABLE coordinator.product_sessions ADD COLUMN IF NOT EXISTS scope_run_id uuid')
  if environment=='sandbox':
   from sandbox.runs import initialize
   initialize(conn,environment=environment)
   conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_harness_tokens(
    token_hash text PRIMARY KEY,run_id uuid NOT NULL REFERENCES coordinator.sandbox_runs(id),
    expires_at timestamptz NOT NULL DEFAULT now()+interval '5 minutes',consumed_at timestamptz)''')
 def cookie(role):return 'claim911_'+environment+'_'+role
 def session(request,role):
  token=request.cookies.get(cookie(role),'')
  with db() as conn:
   row=conn.execute('SELECT * FROM coordinator.product_sessions WHERE token_hash=%s AND role=%s AND expires_at>now()',
     (hashlib.sha256(token.encode()).hexdigest(),role)).fetchone()
  if not row:raise HTTPException(401,'Please open your workspace again.')
  return row
 def harness_session(request):
  token=request.cookies.get('claim911_sandbox_harness','')
  if not token:raise HTTPException(401,'A run-scoped synthetic session is required.')
  with db() as conn:
   row=conn.execute("SELECT * FROM coordinator.product_sessions WHERE token_hash=%s AND role='sandbox_harness' AND scope_run_id IS NOT NULL AND expires_at>now()",
    (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
  if not row:raise HTTPException(401,'The run-scoped synthetic session has expired.')
  return row
 def sandbox_run_access(request,id):
  try:return session(request,'sandbox')
  except HTTPException as exc:
   if exc.status_code!=401:raise
  actor=harness_session(request)
  if actor['scope_run_id']!=id:raise HTTPException(404,'Synthetic run not found.')
  return actor
 def owned(request,id):
  user=session(request,'caregiver')
  with db() as conn:
   record=conn.execute('SELECT * FROM coordinator.product_cases WHERE incident_id=%s AND session_id=%s',(id,user['id'])).fetchone()
  if not record:raise HTTPException(404,'Case not found in your workspace.')
  return record
 def checked(response):
  if response.status_code>=400:raise HTTPException(response.status_code,'The requested case action could not be completed.')
  return response.json()
 def case_view(record):
  data=checked(core.get('/v1/incidents/'+str(record['incident_id'])))
  i=data['incident'];w=data.get('complex_workflow');tasks=w['tasks'] if w else []
  stages=['Investigating' if w else 'Getting started','Collecting documents','Awaiting a decision','Confirmed outcome']
  from experience.presentation import caregiver_progress
  progress=caregiver_progress(data)
  return {'id':str(i['id']),'name':record['name'],'concern':record['concern'],'language':record['language'],
   'status':progress['status'],'stage':progress['stage'],'stages':stages,'next_action':progress['next_action'],'consent_active':i['consent_active'],
   'documents':[{'id':str(d['id']),'name':d['filename'],'kind':d['kind'],'status':d['status'],
    'evidence_checked':str(d['id']) in {str(x['document_id']) for x in (w or {}).get('documents',{}).values()}} for d in data['documents']],
   'packet_permission':({'packet_hash':w['packet_hash'],'recipient':'Synthetic TPA claims desk','approved':w['approval_current'],
    'documents':[{'id':d['id'],'kind':d['kind'],'revision':d.get('revision')} for d in w['packet']['document_records']]} if w and w.get('packet') else None),
   'tasks':tasks,'summary':w.get('caregiver_summary') if w else None,
   'activity':[a for e in data['events'] if (a:=activity(e))][-8:],
   'financials':financials(w),
   'environment':environment,'voice_available':browser_voice_available(),'coordination_available':False}
 @app.get('/v2/health')
 def health():return {'status':'ready','environment':environment,'phone_dispatch_enabled':False,
  'browser_voice_available':browser_voice_available()}
 @app.post('/v2/sessions')
 def login(body:SessionInput,response:Response):
  if body.role=='sandbox_harness':
   if environment!='sandbox' or body.run_id is None or not body.credential:
    raise HTTPException(403,'A run-scoped sandbox credential is required.')
   token_hash=hashlib.sha256(body.credential.encode()).hexdigest()
   with db() as conn:
    ticket=conn.execute('SELECT run_id FROM coordinator.sandbox_harness_tokens WHERE token_hash=%s AND run_id=%s AND consumed_at IS NULL AND expires_at>now() FOR UPDATE',
     (token_hash,body.run_id)).fetchone()
    if not ticket:raise HTTPException(403,'The run-scoped sandbox credential is invalid or expired.')
    run=conn.execute('SELECT state,origin,incident_id,provider_configuration FROM coordinator.sandbox_runs WHERE id=%s',(body.run_id,)).fetchone()
    if (not run or run['state'] not in {'RUNNING','PAUSE_REQUESTED'} or run['origin'] not in {'AUDIO_DEMONSTRATION','USER_PREPARED'}
        or not run['incident_id'] or (run['provider_configuration'] or {}).get('transport')!='BOLNA_WEBRTC'):
     raise HTTPException(403,'The synthetic run is not eligible for a scoped voice session.')
    conn.execute('UPDATE coordinator.sandbox_harness_tokens SET consumed_at=now() WHERE token_hash=%s',(token_hash,))
    cookie_token=secrets.token_urlsafe(40);sid=uuid4()
    conn.execute("INSERT INTO coordinator.product_sessions(id,token_hash,role,scope_run_id,expires_at) VALUES(%s,%s,'sandbox_harness',%s,now()+interval '30 minutes')",
     (sid,hashlib.sha256(cookie_token.encode()).hexdigest(),body.run_id))
   response.set_cookie('claim911_sandbox_harness',cookie_token,httponly=True,samesite='strict',max_age=1800,path='/')
   return {'role':'sandbox_harness','environment':'sandbox','run_id':str(body.run_id)}
  allowed={'caregiver','controller'} if environment=='operational' else {'sandbox'}
  if body.role not in allowed:raise HTTPException(403,'This role belongs to another environment.')
  if body.role!='caregiver' and not secrets.compare_digest(body.credential,cfg['operator_token']):
   raise HTTPException(403,'Workspace credential is not valid.')
  token=secrets.token_urlsafe(40);id=uuid4()
  with db() as conn:conn.execute('INSERT INTO coordinator.product_sessions(id,token_hash,role) VALUES(%s,%s,%s)',(id,hashlib.sha256(token.encode()).hexdigest(),body.role))
  response.set_cookie(cookie(body.role),token,httponly=True,samesite='strict',max_age=43200,path='/')
  return {'role':body.role,'environment':environment}
 @app.delete('/v2/sessions/{role}')
 def logout(role:Literal['caregiver','controller','sandbox'],request:Request,response:Response):
  user=session(request,role)
  with db() as conn:conn.execute('UPDATE coordinator.product_sessions SET expires_at=now() WHERE id=%s',(user['id'],))
  response.delete_cookie(cookie(role),path='/');return {'signed_out':True}
 @app.get('/v2/caregiver/cases')
 def cases(request:Request):
  user=session(request,'caregiver')
  with db() as conn:records=conn.execute('SELECT * FROM coordinator.product_cases WHERE session_id=%s ORDER BY incident_id',(user['id'],)).fetchall()
  return [case_view(r) for r in records]
 @app.post('/v2/caregiver/cases/{id}/voice-session',status_code=201)
 def browser_session(id:UUID,body:BrowserSessionInput,request:Request,response:Response):
  owned(request,id)
  response.headers['Cache-Control']='no-store'
  return checked(core.post(f'/v1/incidents/{id}/browser-session',json=body.model_dump()))
 @app.post('/v2/caregiver/cases/{id}/voice-session/{call_id}/stop',status_code=202)
 def stop_browser_session(id:UUID,call_id:UUID,request:Request):
  owned(request,id)
  return checked(core.post(f'/v1/incidents/{id}/browser-session/{call_id}/stop'))
 @app.post('/v2/caregiver/cases',status_code=201)
 def intake(body:Intake,request:Request):
  user=session(request,'caregiver')
  if not body.investigation_consent:raise HTTPException(422,'Permission to investigate is required to start coordination.')
  id=checked(core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':str(uuid4()),'title':'Discharge coordination','patient_id':'DEMO-'+uuid4().hex[:8].upper(),'reference_known':False}))['incident_id']
  checked(core.post('/v1/incidents/'+id+'/consent',json={'accepted':True,'confirmation':'Caregiver explicitly permitted investigation from their scoped workspace. Synthetic demonstration only.'}))
  with db() as conn:
   record=conn.execute('INSERT INTO coordinator.product_cases(incident_id,session_id,name,concern,language) VALUES(%s,%s,%s,%s,%s) RETURNING *',(id,user['id'],body.name,body.concern,body.language)).fetchone()
  return case_view(record)
 @app.get('/v2/caregiver/cases/{id}')
 def case(id:UUID,request:Request):return case_view(owned(request,id))
 @app.post('/v2/caregiver/cases/{id}/consent')
 def caregiver_consent(id:UUID,body:ConsentInput,request:Request):
  record=owned(request,id)
  checked(core.post(f'/v1/incidents/{id}/consent',json={'accepted':body.accepted,
   'confirmation':'Case caregiver explicitly '+('allowed' if body.accepted else 'withdrew')+' investigation in their scoped workspace.'}))
  return case_view(record)
 @app.post('/v2/caregiver/cases/{id}/packet-permission')
 def packet_permission(id:UUID,body:PacketPermissionInput,request:Request):
  record=owned(request,id)
  checked(core.post(f'/v1/incidents/{id}/complex/approve',json={'source':'CAREGIVER_SCOPED_SESSION',
   'accepted':True,'packet_hash':body.packet_hash,'confirmation':'Authenticated case caregiver approved the displayed exact packet for the synthetic TPA claims desk.'}))
  return case_view(record)
 @app.delete('/v2/caregiver/cases/{id}/packet-permission')
 def revoke_packet_permission(id:UUID,request:Request):
  record=owned(request,id);checked(core.post(f'/v1/incidents/{id}/complex/revoke-approval'))
  return case_view(record)
 @app.post('/v2/caregiver/cases/{id}/documents',status_code=201)
 def upload(id:UUID,request:Request,file:UploadFile=File(),kind:Literal['dispatch','receipt','policy','bill','other']=Form('other')):
  owned(request,id);content=file.file.read(10*1024*1024+1)
  if len(content)>10*1024*1024:raise HTTPException(413,'Document exceeds 10 MiB.')
  return checked(core.post(f'/v1/incidents/{id}/documents',files={'file':(file.filename,content,file.content_type)},data={'kind':kind}))
 @app.get('/v2/caregiver/cases/{id}/documents/{did}')
 def document(id:UUID,did:UUID,request:Request):
  owned(request,id);r=core.get(f'/v1/incidents/{id}/documents/{did}')
  if r.status_code!=200:raise HTTPException(404,'Document not found.')
  return Response(r.content,media_type=r.headers.get('content-type','application/octet-stream'),headers={'Content-Disposition':'inline','X-Content-Type-Options':'nosniff'})
 def activity_page(id,before,limit):
  with db() as conn:
   rows=conn.execute("SELECT sequence,type,created_at FROM coordinator.events WHERE incident_id=%s AND type=ANY(%s) AND (%s::bigint IS NULL OR sequence<%s) ORDER BY sequence DESC LIMIT %s",
    (id,list(EVENTS),before,before,limit+1)).fetchall()
  return {'items':[activity(e) for e in rows[:limit]],'next_cursor':rows[limit-1]['sequence'] if len(rows)>limit else None}
 def conversation_page(id,offset,limit):
  with db() as conn:
   rows=conn.execute('SELECT id,participant_role,purpose,mode,state,created_at FROM coordinator.calls WHERE incident_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s',(id,limit+1,offset)).fetchall()
  return {'items':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}
 def conversation_detail(id,call_id):
  with db() as conn:
   row=conn.execute('SELECT id,participant_role,purpose,mode,state,transcript,created_at FROM coordinator.calls WHERE id=%s AND incident_id=%s',(call_id,id)).fetchone()
  if not row:raise HTTPException(404,'Conversation not found in this case.')
  return row
 @app.get('/v2/caregiver/cases/{id}/activity')
 def caregiver_activity(id:UUID,request:Request,before:int|None=Query(None,gt=0),limit:int=Query(8,ge=1,le=20)):
  owned(request,id);return activity_page(id,before,limit)
 @app.get('/v2/caregiver/cases/{id}/conversations')
 def caregiver_conversations(id:UUID,request:Request,offset:int=Query(0,ge=0),limit:int=Query(6,ge=1,le=12)):
  owned(request,id);return conversation_page(id,offset,limit)
 @app.get('/v2/caregiver/cases/{id}/conversations/{call_id}')
 def caregiver_conversation(id:UUID,call_id:UUID,request:Request):
  owned(request,id);return conversation_detail(id,call_id)
 @app.get('/v2/controller/cases')
 def queue(request:Request):
  session(request,'controller')
  rows=checked(core.get('/v1/incidents?include_tests=false'))
  with db() as conn:
   people={str(r['incident_id']):r['name'] for r in conn.execute('SELECT incident_id,name FROM coordinator.product_cases').fetchall()}
  return [{**r,'name':people.get(str(r['id']))} for r in rows]
 @app.get('/v2/controller/cases/{id}')
 def investigation(id:UUID,request:Request):
  session(request,'controller');return checked(core.get('/v1/incidents/'+str(id)))
 def controller_case(request,id):
  session(request,'controller')
  return checked(core.get('/v1/incidents/'+str(id)))
 @app.get('/v2/controller/cases/{id}/activity')
 def controller_activity(id:UUID,request:Request,before:int|None=Query(None,gt=0),limit:int=Query(8,ge=1,le=20)):
  controller_case(request,id);return activity_page(id,before,limit)
 @app.get('/v2/controller/cases/{id}/conversations')
 def controller_conversations(id:UUID,request:Request,offset:int=Query(0,ge=0),limit:int=Query(6,ge=1,le=12)):
  controller_case(request,id);return conversation_page(id,offset,limit)
 @app.get('/v2/controller/cases/{id}/conversations/{call_id}')
 def controller_conversation(id:UUID,call_id:UUID,request:Request):
  controller_case(request,id);return conversation_detail(id,call_id)
 @app.get('/v2/controller/cases/{id}/documents/{did}')
 def controller_document(id:UUID,did:UUID,request:Request):
  controller_case(request,id);response=core.get(f'/v1/incidents/{id}/documents/{did}')
  if response.status_code!=200:raise HTTPException(404,'Document not found in this case.')
  return Response(response.content,media_type=response.headers.get('content-type','application/octet-stream'),headers={'Content-Disposition':'inline','X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})
 @app.get('/v2/controller/cases/{id}/decisions')
 def decisions(id:UUID,request:Request):
  session(request,'controller')
  from coordinator.reasoning import decision_view
  return decision_view(checked(core.get('/v1/incidents/'+str(id))))
 @app.get('/v2/controller/cases/{id}/callbacks')
 def callbacks(id:UUID,request:Request):
  session(request,'controller');checked(core.get('/v1/incidents/'+str(id)))
  with db() as conn:
   rows=conn.execute('SELECT id,purpose,state,attempts,original_received_at,target_at,available_at,result FROM coordinator.workflow_callbacks WHERE incident_id=%s ORDER BY created_at',(id,)).fetchall()
  return rows
 @app.post('/v2/controller/cases/{id}/callbacks',status_code=201)
 def schedule_callback(id:UUID,body:CallbackInput,request:Request):
  session(request,'controller')
  if body.proposal.incident_id!=id:raise HTTPException(422,'Proposal must belong to the requested case')
  snapshot=checked(core.get('/v1/incidents/'+str(id)))
  from coordinator.callbacks import schedule
  with db() as conn:task=schedule(conn,snapshot,body.proposal,body.due_at)
  return {k:task[k] for k in ['id','purpose','state','attempts','original_received_at','target_at','available_at']}
 @app.delete('/v2/controller/cases/{id}/callbacks/{task_id}')
 def cancel_callback(id:UUID,task_id:UUID,request:Request):
  controller_case(request,id)
  from coordinator.callbacks import cancel_waiting
  with db() as conn:task=cancel_waiting(conn,id,task_id)
  return {k:task[k] for k in ['id','purpose','state','attempts','original_received_at','target_at','available_at']}
 @app.get('/v2/controller/legacy/cases')
 def legacy_cases(request:Request):
  session(request,'controller')
  if not cfg.get('legacy_read_dsn'):return []
  with psycopg.connect(cfg['legacy_read_dsn'],row_factory=dict_row) as conn:
   return conn.execute("SELECT id,title,state,decision_state,created_at FROM coordinator.incidents WHERE NOT is_test ORDER BY created_at DESC LIMIT 50").fetchall()
 @app.get('/v2/controller/legacy/cases/{id}')
 def legacy_evidence(id:UUID,request:Request):
  session(request,'controller')
  if not cfg.get('legacy_read_dsn'):raise HTTPException(404,'Legacy evidence not configured.')
  with psycopg.connect(cfg['legacy_read_dsn'],row_factory=dict_row) as conn:
   row=conn.execute('SELECT id,title,state,decision_state FROM coordinator.incidents WHERE id=%s',(id,)).fetchone()
   if not row:raise HTTPException(404,'Legacy case not found.')
   calls=conn.execute('SELECT id,participant_role,purpose,mode,state,transcript,created_at FROM coordinator.calls WHERE incident_id=%s ORDER BY created_at',(id,)).fetchall()
   docs=conn.execute('SELECT id,filename,kind,status,content_hash FROM coordinator.documents WHERE incident_id=%s ORDER BY created_at',(id,)).fetchall()
  return {'incident':row,'calls':calls,'documents':docs,'read_only':True,'environment':'legacy'}
 @app.get('/v2/controller/legacy/cases/{id}/documents/{did}')
 def legacy_document(id:UUID,did:UUID,request:Request):
  session(request,'controller')
  if not cfg.get('legacy_read_dsn'):raise HTTPException(404,'Legacy evidence not configured.')
  with psycopg.connect(cfg['legacy_read_dsn'],row_factory=dict_row) as conn:
   d=conn.execute('SELECT data,content_type FROM coordinator.documents WHERE id=%s AND incident_id=%s',(did,id)).fetchone()
  if not d:raise HTTPException(404,'Legacy document not found.')
  return Response(bytes(d['data']),media_type=d['content_type'],headers={'X-Content-Type-Options':'nosniff'})
 @app.get('/v2/sandbox/status')
 def sandbox_status(request:Request):
  operator=True
  try:session(request,'sandbox')
  except HTTPException as exc:
   if exc.status_code!=401:raise
   harness_session(request);operator=False
  from sandbox.readiness import available
  from sandbox.spend import testing_readiness
  with db() as conn:
   ready=bool(cfg.get('sandbox_execution_enabled') and cfg.get('sandbox_seed_token') and available(conn))
   paid=testing_readiness(conn)
  bolna_ready=browser_voice_available()
  return {'environment':'sandbox','runner_available':ready,'bolna_browser_available':bolna_ready,
   'scenario_management_available':operator,'phone_dispatch_enabled':False,
   'paid_testing_allowed':paid['allowed'],'paid_testing_code':paid['code'],'paid_testing_message':paid['message'],
   'message':'Synthetic audio worker available.' if ready else 'The synthetic audio worker is unavailable. Saved runs remain inspectable.'}
 @app.get('/v2/sandbox/runs')
 def sandbox_runs(request:Request):
  from sandbox.runs import public
  try:
   session(request,'sandbox')
   scoped_id=None
  except HTTPException as exc:
   if exc.status_code!=401:raise
   scoped_id=harness_session(request)['scope_run_id']
  with db() as conn:
   if scoped_id:return [public(__import__('sandbox.runs',fromlist=['get']).get(conn,scoped_id))]
   return [public(row) for row in conn.execute("SELECT r.* FROM coordinator.sandbox_runs r LEFT JOIN coordinator.incidents i ON i.id=r.incident_id WHERE r.origin IN ('USER_PREPARED','AUDIO_DEMONSTRATION') ORDER BY (r.origin='AUDIO_DEMONSTRATION') DESC,r.created_at DESC LIMIT 20").fetchall()]
 @app.get('/v2/sandbox/runs/{id}')
 def sandbox_run(id:UUID,request:Request):
  sandbox_run_access(request,id)
  from sandbox.runs import get,public,full_case_completed
  with db() as conn:
   row=get(conn,id)
   calls=conn.execute("SELECT id,purpose,participant_role,mode,state,sandbox_audio_provenance,created_at FROM coordinator.calls WHERE incident_id=%s ORDER BY created_at DESC LIMIT 20",(row['incident_id'],)).fetchall() if row['incident_id'] else []
   events=conn.execute('SELECT sequence,type,created_at FROM coordinator.sandbox_run_events WHERE run_id=%s ORDER BY sequence DESC LIMIT 12',(id,)).fetchall()
   callback_waiting=bool(conn.execute("SELECT 1 FROM coordinator.workflow_callbacks WHERE incident_id=%s AND state='WAITING' LIMIT 1",(row['incident_id'],)).fetchone()) if row['incident_id'] else False
  outcome=None
  if row['checkpoint']>=12:
   data=checked(core.get('/v1/incidents/'+str(row['incident_id'])));workflow=data.get('complex_workflow') or {}
   if workflow.get('clearance'):outcome={'financials':financials(workflow),'summary':workflow.get('caregiver_summary'),'synthetic':True}
  return {**public(row),'checkpoints':[{'key':key,'title':CHECKPOINTS[key],'state':'verified' if n<row['checkpoint'] else 'current' if n==row['checkpoint'] else 'pending'} for n,key in enumerate(row['manifest']['checkpoints'])],
    'conversations':calls,'recent_events':events,'callback_waiting':callback_waiting,'outcome':outcome,'full_case_completed':full_case_completed(row)}
 @app.get('/v2/sandbox/runs/{id}/conversations/{call_id}')
 def sandbox_conversation(id:UUID,call_id:UUID,request:Request):
  sandbox_run_access(request,id)
  from sandbox.runs import get
  with db() as conn:
   row=get(conn,id)
   call=conn.execute("SELECT id,purpose,participant_role,mode,state,transcript,sandbox_audio_provenance,recording_url,recording_consent FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO'",(call_id,row['incident_id'])).fetchone()
  if not call:raise HTTPException(404,'Conversation not found in this run.')
  archive=core.get(f'/v1/sandbox/incidents/{row["incident_id"]}/audio-calls/{call_id}/browser-archive') if call['sandbox_audio_provenance']=='BOLNA_WEBRTC' else None
  provider_transcript=call['transcript']
  if archive is not None and archive.status_code==200:call['transcript']=archive.json()['turns']
  artifacts=checked(core.get(f'/v1/sandbox/incidents/{row["incident_id"]}/audio-calls/{call_id}/artifacts'))
  return {k:v for k,v in call.items() if k not in {'recording_url','recording_consent'}}|{
   'audio':artifacts,'original_provider_transcript':provider_transcript if call['sandbox_audio_provenance']=='BOLNA_WEBRTC' else None,
   'provider_recording_available':bool(call['recording_consent'] and call['recording_url']
    and call['sandbox_audio_provenance']=='BOLNA_WEBRTC'),'synthetic':True}
 @app.post('/v2/sandbox/runs/{id}/conversations/{call_id}/abort')
 def abort_sandbox_conversation(id:UUID,call_id:UUID,request:Request):
  sandbox_run_access(request,id)
  from sandbox.runs import get
  with db() as conn:
   run=get(conn,id)
   call=conn.execute("SELECT id FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO'",(call_id,run['incident_id'])).fetchone()
  if not call:raise HTTPException(404,'Conversation not found in this synthetic run.')
  return checked(core.post(f'/v1/sandbox/incidents/{run["incident_id"]}/audio-calls/{call_id}/abort'))
 @app.post('/v2/sandbox/runs/{id}/conversations/{call_id}/provider-execution')
 def sandbox_provider_execution(id:UUID,call_id:UUID,request:Request):
  sandbox_run_access(request,id)
  from sandbox.runs import get
  with db() as conn:
   run=get(conn,id)
   call=conn.execute("SELECT execution_id,sandbox_audio_provenance FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO'",
    (call_id,run['incident_id'])).fetchone()
  if not call or call['sandbox_audio_provenance']!='BOLNA_WEBRTC' or not call['execution_id']:
   raise HTTPException(404,'Bolna execution is not bound to this synthetic conversation.')
  broker_url=cfg.get('sandbox_bolna_broker_url','');broker_token=cfg.get('sandbox_bolna_broker_token','')
  from urllib.parse import urlsplit
  from ipaddress import ip_address
  parsed=urlsplit(broker_url)
  try:loopback=parsed.hostname in {'localhost'} or ip_address(parsed.hostname).is_loopback
  except (ValueError,TypeError):loopback=False
  if parsed.scheme!='http' or not loopback or parsed.port not in (None,8127) or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
   raise HTTPException(503,'The private Bolna execution broker is unavailable.')
  try:
   import httpx
   with httpx.Client(timeout=8,follow_redirects=False) as broker:
    response=broker.post(broker_url.rstrip('/')+'/execution',headers={'Authorization':'Bearer '+broker_token},
     json={'execution_id':str(call['execution_id']),'call_id':str(call_id),'incident_id':str(run['incident_id'])})
   if response.status_code!=200:raise HTTPException(503,'Bolna execution evidence is not available yet.')
   evidence=response.json()
   if (not isinstance(evidence,dict) or evidence.get('execution_id')!=str(call['execution_id'])
       or not isinstance(evidence.get('status'),str) or not isinstance(evidence.get('transcript'),str)
       or len(evidence['transcript'])>250_000
       or (evidence.get('conversation_duration') is not None and type(evidence['conversation_duration']) not in (int,float))):
    raise HTTPException(502,'The private Bolna broker returned invalid execution evidence.')
   return {'execution_id':evidence['execution_id'],'status':evidence['status'],
    'transcript':evidence['transcript'],'conversation_duration':evidence.get('conversation_duration')}
  except HTTPException:raise
  except Exception:raise HTTPException(503,'Bolna execution evidence could not be checked.') from None
 @app.get('/v2/sandbox/runs/{id}/conversations/{call_id}/provider-audio')
 def sandbox_provider_audio(id:UUID,call_id:UUID,request:Request):
  sandbox_run_access(request,id)
  from sandbox.runs import get
  with db() as conn:
   run=get(conn,id)
   call=conn.execute("SELECT execution_id,recording_url,recording_consent,sandbox_audio_provenance FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO'",
    (call_id,run['incident_id'])).fetchone()
  if not call or call['sandbox_audio_provenance']!='BOLNA_WEBRTC' or not call['recording_consent'] or not call['recording_url'] or not call['execution_id']:
   raise HTTPException(404,'Bolna recording is not available for this synthetic conversation.')
  broker_url=cfg.get('sandbox_bolna_broker_url','');broker_token=cfg.get('sandbox_bolna_broker_token','')
  from urllib.parse import urlsplit
  from ipaddress import ip_address
  parsed=urlsplit(broker_url)
  try:loopback=parsed.hostname in {'localhost'} or ip_address(parsed.hostname).is_loopback
  except (ValueError,TypeError):loopback=False
  if parsed.scheme!='http' or not loopback or parsed.port not in (None,8127) or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
   raise HTTPException(503,'The private Bolna recording broker is unavailable.')
  try:
   import httpx
   with httpx.Client(timeout=30,follow_redirects=False) as broker:
    response=broker.post(broker_url.rstrip('/')+'/recording',headers={'Authorization':'Bearer '+broker_token},
     json={'execution_id':str(call['execution_id']),'call_id':str(call_id),'incident_id':str(run['incident_id'])})
   if response.status_code!=200 or not response.headers.get('content-type','').startswith('audio/'):
    raise HTTPException(404,'The provider recording is not available yet.')
   if len(response.content)>25*1024*1024:raise HTTPException(413,'Recording exceeds the playback limit.')
  except HTTPException:raise
  except Exception:raise HTTPException(503,'The private Bolna recording broker could not be reached.') from None
  return Response(response.content,media_type=response.headers['content-type'].split(';')[0],headers={
   'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
 @app.get('/v2/sandbox/runs/{id}/events')
 def sandbox_events(id:UUID,request:Request):
  sandbox_run_access(request,id)
  from sandbox.runs import get
  with db() as conn:get(conn,id)
  raw=request.headers.get('last-event-id','0')
  if not raw.isdecimal() or len(raw)>18:raise HTTPException(422,'A valid event cursor is required.')
  cursor=int(raw)
  async def stream():
   import asyncio,time
   nonlocal cursor
   deadline=time.monotonic()+15
   yield 'retry: 1500\n\n'
   while time.monotonic()<deadline:
    if await request.is_disconnected():return
    sandbox_run_access(request,id)
    with db() as conn:
     events=conn.execute('SELECT sequence,type FROM coordinator.sandbox_run_events WHERE run_id=%s AND sequence>%s ORDER BY sequence LIMIT 100',(id,cursor)).fetchall()
    for event in events:
     cursor=event['sequence']
     yield 'id: '+str(cursor)+'\nevent: run-update\ndata: '+json.dumps({'sequence':cursor,'type':event['type']})+'\n\n'
    if not events:yield ': heartbeat\n\n'
    await asyncio.sleep(1)
  return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache, no-store','X-Accel-Buffering':'no'})
 @app.get('/v2/sandbox/runs/{id}/conversations/{call_id}/audio/{artifact_id}')
 def sandbox_audio(id:UUID,call_id:UUID,artifact_id:UUID,request:Request):
  conversation=sandbox_conversation(id,call_id,request)
  if str(artifact_id) not in {str(a['id']) for a in conversation['audio']}:raise HTTPException(404,'Audio not found in this conversation.')
  with db() as conn:
   row=conn.execute('SELECT incident_id FROM coordinator.sandbox_runs WHERE id=%s',(id,)).fetchone()
  response=core.get(f'/v1/sandbox/incidents/{row["incident_id"]}/audio/{artifact_id}')
  if response.status_code!=200:raise HTTPException(404,'Audio is unavailable.')
  return Response(response.content,media_type='audio/wav',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
 @app.post('/v2/sandbox/runs',status_code=201)
 def prepare_run(body:PrepareRun,request:Request):
  session(request,'sandbox')
  from sandbox.runs import create,public
  with db() as conn:return public(create(conn,language=body.language,origin='USER_PREPARED'))
 @app.post('/v2/sandbox/runs/{id}/control')
 def run_control(id:UUID,body:RunControl,request:Request):
  session(request,'sandbox')
  from sandbox.runs import control,public
  with db() as conn:return public(control(conn,id,body.operation))
 @app.post('/v2/sandbox/runs/{id}/faults')
 def scenario_faults(id:UUID,body:ScenarioFaultInput,request:Request):
  session(request,'sandbox')
  from sandbox.runs import configure_faults,public
  with db() as conn:return public(configure_faults(conn,id,body.faults))
 @app.post('/v2/sandbox/runs/{id}/start',status_code=202)
 def start_run(id:UUID,request:Request):
  session(request,'sandbox')
  from sandbox.spend import require_testing
  with db() as conn:require_testing(conn)
  if not cfg.get('sandbox_execution_enabled'):raise HTTPException(503,'The sandbox execution worker is not available yet.')
  from sandbox.runs import get
  with db() as conn:
   current=get(conn,id)
  fingerprint=cfg.get('sandbox_bolna_agent_config_sha256','')
  if not isinstance(fingerprint,str) or len(fingerprint)!=64 or any(c not in '0123456789abcdef' for c in fingerprint):
   raise HTTPException(503,'The reviewed Bolna assistant fingerprint is not configured.')
  provider_configuration={'transport':'BOLNA_WEBRTC','assistant_config_sha256':fingerprint}
  if current['provider_configuration'] and current['provider_configuration']!=provider_configuration:
   raise HTTPException(409,'This run uses a different or unpinned assistant configuration. Preserve it for review.')
  from sandbox.readiness import available
  with db() as conn:
   if not available(conn):raise HTTPException(503,'The synthetic audio worker is offline. No execution was queued.')
  import httpx
  from sandbox.preparation import bind
  from sandbox.runs import enqueue
  token=cfg.get('sandbox_seed_token')
  if not token:raise HTTPException(503,'Synthetic case preparation is not configured.')
  with httpx.Client(base_url=cfg['simulator_url'],timeout=5) as institutions,db() as conn:
   bind(conn,id,core=core,institutions=institutions,seed_token=token,provider_configuration=provider_configuration)
   return enqueue(conn,id)
 @app.post('/v2/sandbox/runs/{id}/voice-session',status_code=201)
 def sandbox_voice_session(id:UUID,body:SandboxVoiceSessionInput,request:Request):
  """Mint one run-scoped Bolna browser session through the trusted local broker."""
  sandbox_run_access(request,id)
  broker_url=cfg.get('sandbox_bolna_broker_url','')
  broker_token=cfg.get('sandbox_bolna_broker_token','')
  expected_fingerprint=cfg.get('sandbox_bolna_agent_config_sha256','')
  if not broker_url or not broker_token or not expected_fingerprint:
   raise HTTPException(503,'The isolated Bolna browser broker is not configured.')
  from urllib.parse import urlsplit
  from ipaddress import ip_address
  parsed=urlsplit(broker_url)
  try:loopback=parsed.hostname in {'localhost'} or ip_address(parsed.hostname).is_loopback
  except (ValueError,TypeError):loopback=False
  if parsed.scheme!='http' or not loopback or parsed.port not in (None,8127) or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
   raise HTTPException(503,'The sandbox voice broker must use its private loopback service.')
  from sandbox.spend import require_testing
  with db() as conn:require_testing(conn)
  incident_id=None;call_id=None
  def hold_uncertain_session():
   with db() as conn:
    conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s AND state NOT IN ('COMPLETED','CANCELLED')",(id,))
    from psycopg.types.json import Jsonb
    conn.execute("INSERT INTO coordinator.sandbox_run_events(run_id,type,payload) VALUES(%s,'BOLNA_SESSION_UNCERTAIN',%s)",
     (id,Jsonb({'call_id':call_id,'transport':'BOLNA_WEBRTC','automatic_retry':False,'phone_dispatch':False})))
  try:
   import httpx
   from sandbox.preparation import bind as bind_run
   # Prepare the synthetic institution case on demand. This seeds only the
   # isolated sandbox services and does not enqueue any audio worker.
   with db() as conn:initial=__import__('sandbox.runs',fromlist=['get']).get(conn,id)
   if initial['state']=='PREPARED':
    seed=cfg.get('sandbox_seed_token')
    simulator_url=cfg.get('simulator_url')
    if not seed or not simulator_url:raise HTTPException(503,'Synthetic sandbox preparation is unavailable.')
    with httpx.Client(base_url=simulator_url,timeout=5) as institutions,db() as conn:
     bind_run(conn,id,core=core,institutions=institutions,seed_token=seed)
   with db() as conn:
    run_row=__import__('sandbox.runs',fromlist=['get']).get(conn,id,True)
    if not run_row['incident_id']:
     raise HTTPException(409,'Prepare a synthetic run before starting Bolna voice.')
    from sandbox.bolna_workflow import voice_purpose
    purpose=voice_purpose(run_row,expected_fingerprint)
    incident_id=str(run_row['incident_id'])
    incident_row=conn.execute('SELECT consent_active,consent_version,is_test FROM coordinator.incidents WHERE id=%s',(run_row['incident_id'],)).fetchone()
    if not incident_row or not incident_row['is_test'] or not incident_row['consent_active'] or incident_row['consent_version']!=run_row['consent_version']:
     raise HTTPException(409,'The synthetic run needs current investigation permission.')
   # Binding and all case reads stay inside the sandbox coordinator. The call
   # token is sent only from this trusted API to the local broker, never to UI.
   opened=core.post(f'/v1/sandbox/incidents/{incident_id}/audio-calls',json={
    'purpose':purpose,'audio_provenance':'BOLNA_WEBRTC'})
   call=checked(opened)
   call_id=call['call_id']
   context_response=core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']})
   context=checked(context_response)
   if context.get('incident_id')!=incident_id or context.get('call_id')!=call['call_id'] or context.get('simulated') is not True:
    raise HTTPException(409,'The synthetic call context did not match its run.')
   # The broker may spend 20s reviewing configuration, 20s minting,
   # then 5s securing the callback route. Do not abandon it mid-mint.
   with httpx.Client(timeout=50,follow_redirects=False) as broker:
    minted=broker.post(broker_url.rstrip('/')+'/session',headers={'Authorization':'Bearer '+broker_token},
     json={'call_token':call['call_token'],'recording_consent':body.recording_consent,'context':context})
   if minted.status_code!=201:
    raise HTTPException(503,'Bolna could not prepare the sandbox browser session. Review the run before retrying.')
   result=minted.json()
   if (result.get('transport')!='BOLNA_WEBRTC' or result.get('synthetic') is not True or result.get('phone_dispatch') is not False
       or result.get('call_id')!=call['call_id'] or result.get('assistant_config_sha256')!=expected_fingerprint
       or not isinstance(result.get('session'),dict)):
    raise HTTPException(502,'The broker returned an unverified voice session. No session was exposed.')
   try:execution_id=str(UUID(result['session']['run_id']))
   except (KeyError,ValueError,TypeError):
    raise HTTPException(502,'The browser session has no valid provider execution identity. No session was exposed.') from None
   bound=checked(core.post(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call["call_id"]}/bind-provider-execution',
    json={'execution_id':execution_id}))
   if bound.get('bound') is not True or bound.get('transport')!='BOLNA_WEBRTC' or bound.get('phone_dispatch') is not False:
    raise HTTPException(502,'The provider execution could not be bound to this synthetic conversation. No session was exposed.')
   with db() as conn:
    row=__import__('sandbox.runs',fromlist=['get']).get(conn,id,True)
    if voice_purpose(row,expected_fingerprint)!=purpose:
     core.post(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call["call_id"]}/abort')
     raise HTTPException(409,'The scenario changed while the provider session was prepared.')
    from psycopg.types.json import Jsonb
    conn.execute("UPDATE coordinator.sandbox_runs SET provider_configuration=%s,updated_at=now() WHERE id=%s",
     (Jsonb({'transport':'BOLNA_WEBRTC','assistant_config_sha256':expected_fingerprint}),id))
    conn.execute("INSERT INTO coordinator.sandbox_run_events(run_id,type,payload) VALUES(%s,'BOLNA_SESSION_MINTED',%s)",
     (id,Jsonb({'call_id':call['call_id'],'transport':'BOLNA_WEBRTC','assistant_config_sha256':expected_fingerprint,'phone_dispatch':False})))
   return {'call_id':call['call_id'],'transport':'BOLNA_WEBRTC','synthetic':True,
    'phone_dispatch':False,'assistant_config_sha256':expected_fingerprint,'session':result['session']}
  except HTTPException:
   if incident_id and call_id:
    try:core.post(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call_id}/abort')
    except Exception:pass
    try:hold_uncertain_session()
    except Exception:pass
   raise
  except Exception:
   if incident_id and call_id:
    try:core.post(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call_id}/abort')
    except Exception:pass
    try:hold_uncertain_session()
    except Exception:pass
   raise HTTPException(503,'The isolated Bolna session could not be prepared. Review the run before another attempt.') from None
 @app.post('/v2/sandbox/runs/{id}/clock')
 def advance_run_clock(id:UUID,body:AdvanceClock,request:Request):
  session(request,'sandbox')
  from sandbox.runs import advance_clock,public
  with db() as conn:return public(advance_clock(conn,id,body.seconds))
 return app
