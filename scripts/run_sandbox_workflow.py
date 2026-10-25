"""Run the complete synthetic workflow with the same independent evidence gates.

Defaults to the preserved case. --fresh explicitly creates a new auditable run;
old runs and recordings are retained. No real telephone dispatch is available.
"""
import argparse,json,sys,shutil,traceback,re
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.app import create_app
from simulator.app import create_app as institution_app
from sandbox import runs
from sandbox.executor import ScenarioExecutor
from sandbox.workflow_services import WorkflowServices
from sandbox.audio_transport import AudioConversation
from sandbox.bolna_browser_transport import BolnaBrowserConversation
from sandbox.provider_control import DockerProvider
from sandbox.checkpoints import CheckpointVerifier


def preserved_bolna_conversations(directory,run_id,configuration,accepted_fingerprints=()):
 """Retain successful phases of this same case across explicit resumptions."""
 calls={};sources=[];accepted=set(accepted_fingerprints)|{configuration.get('assistant_config_sha256')}
 for path in sorted(Path(directory).glob('Claim911_Run_'+str(run_id)+'_*.json')):
  try:
   report=json.loads(path.read_text())
   prior=report.get('provider_configuration',{})
   if report.get('run_id')!=str(run_id) or prior.get('transport')!=configuration.get('transport') or prior.get('assistant_config_sha256') not in accepted:continue
   used=False
   for call in report.get('conversations',[]):
    if (call.get('archived') is True and call.get('provenance')=='BOLNA_WEBRTC'
        and call.get('assistant_config_sha256') in accepted
        and call.get('semantic_dialogue_evaluation',{}).get('conversation_quality_passed') is True):
     calls[call['call_id']]=call;used=True
   if used:sources.append(str(path))
  except (OSError,ValueError,KeyError,TypeError):continue
 return list(calls.values()),sources


def main():
 parser=argparse.ArgumentParser();selection=parser.add_mutually_exclusive_group();selection.add_argument('--fresh',action='store_true');selection.add_argument('--run-id',type=str);parser.add_argument('--language',choices=['en','hi'],default='en');parser.add_argument('--until-checkpoint',type=int,choices=range(1,14),default=13);parser.add_argument('--participant-mode',choices=['scripted','adaptive'],default='adaptive');parser.add_argument('--transport',choices=['bolna-browser','pipecat'],default='bolna-browser');parser.add_argument('--bolna-browser-url',default='http://127.0.0.1:3130/');parser.add_argument('--node',default=shutil.which('node') or 'node')
 parser.add_argument('--runtime',type=Path)
 parser.add_argument('--component',choices=['hospital_references_reported','claims_query_discovered'])
 parser.add_argument('--prepare-only',action='store_true')
 parser.add_argument('--single-step',action='store_true')
 parser.add_argument('--participant-evaluation')
 parser.add_argument('--phase',choices=['development','rehearsal','reserve'],default='development')
 args=parser.parse_args()
 if args.component and not args.fresh:parser.error("Component tests require --fresh")
 workspace=Path(__file__).resolve().parents[3]
 root=(args.runtime or workspace/'work/claim911-runtime').resolve();statefile=root/'sandbox/active_audio_case.json'
 cfg=json.loads((root/'sandbox/coordinator.json').read_text());sim=json.loads((root/'sandbox/simulator.json').read_text())
 if cfg['environment']!='sandbox' or sim['environment']!='sandbox' or cfg.get('bolna_api_key') or cfg.get('live_calls_enabled'):
  raise RuntimeError('Isolated non-phone profiles required')
 from sandbox.local_preflight import run_local_preflight
 local_preflight=run_local_preflight(Path(__file__).resolve().parents[1])
 from sandbox.spend import require_testing
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:require_testing(conn)
 provider=DockerProvider(json.loads((root/'azure/provider.json').read_text()))
 participant_gate=None
 if args.transport=='bolna-browser' and args.participant_mode=='adaptive':
  from sandbox.participant_evaluation import require_participant_gate
  default_gate=root/'sandbox/participant-text-gate.json'
  if not default_gate.exists():default_gate=workspace/'outputs/Claim911_Participant_Text_Fresh_Evaluation.json'
  participant_gate=require_participant_gate(args.participant_evaluation or default_gate,
   Path(__file__).resolve().parents[1],provider.image_id)
 bolna_fingerprint=cfg.get('sandbox_bolna_agent_config_sha256')
 if args.transport=='bolna-browser' and (not isinstance(bolna_fingerprint,str) or len(bolna_fingerprint)!=64):
  raise RuntimeError('The reviewed Bolna browser assistant fingerprint is missing from the private sandbox profile')
 public_provider=({'transport':'BOLNA_WEBRTC','assistant_config_sha256':bolna_fingerprint}
                  if args.transport=='bolna-browser' else
                  {'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'})
 def db():return psycopg.connect(cfg['dsn'],row_factory=dict_row)
 with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as env:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  with db() as conn:runs.initialize(conn,environment='sandbox')
  if args.fresh:
   previous=json.loads(statefile.read_text()) if statefile.exists() else None
   if previous:
    with db() as conn:
     old=runs.get(conn,previous['run_id'])
     if old['state'] in {'RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'}:raise RuntimeError('Stop or reconcile the existing execution before preparing a fresh case')
   seed=env.post('/evaluator/complex-runs',headers={'Authorization':'Bearer '+sim['tokens']['evaluator']});seed.raise_for_status();seed=seed.json()
   intake={'case_id':seed['case_id'],'patient_id':seed['patient_id'],'reference_known':False,'title':'Synthetic complete audio discharge coordination'}
   if args.component=='claims_query_discovered':
    # Explicit stage fixture, not a fabricated prior voice checkpoint. Read only
    # the new institution's own reference; never clone old reports or archives.
    source=env.get(f'/hospital/complex/{seed["case_id"]}/desks/insurance',headers={'Authorization':'Bearer '+sim['tokens']['hospital']})
    source.raise_for_status()
    intake.update(reference_known=True,reference=source.json()['references']['final_request'],title='[Component fixture] Claims query discovery with supplied final reference')
   created=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json=intake);created.raise_for_status();id=created.json()['incident_id']
   consent=core.post(f'/v1/incidents/{id}/consent',json={'accepted':True,'confirmation':'Explicit synthetic caregiver fixture permits this isolated scenario investigation. Exact document sharing is separately approved at its dedicated checkpoint.'});consent.raise_for_status()
   with db() as conn:
    run=runs.create(conn,language=args.language,origin='AUDIO_DEMONSTRATION',component=args.component)
    runs.attach_case(conn,run['id'],incident_id=id,institution_case_id=seed['case_id'],provider_configuration=public_provider)
    if previous:runs.event(conn,run['id'],'FRESH_SCENARIO_REQUESTED',{'previous_run_id':previous['run_id'],'previous_evidence_preserved':True})
   identity={'run_id':str(run['id']),'incident_id':id,'institution_case_id':seed['case_id'],'checkpoint':0}
   statefile.write_text(json.dumps(identity,indent=2));statefile.chmod(0o600)
  elif args.run_id:
   from uuid import UUID
   with db() as conn:selected=runs.get(conn,UUID(args.run_id))
   if selected['origin'] not in {'USER_PREPARED','AUDIO_DEMONSTRATION'}:raise RuntimeError('Regression fixtures cannot start paid audio execution')
   if not selected['incident_id']:raise RuntimeError('The selected run must be bound before execution')
   if selected['provider_configuration']!=public_provider:raise RuntimeError('The selected run was prepared for a different assistant transport or configuration')
   identity={'run_id':str(selected['id']),'incident_id':str(selected['incident_id']),'institution_case_id':str(selected['institution_case_id']),'checkpoint':selected['checkpoint']}
   # Explicit job selection must never overwrite another run's active identity.
   statefile=root/'sandbox'/('run-'+identity['run_id']+'.json')
  else:
   if not statefile.exists():raise RuntimeError('No preserved case. Use --fresh to explicitly prepare one.')
   identity=json.loads(statefile.read_text())
  if args.prepare_only:
   print(json.dumps({'state':'PREPARED_ONLY','run_id':identity['run_id'],'provider_sessions_started':0,'component':args.component}),flush=True)
   return
  verifier=CheckpointVerifier(core,env,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
  if participant_gate:
   with db() as conn:runs.event(conn,identity['run_id'],'PARTICIPANT_TEXT_GATE_PASSED',
    participant_gate|{'participant_provider_image':provider.image_id,'spend_phase':args.phase})
  holder={}
  services=WorkflowServices(core,env,incident_id=identity['incident_id'],case_id=identity['institution_case_id'],tokens=sim['tokens'],authorized=lambda:bool(holder) and holder['executor'].authorized())
  with db() as conn:current=runs.get(conn,identity['run_id'])
  if current['provider_configuration']!=public_provider:raise RuntimeError('The preserved run was prepared for a different assistant transport or configuration')
  if args.transport=='bolna-browser':
   project=Path(__file__).resolve().parents[1]
   transport=BolnaBrowserConversation(core=core,services=services,provider=provider,db=db,
    run_id=identity['run_id'],sandbox_profile=root/'sandbox/coordinator.json',
    provider_profile=root/'azure/provider.json',browser_url=args.bolna_browser_url,node=args.node,
    harness_path=project/'product/scripts/sandbox-bolna-participant-harness.mjs',
    runtime_root=root,max_turns=12,participant_mode=args.participant_mode,spend_phase=args.phase)
  else:
   transport=AudioConversation(core=core,services=services,provider=provider,db=db,run_id=identity['run_id'],language=current['language'],journal_root=root/'sandbox/conversations',participant_mode=args.participant_mode)
  executor=ScenarioExecutor(db=db,run_id=identity['run_id'],services=services,verifier=verifier,conversation=transport,clock_start='2026-10-23T11:40:00+05:30');holder['executor']=executor
  report_path=workspace/'outputs'/('Claim911_Run_'+identity['run_id']+'_'+uuid4().hex[:12]+'.json')
  started=datetime.now(timezone.utc).isoformat();failure=None
  try:
   for _ in range(20):
    with db() as conn:current=runs.get(conn,identity['run_id'])
    if current['checkpoint']>=args.until_checkpoint or current['state']=='COMPLETED':break
    result=executor.step();print(json.dumps(result),flush=True)
    with db() as conn:current=runs.get(conn,identity['run_id'])
    identity.update(checkpoint=current['checkpoint'],state=current['state'],stage=result.get('verified_checkpoint',result['state']))
    if transport.reports:identity['call_id']=transport.reports[-1]['call_id']
    statefile.write_text(json.dumps(identity,indent=2))
    if args.single_step:break
    if result['state']=='WAITING_CALLBACK':
     with db() as conn:runs.advance_clock(conn,identity['run_id'],60)
   else:raise RuntimeError('Run exceeded the bounded phase/callback iteration limit')
  except Exception as exc:
   frames=traceback.extract_tb(exc.__traceback__)
   location=None
   if frames:
    frame=frames[-1]
    filename=Path(frame.filename).name
    if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',filename) and re.fullmatch(r'[A-Za-z0-9_]{1,100}',frame.name):
     location={'file':filename,'function':frame.name,'line':frame.lineno}
   failure={'error_type':type(exc).__name__,'boundary':getattr(exc,'diagnostic',None),
            'failure_location':location,'automatic_retry':False}
   print(json.dumps({'state':'REVIEW_REQUIRED',**failure}),flush=True)
  finally:
   with db() as conn:current=runs.get(conn,identity['run_id'])
   identity.update(checkpoint=current['checkpoint'],state=current['state']);statefile.write_text(json.dumps(identity,indent=2))
   with db() as conn:
    rotations=[r['payload'] for r in conn.execute("SELECT payload FROM coordinator.sandbox_run_events WHERE run_id=%s AND type='BOLNA_GATEWAY_ROTATION_REVIEWED' ORDER BY created_at DESC",(identity['run_id'],))]
   accepted={current['provider_configuration'].get('assistant_config_sha256')}
   for rotation in rotations:
    if rotation.get('gateway_only') is True and rotation.get('new_fingerprint') in accepted and len(rotation.get('behavior_sha256',''))==64:
     accepted.add(rotation['old_fingerprint'])
   retained,sources=preserved_bolna_conversations(workspace/'outputs',identity['run_id'],current['provider_configuration'],accepted) if args.transport=='bolna-browser' else ([],[])
   combined={call['call_id']:call for call in retained}
   combined.update({call['call_id']:call for call in transport.reports})
   report={'run_id':identity['run_id'],'incident_id':identity['incident_id'],'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
    'state':current['state'],'verified_checkpoints':current['checkpoint'],'required_checkpoints':len(current['manifest']['checkpoints']),
    'scenario_version':current['scenario_version'],'scenario_faults':current['faults'],'provider_image':provider.image_id,'assistant_transport':args.transport,'provider_configuration':current['provider_configuration'],'phone_dispatch':False,'synthetic':True,
    'execution_scope':current['manifest'].get('execution_scope','FULL_CASE'),
    'component_completed':current['manifest'].get('execution_scope')=='COMPONENT' and current['state']=='COMPLETED',
    'full_case_completed':runs.full_case_completed(current),'conversations':list(combined.values()),'retained_phase_reports':sources,'reviewed_gateway_rotations':rotations,'execution_resumed':not args.fresh,'institution_operations':services.audit,'failure':failure,
    'independent_evaluation':verifier.audit(identity['incident_id']) if runs.full_case_completed(current) else None}
   report_path.write_text(json.dumps(report,indent=2,default=str))
  if failure:raise SystemExit(1)


if __name__=='__main__':main()
