"""Read one known Bolna execution and preserve its terminal synthetic binding.

Does not mint, connect, retry, advance a checkpoint, or release a review hold.
"""
import argparse,json,sys
from pathlib import Path
from uuid import UUID
from datetime import datetime,timezone
import httpx,psycopg
from psycopg.types.json import Jsonb
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def terminal_evidence(record,*,run_id,call_id,incident_id,execution_id):
    if str(record.get('id'))!=str(execution_id):raise ValueError('Execution identity mismatch')
    data=(record.get('context_details') or {}).get('recipient_data') or {}
    context=data.get('claim911_context') or {}
    if isinstance(context,str):context=json.loads(context)
    if (data.get('claim911_case_id')!=str(incident_id) or context.get('call_id')!=str(call_id)
        or context.get('simulated') is not True):raise ValueError('Synthetic call binding mismatch')
    if record.get('status') not in {'completed','failed','stopped','balance-low','no-answer','busy','canceled','cancelled'}:
        raise ValueError('Provider execution is not confirmed terminal')
    return {'run_id':str(run_id),'call_id':str(call_id),'execution_id':str(execution_id),
        'provider_status':record['status'],'conversation_duration':record.get('conversation_duration'),
        'synthetic_binding_verified':True,'run_remains_uncertain':True,'checkpoint_pass':False,
        'observed_at':datetime.now(timezone.utc).isoformat(),'automatic_retry':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True)
    parser.add_argument('--recover-unconnected',action='store_true',help='Reopen the same checkpoint only after a failed, zero-duration session with no speech or tools.')
    for key in ('run-id','call-id','execution-id'):parser.add_argument('--'+key,required=True,type=UUID)
    args=parser.parse_args();root=Path(args.runtime).resolve()/'sandbox'
    cfg=json.loads((root/'coordinator.json').read_text());broker=json.loads((root/'bolna-session-broker.json').read_text())
    if cfg.get('environment')!='sandbox' or cfg.get('bolna_api_key') or cfg.get('live_calls_enabled'):
        raise ValueError('Isolated non-phone sandbox profile required')
    with psycopg.connect(cfg['dsn']) as db:
        row=db.execute('SELECT incident_id,state FROM coordinator.sandbox_runs WHERE id=%s',(args.run_id,)).fetchone()
        if not row or row[1]!='UNCERTAIN':raise ValueError('An uncertain synthetic run is required')
        call=db.execute('SELECT 1 FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode=%s',
            (args.call_id,row[0],'SANDBOX_AUDIO')).fetchone()
        if not call:raise ValueError('Call does not belong to this synthetic run')
        with httpx.Client(timeout=20,follow_redirects=False) as client:
            response=client.get('https://api.bolna.ai/executions/'+str(args.execution_id),headers={'Authorization':'Bearer '+broker['bolna_api_key']})
            response.raise_for_status()
        evidence=terminal_evidence(response.json(),run_id=args.run_id,call_id=args.call_id,incident_id=row[0],execution_id=args.execution_id)
        db.execute('INSERT INTO coordinator.sandbox_run_events(run_id,type,payload) VALUES(%s,%s,%s)',
            (args.run_id,'BOLNA_MINT_RECONCILED_TERMINAL',Jsonb(evidence)))
        if args.recover_unconnected:
            record=response.json()
            if not unconnected_without_actions(record):raise ValueError('The session is not a proven unconnected failure')
            active=db.execute("SELECT 1 FROM coordinator.calls WHERE incident_id=%s AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER') LIMIT 1",(row[0],)).fetchone()
            if active:raise ValueError('An active local conversation still requires reconciliation')
            db.execute("UPDATE coordinator.sandbox_runs SET state='PAUSED',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s AND state='UNCERTAIN' AND lease_token IS NULL",(args.run_id,))
            db.execute('INSERT INTO coordinator.sandbox_run_events(run_id,type,payload) VALUES(%s,%s,%s)',
                (args.run_id,'UNCONNECTED_SESSION_RECONCILED',Jsonb({'execution_id':str(args.execution_id),'checkpoint_advanced':False,'provider_duration':0,'automatic_retry':False})))
            evidence.update(run_remains_uncertain=False,state='PAUSED',checkpoint_advanced=False)
    print(json.dumps(evidence))


def unconnected_without_actions(record):
    return (record.get('status')=='failed' and record.get('conversation_duration')==0
            and not record.get('transcript') and record.get('tool_call_logs')==[])


if __name__=='__main__':main()
