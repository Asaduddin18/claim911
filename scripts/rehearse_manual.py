"""Exercise a complete manual reconstruction through institution and coordinator APIs.

This does not make phone calls. Every conversation is labeled MANUAL_RECONSTRUCTION.
"""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone

import httpx


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime',required=True)
    p.add_argument('--report',required=True)
    args=p.parse_args();runtime=Path(args.runtime)
    sim=json.loads((runtime/'simulator.json').read_text())
    core=json.loads((runtime/'coordinator.json').read_text())
    checks=[]
    def check(name,condition):
        if not condition:
            raise AssertionError(name)
        checks.append({'check':name,'passed':True})
    with httpx.Client(base_url='http://127.0.0.1:8111',timeout=10) as institutions, httpx.Client(
        base_url='http://127.0.0.1:8110',timeout=10,headers={'Authorization':'Bearer '+core['operator_token']}) as app:
        def institution(method,path,role,**kwargs):
            r=institutions.request(method,path,headers={'Authorization':'Bearer '+sim['tokens'][role],
                **kwargs.pop('headers',{})},**kwargs);r.raise_for_status();return r.json()
        def command(path,body):
            r=app.post(path,json=body,headers={'Idempotency-Key':str(uuid4())});r.raise_for_status();return r.json()
        case=institution('POST','/evaluator/runs','evaluator',json={})['case_id']
        hospital=institution('GET',f'/hospital/cases/{case}','hospital')
        original=institution('GET',f'/hospital/cases/{case}/submissions','hospital')['submissions'][0]
        lookup=institution('POST','/claims/request-lookups','claims',json={'case_id':case,'patient_id':hospital['patient_id'],
            'reference':hospital['final_reference'],'request_type':'FINAL_AUTHORIZATION'})
        check('Hospital has dispatch but correct claims queue is empty',original['transport_status']=='ACCEPTED_BY_TRANSPORT' and not lookup['requests'])
        check('Initial approval is separate from final request',hospital['initial_status']=='AUTHORIZED' and original['request_type']=='FINAL_AUTHORIZATION')
        i=command('/v1/intakes',{'case_id':case,'title':'Manual verification / wrong-route final request'})['incident_id']
        prefix=f'/v1/incidents/{i}'
        command(prefix+'/consent',{'accepted':True,'confirmation':'Synthetic caregiver permission recorded for this manual test only.'})
        def upload(name,data):
            r=app.post(prefix+'/documents',files={'file':(name,json.dumps(data).encode(),'application/json')},data={'kind':'dispatch'})
            r.raise_for_status();return r.json()['document_id']
        original_doc=upload('original-hospital-dispatch.json',original)
        def record(role,predicate,value,text,document=None):
            c=command(prefix+'/calls',{'participant_role':role,'purpose':'Manual reconstruction from institution API evidence',
                'transcript':[{'speaker':'participant','text':text}]})['call_id']
            return command(prefix+'/statements',{'call_id':c,'source_role':role,'predicate':predicate,'value':value,
                'reference':hospital['final_reference'],'document_id':document})['assertion_id']
        a=record('hospital','SUBMITTED',{'submitted':True,'revision':1},
            'The hospital dispatch record shows the final request was sent.')
        b=record('claims','NOT_RECEIVED',{'queue':'designated-claims','lookup_id':lookup['lookup_id'],'found':False},
            'No matching final request was found in the designated claims queue.')
        c=record('hospital','DESTINATION',{'destination':original['destination']},
            'The dispatch destination is '+original['destination']+'.',original_doc)
        detail=app.get(prefix).json()
        check('Comparable statements produce a visible discrepancy',detail['incident']['state']=='DISCREPANCY_OPEN')
        route=institution('GET','/claims/routing','claims')['routes'][0]
        action=command(prefix+'/actions',{'destination':route['destination'],'route_id':route['id'],'evidence_ids':[a,b,c]})
        command(prefix+'/actions/'+action['action_id']+'/authorize',{'accepted':True,
            'confirmation':'Synthetic caregiver approves this exact hospital correction request in the manual test.'})
        corrected=institution('POST',f'/hospital/cases/{case}/submissions','hospital',json={
            'destination':route['destination'],'reference':hospital['final_reference'],'packet':hospital['packet']},
            headers={'Idempotency-Key':str(uuid4())})
        history=institution('GET',f'/hospital/cases/{case}/submissions','hospital')['submissions']
        dispatch=history[-1]|{'submission_id':corrected['submission_id']}
        dispatch_doc=upload('corrected-hospital-dispatch.json',dispatch)
        receipt=institution('GET',f'/claims/cases/{case}/receipts','claims')['receipts'][0]
        verified=command(prefix+'/verify',{'action_id':action['action_id'],'dispatch_document_id':dispatch_doc,'receipt':receipt})
        check('Independent recipient signature accepted',verified['verified'] is True)
        check('Original and corrected hospital history preserved',len(history)==2 and history[0]['destination']==original['destination'])
        final=app.get(prefix).json()
        check('Only routing resolves; insurance decision remains pending',final['incident']['state']=='BLOCKER_RESOLVED' and final['incident']['decision_state']=='PENDING')
        check('Every conversation labeled manual; no real execution fabricated',all(
            x['mode']=='MANUAL_RECONSTRUCTION' and x['execution_id'] is None for x in final['calls']))
        check('Uploaded dispatch corroborated only after receipt verification',next(
            x for x in final['documents'] if x['id']==dispatch_doc)['status']=='CORROBORATED_BY_RECIPIENT')
        report={'generated_at':datetime.now(timezone.utc).isoformat(),'simulated':True,'mode':'MANUAL_RECONSTRUCTION',
            'real_calls_performed':0,'case_id':case,'incident_id':i,'checks':checks,'incident':final,
            'institution_history':history,'signed_recipient_receipt':receipt,
            'remaining':'Real Bolna calls, tool configuration, inbound binding, recording playback and integrated voice rehearsals remain unverified.'}
        Path(args.report).write_text(json.dumps(report,indent=2))
        print(f'{len(checks)} manual-case checks passed. No real calls made. Evidence report saved.')


if __name__=='__main__':
    main()
