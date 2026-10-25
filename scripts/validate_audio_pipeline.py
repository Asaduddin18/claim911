"""One-shot synthetic Pipecat integration check. Run from the workspace root.
Requires existing private profiles, provider configuration and the built images.
Refuses to repeat a prior validation identity; inspect its evidence first.
"""
import base64,json,subprocess,sys,time,wave
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,'outputs/claim911')
from sandbox.audio_gateway import AudioGateway,create_audio_app
from sandbox.spend import reserve,settle
from sandbox.stdio_control import run_worker
from coordinator.app import create_app
root=Path('work/claim911-runtime');cfg=json.loads((root/'sandbox/coordinator.json').read_text());providers=json.loads((root/'azure/provider.json').read_text())
statefile=root/'azure/pipecat-validation.json'
if statefile.exists():raise SystemExit('Prior audio gateway validation exists. Reconcile its evidence before a new run.')
run=str(uuid4());case=str(uuid4());active={};ids={'run_id':run,'case_id':case}
statefile.write_text(json.dumps(ids));statefile.chmod(0o600)
with TestClient(create_app(cfg)) as core:
 core.headers['Authorization']='Bearer '+cfg['operator_token']
 incident=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':case,'patient_id':'SYN-AUDIO-GATEWAY','reference_known':False,'title':'[Integration test] Isolated real Pipecat audio pipeline'}).json()['incident_id']
 core.post(f'/v1/incidents/{incident}/consent',json={'accepted':True,'confirmation':'Synthetic audio gateway evaluation investigation consent.'})
 ids['incident_id']=incident;statefile.write_text(json.dumps(ids))
 def consent(run_id,case_id,version):
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   row=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s AND case_id=%s',(incident,case_id)).fetchone()
  return run_id==run and bool(row and row['consent_active'] and row['consent_version']==version)
 def provider(operation,body):
  envelope={'environment':'sandbox','operation':operation,'body':body}
  if operation=='reply':envelope.update(model=providers['model'],reservation_id=active['request_id'])
  else:envelope['speech']=providers['speech']
  args=['docker','--context','colima-claim911-sandbox','run','--rm','-i','--network','claim911-provider-internal','-e','CLAIM911_EGRESS_PROXY=http://claim911-egress-proxy:3128','--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','32','--memory','128m','--cpus','0.5','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777','--entrypoint','python','claim911-speech-provider:local','-I','/app/one_request.py']
  r=subprocess.run(args,input=json.dumps(envelope)+'\n',capture_output=True,text=True,timeout=60)
  if r.returncode:raise RuntimeError('Trusted provider operation unavailable')
  return json.loads(r.stdout)
 class Speech:
  def transcribe(self,pcm,language):return provider('transcribe',{'pcm_base64':base64.b64encode(pcm).decode(),'language':language})
  def synthesize(self,text,language):return base64.b64decode(provider('synthesize',{'text':text,'language':language})['pcm_base64'],validate=True)
 class Model:
  def reply(self,messages):return provider('reply',{'messages':messages})
 def reserve_cost(request_id,run_id,operation):
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   result=reserve(conn,request_id=request_id,run_id=run_id,phase='integration',operation=operation,maximum_micro=100000)
   if not result['new_reservation']:raise RuntimeError('Prior paid request requires reconciliation')
  active['request_id']=request_id
 def finish_cost(request_id):
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:settle(conn,request_id)
 gateway=AudioGateway(speech=Speech(),model=Model(),reserve_cost=reserve_cost,finish_cost=finish_cost,consent_active=consent)
 token=gateway.issue(run_id=run,case_id=case,role='medical_records',language='en',consent_version=1,
  context='The caregiver reports that the discharge summary needs a signature. Ask the medical records desk who can obtain the authorized signature. No signed summary or verified institution outcome is available.',ttl=600)
 with wave.open('outputs/Claim911_Azure_Speech_en.wav','rb') as source:pcm=source.readframes(source.getnframes())
 started=time.monotonic();worker=run_worker(gateway,token,pcm,timeout=150);duration=time.monotonic()-started
 audio=worker.pop('audio')
 with wave.open('outputs/Claim911_Pipecat_Response.wav','wb') as wav:
  wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(audio)
 gateway.revoke_run(run)
 result={'provenance':'ISOLATED_PIPECAT_REAL_STT_MODEL_TTS','synthetic':True,'run_id':run,'incident_id':incident,
  'input_audio_source':'Previously generated synthetic Azure TTS fixture','agent_response':worker['text'],
  'events':worker['events'],'total_seconds':round(duration,3),'audio_file':'Claim911_Pipecat_Response.wav',
  'reserved_cost_upper_bound_usd':0.1,'actual_billed_cost':'AWAITING_PROVIDER_TELEMETRY',
  'worker_network':'none','credentials_sent_to_worker':False,
  'institution_tools_executed':False,'pipecat_pipeline_executed':True,'pipecat_evals_transport_executed':False,
  'full_case_workflow_executed':False,'session_revoked':True}
 Path('outputs/Claim911_Pipecat_Real_Audio_Validation.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result))
