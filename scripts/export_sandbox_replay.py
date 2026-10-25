"""Export a completed, independently verified synthetic audio run as an offline replay."""
import argparse,json,sys
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.app import create_app
from simulator.app import create_app as simulator
from sandbox.checkpoints import CheckpointVerifier
from sandbox.replay import export


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime',required=True);parser.add_argument('--run-id',required=True,type=UUID);parser.add_argument('--output',required=True);args=parser.parse_args()
 root=Path(args.runtime)/'sandbox';cfg=json.loads((root/'coordinator.json').read_text());sim=json.loads((root/'simulator.json').read_text())
 if cfg.get('environment')!='sandbox' or sim.get('environment')!='sandbox':raise ValueError('Isolated sandbox profiles required')
 with TestClient(create_app(cfg)) as core,TestClient(simulator(sim)) as institutions:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  verifier=CheckpointVerifier(core,institutions,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   path=export(conn,args.run_id,core=core,verifier=verifier,destination=args.output)
 print(str(path.resolve()))


if __name__=='__main__':main()
