"""Reconcile a captured call after offline checks, without another voice call.

Requires retained provider-bound audio, fresh semantic review and independent
checkpoint verification. Original failure reports and run events are retained.
"""
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.app import create_app
from simulator.app import create_app as institution_app
from sandbox.bolna_browser_transport import BolnaBrowserConversation
from sandbox.provider_control import DockerProvider
from sandbox.dialogue_quality import evaluate_dialogue
from sandbox.checkpoints import CheckpointVerifier
from sandbox.reconciliation import reconcile_verified_checkpoint
from sandbox import runs
from sandbox.dialogue_evidence import dialogue_facts


def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--report',required=True)
 p.add_argument('--archive',required=True);p.add_argument('--facts',required=True);p.add_argument('--output',required=True);args=p.parse_args()
 root=Path(args.runtime);cfg=json.loads((root/'sandbox/coordinator.json').read_text());sim=json.loads((root/'sandbox/simulator.json').read_text())
 report=json.loads(Path(args.report).read_text());archive=json.loads(Path(args.archive).read_text());facts=json.loads(Path(args.facts).read_text());out=Path(args.output)
 if out.exists():raise ValueError('Preserve existing reconciliation reports')
 if cfg['environment']!='sandbox' or facts.get('synthetic') is not True or facts.get('role')!=report['participant_role']:
  raise ValueError('Role-bound synthetic context required')
 if report['provider_execution_id']!=archive['execution_id']:raise ValueError('Provider identity mismatch')
 def db():return psycopg.connect(cfg['dsn'],row_factory=dict_row)
 with db() as conn:
  run=runs.get(conn,report['run_id']);call=conn.execute('SELECT purpose,incident_id FROM coordinator.calls WHERE id=%s',(report['call_id'],)).fetchone()
 if str(call['incident_id'])!=str(run['incident_id']):raise ValueError('Call belongs to a different run')
 transport=object.__new__(BolnaBrowserConversation);transport.db=db;transport.run_id=report['run_id']
 transport.provider=DockerProvider(json.loads((root/'azure/provider.json').read_text()));transport._active_authorized=None;transport.spend_phase='reserve'
 with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as env:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  snapshot=core.get('/v1/incidents/'+str(run['incident_id']));snapshot.raise_for_status()
  quality=evaluate_dialogue(transcript=[{'speaker':t['speaker'],'text':t['text']} for t in archive['turns']],
   participant_role=report['participant_role'],known_facts=dialogue_facts(facts,snapshot.json()),invoke=transport._invoke,assistant_provider='BOLNA_WEBRTC',
   expected_exchanges=[{k:t[k] for k in ('assistant_text','participant_text')} for t in report['turns']])
  if not quality['conversation_quality_passed']:raise RuntimeError('Captured conversation still needs human review: '+str(quality['critical_failures']))
  response=core.post(f'/v1/sandbox/incidents/{run["incident_id"]}/audio-calls/{report["call_id"]}/browser-archive',json=archive)
  response.raise_for_status()
  verifier=CheckpointVerifier(core,env,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
  with db() as conn:reconciled=reconcile_verified_checkpoint(conn,report['run_id'],verifier=verifier)
 now=datetime.now(timezone.utc).isoformat()
 result={'run_id':report['run_id'],'incident_id':str(run['incident_id']),'provider_configuration':run['provider_configuration'],
  'started_at':now,'finished_at':now,'state':'PAUSED','verified_checkpoints':reconciled['checkpoint'],
  'conversations':[{'archived':True,'call_id':report['call_id'],'execution_id':archive['execution_id'],
   'purpose':call['purpose'],'role':report['participant_role'],'provenance':'BOLNA_WEBRTC',
   'assistant_config_sha256':archive['assistant_config_sha256'],'semantic_dialogue_evaluation':quality,
   'sandbox_report':str(Path(args.report).resolve()),'evidence_recovered_from_existing_recording':True,
   'new_voice_session':False}],'original_failure_preserved':True,'new_voice_sessions':0}
 with out.open('x') as f:json.dump(result,f,indent=2)
 print(json.dumps(reconciled))


if __name__=='__main__':main()
