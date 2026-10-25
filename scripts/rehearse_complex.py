"""Exercise synthetic institutions. This does not run agents or place telephone calls."""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4
import httpx

sys.path.insert(0,str(Path(__file__).parents[1]))
from simulator.complex import canonical
from tests.test_environment import public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import base64


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--url',default='http://127.0.0.1:8111')
    args=p.parse_args()
    config=json.loads((Path(args.runtime)/'simulator.json').read_text())
    evidence=[]
    with httpx.Client(base_url=args.url,timeout=20) as client:
        def request(role,method,path,expected=200,**kwargs):
            headers={'Authorization':'Bearer '+config['tokens'][role]}
            headers.update(kwargs.pop('headers',{}))
            r=client.request(method,path,headers=headers,**kwargs)
            assert r.status_code==expected,(path,r.status_code)
            evidence.append({'role':role,'method':method,'path':path,'http_status':r.status_code,'result':r.json()})
            return r.json()
        seeded=request('evaluator','POST','/evaluator/complex-runs',201)
        cid=seeded['case_id']
        request('hospital','GET',f'/hospital/complex/{cid}/desks/insurance')
        query=request('claims','GET',f'/claims/complex/{cid}/query')
        for desk in ['billing','medical_records','implant_store']:
            request('hospital','GET',f'/hospital/complex/{cid}/desks/{desk}')
        packet={'query_id':'QRY25','claim_id':'CLM86','reference':'FIN63',
                'documents':['bill-v2','summary-signed','implant-invoice']}
        request('hospital','POST',f'/hospital/complex/{cid}/dispatches',422,
                headers={'Idempotency-Key':str(uuid4())},json=packet)
        request('hospital','POST',f'/hospital/complex/{cid}/reconcile',409)
        request('agent','GET',f'/claims/complex/{cid}/query',403)
        request('hospital','POST',f'/hospital/complex/{cid}/documents/summary-signed/release')
        sub=request('hospital','POST',f'/hospital/complex/{cid}/dispatches',201,
                    headers={'Idempotency-Key':str(uuid4())},json=packet)
        before=request('claims','GET',f'/claims/complex/{cid}/query')
        assert before['receipts']==[]
        ack=request('claims','POST',f'/claims/complex/{cid}/receive/{sub["id"]}')
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key(config))).verify(
            base64.b64decode(ack['signature']),canonical(ack['envelope']))
        assert ack['envelope']['packet_hash']==sub['packet_hash']
        request('claims','POST',f'/claims/complex/{cid}/link-enhancement')
        request('hospital','POST',f'/hospital/complex/{cid}/reconcile',409)
        request('insurer','POST',f'/insurer/complex/{cid}/decision',
                json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Scripted synthetic insurer review, not model adjudication.'})
        clearance=request('hospital','POST',f'/hospital/complex/{cid}/reconcile')
        assert clearance['refund_due_inr']==12000 and clearance['refund_payment_state']=='NOT_VERIFIED'
        after=request('claims','GET',f'/claims/complex/{cid}/query')
        assert after['received_at']==query['received_at']
    result={'synthetic':True,'case_id':cid,'execution_mode':'DIRECT_INSTITUTION_API_REHEARSAL',
            'real_phone_calls':0,'agent_conversations':0,'signature_verified':True,
            'passed':True,'final_clearance':clearance,'evidence':evidence,
            'not_proven':['Coordinator task orchestration','Caregiver packet approval','Agent conversation behavior',
                          'Complex-case dashboard integration','Real voice workflow','Actual refund payment']}
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'case_id':cid,'operations':len(evidence),'signature_verified':True,'refund_due_inr':12000,
                      'real_phone_calls':0,'agent_conversations':0,'evidence_saved':True}))


if __name__=='__main__':
    main()
