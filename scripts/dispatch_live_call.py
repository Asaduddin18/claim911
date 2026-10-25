"""Place one explicitly approved test call and reconcile its known execution.

Saved job identity makes restarts safe. Re-running a purpose does not place a second call.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.worker import work_once,poll_once,process_webhook_once


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True)
    p.add_argument('--purpose',choices=['HOSPITAL_INITIAL','CLAIMS_LOOKUP','HOSPITAL_FOLLOWUP','CORRECTION_REQUEST','CAREGIVER_UPDATE'],required=True)
    p.add_argument('--action-id');p.add_argument('--attempt',type=int,choices=[1,2,3],default=1);args=p.parse_args()
    runtime=Path(args.runtime);cfg=json.loads((runtime/'coordinator.json').read_text())
    meta=json.loads((runtime/'live-case.json').read_text())
    participant=json.loads((runtime/'test-participant.json').read_text())
    if cfg.get('outbound_paused'):
        raise SystemExit('Calls are on hold pending participant readiness. No dispatch attempted.')
    if not cfg.get('live_calls_enabled') or not participant.get('owner_consents_to_calls'):
        raise SystemExit('Live calling and explicit participant consent are required.')
    roles={'HOSPITAL_INITIAL':'hospital','CLAIMS_LOOKUP':'claims','HOSPITAL_FOLLOWUP':'hospital',
           'CORRECTION_REQUEST':'hospital','CAREGIVER_UPDATE':'caregiver'}
    headers={'Authorization':'Bearer '+cfg['operator_token']}
    prefix='http://127.0.0.1:8110/v1/incidents/'+meta['incident_id']
    with httpx.Client(headers=headers,timeout=20) as client:
        calls=meta.setdefault('calls',{})
        purpose_key=args.purpose if args.attempt==1 else args.purpose+':'+str(args.attempt)
        if purpose_key not in calls:
            body={'participant_id':meta['participants'][roles[args.purpose]],'purpose':args.purpose,'action_id':args.action_id}
            r=client.post(prefix+'/call-jobs',json=body,headers={'Idempotency-Key':'live-'+meta['incident_id']+'-'+purpose_key})
            r.raise_for_status();calls[purpose_key]=r.json()
            (runtime/'live-case.json').write_text(json.dumps(meta,indent=2))
        job=calls[purpose_key]
        work_once(cfg,job_id=job['job_id'])
        print('Test-call job processed. Monitoring only the saved call identity.',flush=True)
        prior=None;deadline=time.monotonic()+190
        while time.monotonic()<deadline:
            poll_once(cfg,call_id=job['call_id'])
            for _ in range(10):
                if not process_webhook_once(cfg):break
            r=client.get(prefix);r.raise_for_status();data=r.json()
            call=next(c for c in data['calls'] if c['id']==job['call_id'])
            if call['state']!=prior:
                print('Call state:',call['state'],'provider execution saved:',bool(call['execution_id']),flush=True)
                prior=call['state']
            if call['state'] in ['COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER','DISPATCH_UNKNOWN']:
                if call['state']=='COMPLETED' and not call['transcript']:
                    time.sleep(3);continue
                print('Transcript segments:',len(call['transcript']),'attributed statements:',len(data['assertions']),
                      'recording available:',bool(call['recording_url']),'incident state:',data['incident']['state'],flush=True)
                (runtime/('last-live-'+args.purpose.lower()+'.json')).write_text(json.dumps(data,indent=2))
                if call['state']!='COMPLETED':
                    raise SystemExit('Call did not complete; inspect the saved state before any new attempt.')
                return
            time.sleep(3)
        raise SystemExit('Call monitor reached its deadline. Preserve its identity and reconcile before another attempt.')


if __name__=='__main__':main()
