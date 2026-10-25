"""Summarize existing local usage evidence without provider requests or writes."""
import argparse,json,sys
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sandbox.cost_report import summarize


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output)
    if output.exists():raise ValueError('Preserve earlier evidence; choose a fresh output path')
    config=json.loads((Path(args.runtime)/'sandbox/coordinator.json').read_text())
    database=conninfo_to_dict(config['dsn'])
    if config.get('environment')!='sandbox' or database.get('host') not in {'127.0.0.1','localhost','::1'} or not database.get('dbname','').startswith('claim911_sandbox'):
        raise ValueError('Explicit local sandbox storage required')
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        budget=conn.execute('SELECT suspended FROM coordinator.sandbox_budget WHERE id=1').fetchone()
        rows=conn.execute('SELECT phase,operation,state,reserved_micro,charged_micro,cost_evidence FROM coordinator.sandbox_spend').fetchall()
    report=summarize(budget,rows);report['generated_at']=datetime.now(timezone.utc).isoformat()
    with output.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({key:report[key] for key in ['scope','paid_testing_suspended','requests','recorded_confirmed_charges_usd','unreconciled_reservation_holds_usd','billing_reconciled','provider_requests','ledger_writes']}))


if __name__=='__main__':main()
