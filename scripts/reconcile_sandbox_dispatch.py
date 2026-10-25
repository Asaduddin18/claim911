"""Inspect and reconcile one interrupted synthetic dispatch. Never submit a packet."""
import argparse,json,sys
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.app import create_app
from simulator.app import create_app as simulator
from sandbox.reconciliation import reconcile_dispatch


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime',required=True);parser.add_argument('--run-id',required=True,type=UUID);parser.add_argument('--kind',choices=['dispatch','followup'],default='dispatch');args=parser.parse_args()
 root=Path(args.runtime)/'sandbox';cfg=json.loads((root/'coordinator.json').read_text());sim=json.loads((root/'simulator.json').read_text())
 if cfg.get('environment')!='sandbox' or sim.get('environment')!='sandbox' or cfg.get('bolna_api_key') or cfg.get('live_calls_enabled'):
  raise RuntimeError('Isolated non-phone profiles required')
 with TestClient(create_app(cfg)) as core,TestClient(simulator(sim)) as institutions:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   if args.kind=='dispatch':result=reconcile_dispatch(conn,args.run_id,core=core,institutions=institutions,hospital_token=sim['tokens']['hospital'])
   else:
    from sandbox.reconciliation import reconcile_followup
    from sandbox.checkpoints import CheckpointVerifier
    verifier=CheckpointVerifier(core,institutions,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
    result=reconcile_followup(conn,args.run_id,core=core,institutions=institutions,claims_token=sim['tokens']['claims'],hospital_token=sim['tokens']['hospital'],verifier=verifier)
 print(json.dumps({'run_id':str(args.run_id),**result}))


if __name__=='__main__':main()
