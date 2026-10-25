"""Resume a reviewed synthetic callback without discarding prior evidence.

Reads the exact provider execution and institution state. Does not place a call,
change an institution record, or award a checkpoint.
"""
import argparse,json,sys
from pathlib import Path
from datetime import datetime,timedelta
import httpx,psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.app import create_app
from coordinator.callbacks import reschedule_after_review
from simulator.app import create_app as institution_app
from sandbox import runs
from sandbox.checkpoints import CheckpointVerifier
from scripts.reconcile_bolna_mint import terminal_evidence


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 for key in ('runtime','run-id','callback-id','report','reason'):parser.add_argument('--'+key,required=True)
 args=parser.parse_args();root=Path(args.runtime)/'sandbox'
 cfg=json.loads((root/'coordinator.json').read_text());sim=json.loads((root/'simulator.json').read_text());broker=json.loads((root/'bolna-session-broker.json').read_text())
 if cfg['environment']!='sandbox' or sim['environment']!='sandbox' or cfg.get('live_calls_enabled') or cfg.get('bolna_api_key'):raise ValueError('Isolated sandbox profiles required')
 report=json.loads(Path(args.report).read_text())
 if report['run_id']!=args.run_id or report['participant_role']!='medical_records':raise ValueError('A matching records callback report is required')
 with httpx.Client(timeout=20,follow_redirects=False) as client:
  response=client.get('https://api.bolna.ai/executions/'+report['provider_execution_id'],headers={'Authorization':'Bearer '+broker['bolna_api_key']});response.raise_for_status();provider=response.json()
 with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as institutions:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  verifier=CheckpointVerifier(core,institutions,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   run=runs.get(conn,args.run_id,True)
   if run['state']!='UNCERTAIN' or run['lease_token'] is not None:raise ValueError('A stopped uncertain run is required')
   terminal_evidence(provider,run_id=args.run_id,call_id=report['call_id'],incident_id=run['incident_id'],execution_id=report['provider_execution_id'])
   for key in run['manifest']['checkpoints'][:run['checkpoint']]:
    if not verifier.inspect(key,str(run['incident_id']))['passed']:raise ValueError('Earlier checkpoint evidence no longer verifies')
   snapshot=core.get('/v1/incidents/'+str(run['incident_id']));snapshot.raise_for_status()
   own=institutions.get('/hospital/complex/'+str(run['institution_case_id'])+'/desks/medical_records',headers={'Authorization':'Bearer '+sim['tokens']['hospital']});own.raise_for_status()
   now=datetime.fromisoformat('2026-10-23T11:40:00+05:30')+timedelta(seconds=run['elapsed_seconds'])
   replacement=reschedule_after_review(conn,snapshot.json(),args.callback_id,args.reason,now=now)
   conn.execute("UPDATE coordinator.sandbox_runs SET state='PAUSED',updated_at=now() WHERE id=%s",(args.run_id,))
   runs.event(conn,args.run_id,'CALLBACK_REVIEW_COMPLETED',{'replacement_callback_id':str(replacement['id']),'provider_execution_id':report['provider_execution_id'],'prior_attempts_preserved':True,'checkpoint_advanced':False,'institution_document_ready':own.json()['documents'][0]['ready']})
 print(json.dumps({'state':'PAUSED','checkpoint':run['checkpoint'],'provider_sessions_started':0,'institution_writes':0,'prior_attempts_preserved':True}))


if __name__=='__main__':main()
