"""Provision a synthetic case for calls to a user-approved verified participant.

Does not place a call. Never infers consent from mere account ownership.
"""
import argparse
import json
from pathlib import Path
from uuid import uuid4
import httpx


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);args=p.parse_args()
    runtime=Path(args.runtime);meta=runtime/'live-case.json'
    if meta.exists():
        print('A live case is already provisioned. Reuse its saved identifiers; no new case was created.')
        return
    sim=json.loads((runtime/'simulator.json').read_text());core=json.loads((runtime/'coordinator.json').read_text())
    participant=json.loads((runtime/'test-participant.json').read_text())
    if not all(participant.get(x) for x in ['verified_in_bolna','owner_consents_to_calls','owner_consents_to_recording']):
        raise SystemExit('Explicit verified-participant and recording consent required for this rehearsal.')
    with httpx.Client(timeout=15) as client:
        r=client.post('http://127.0.0.1:8111/evaluator/runs',headers={'Authorization':'Bearer '+sim['tokens']['evaluator']},json={})
        r.raise_for_status();case=r.json()['case_id']
        headers={'Authorization':'Bearer '+core['operator_token']}
        r=client.post('http://127.0.0.1:8110/v1/intakes',headers=headers|{'Idempotency-Key':str(uuid4())},json={
            'case_id':case,'title':'Live voice rehearsal / synthetic final authorization'})
        r.raise_for_status();incident=r.json()['incident_id'];prefix='http://127.0.0.1:8110/v1/incidents/'+incident
        r=client.post(prefix+'/consent',headers=headers,json={'accepted':True,
            'confirmation':'User explicitly authorized an end-to-end synthetic voice test using their own verified number. No real patient case.'})
        r.raise_for_status();people={}
        for role in ['hospital','claims','caregiver']:
            r=client.post(prefix+'/participants',headers=headers,json={'role':role,'phone':participant['phone'],
                'verified':True,'demo_consent':participant['consent_source'],'recording_consent':True})
            r.raise_for_status();people[role]=r.json()['participant_id']
        meta.write_text(json.dumps({'case_id':case,'incident_id':incident,'participants':people,
                                   'mode':'REAL_CALLS_SYNTHETIC_INSURANCE'},indent=2));meta.chmod(0o600)
        print('Synthetic live-call case provisioned. Case ID:',case)
        print('Incident ID:',incident)
        print('Three role registrations use the single user-approved number. No call placed yet.')


if __name__=='__main__':main()
