"""Explicit manual reconstruction through running services; no voice or phone calls."""
import argparse,json,sys
from pathlib import Path
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.app import create_app


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    runtime=Path(args.runtime);cfg=json.loads((runtime/'simulator.json').read_text());core=json.loads((runtime/'coordinator.json').read_text())
    operations=[]
    with httpx.Client(base_url='http://127.0.0.1:8111',timeout=20) as env,TestClient(create_app(core|{'test_mode':True,'live_calls_enabled':False,'bolna_api_key':None})) as api:
        api.headers['Authorization']='Bearer '+core['operator_token']
        def inst(role,method,path,**kwargs):
            r=env.request(method,path,headers={'Authorization':'Bearer '+cfg['tokens'][role],**kwargs.pop('headers',{})},**kwargs);r.raise_for_status();return r.json()
        def command(path,body):
            r=api.post(path,json=body);r.raise_for_status();operations.append({'path':path,'http_status':r.status_code});return r.json()
        case=inst('evaluator','POST','/evaluator/complex-runs');cid=case['case_id']
        r=api.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':cid,'title':'Synthetic complex discharge | manual rehearsal','patient_id':case['patient_id'],'reference':'FIN63'});r.raise_for_status();id=r.json()['incident_id'];base=f'/v1/incidents/{id}'
        command(base+'/consent',{'accepted':True,'confirmation':'Synthetic rehearsal fixture consent only; no human contacted.'})
        call=command(base+'/calls',{'participant_role':'claims','purpose':'Manual reconstruction of synthetic TPA document query','transcript':[{'speaker':'participant','text':'MANUAL REHEARSAL: TPA query QRY25 requires bill v2, signed summary and implant invoice for admission ADM42. Enhancement linking and decision remain pending.'}]})
        def upload(name,value,kind='other'):
            r=api.post(base+'/documents',files={'file':(name,json.dumps(value).encode(),'application/json')},data={'kind':kind});r.raise_for_status();return r.json()['document_id']
        q=inst('claims','GET',f'/claims/complex/{cid}/query')
        did=upload('synthetic-tpa-query.json',q)
        command(base+'/complex/query',{'call_id':call['call_id'],'document_id':did})
        inst('hospital','POST',f'/hospital/complex/{cid}/documents/summary-signed/release')
        for desk in ['billing','medical_records','implant_store']:
            d=inst('hospital','GET',f'/hospital/complex/{cid}/desks/{desk}')['documents'][0]
            w=command(base+'/complex/documents',{'document_id':upload(desk+'.json',d)})
        command(base+'/complex/approve',{'accepted':True,'packet_hash':w['packet_hash'],'source':'SYNTHETIC_REHEARSAL_FIXTURE','confirmation':'MANUAL SYNTHETIC REHEARSAL APPROVAL FIXTURE. No actual caregiver decision represented.'})
        packet=w['packet'];sub=inst('hospital','POST',f'/hospital/complex/{cid}/dispatches',headers={'Idempotency-Key':str(uuid4())},json={k:packet[k] for k in ['query_id','claim_id','reference','documents']})
        ack=inst('claims','POST',f'/claims/complex/{cid}/receive/{sub["id"]}')
        w=command(base+'/complex/verify',{'dispatch_document_id':upload('hospital-response-dispatch.json',sub,'dispatch'),'receipt':ack})
        r=api.get(base);r.raise_for_status();detail=r.json()
        assert detail['incident']['state']=='QUERY_RESPONSE_RECEIVED' and detail['incident']['decision_state']=='PENDING'
        assert len(detail['verified_receipts'])==1 and w['approval_current']
        resolution=inst('claims','POST',f'/claims/complex/{cid}/link-enhancement')
        command(base+'/complex/query-resolution',{'document_id':upload('tpa-query-answered.json',resolution)})
        decision=inst('insurer','POST',f'/insurer/complex/{cid}/decision',json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Scripted synthetic insurer adjudication. No model decision.'})
        command(base+'/complex/decision',{'document_id':upload('insurer-final-decision.json',decision)})
        clearance=inst('hospital','POST',f'/hospital/complex/{cid}/reconcile')
        w=command(base+'/complex/clearance',{'document_id':upload('hospital-discharge-reconciliation.json',clearance)})
        r=api.get(base);r.raise_for_status();detail=r.json()
        assert detail['incident']['state']=='DISCHARGE_CLEARED' and detail['incident']['decision_state']=='AUTHORIZED'
        assert w['clearance']['envelope']['refund_due_inr']==12000
        assert w['clearance']['envelope']['refund_payment_state']=='NOT_VERIFIED'
        output={'execution_mode':'MANUAL_RECONSTRUCTION','synthetic':True,'approval_source':'SYNTHETIC_REHEARSAL_FIXTURE','test_incident':True,'real_phone_calls':0,'agent_conversations':0,
                'incident_id':id,'case_id':cid,'operations':operations,'workflow':w,
                'evidence_document_count':len(detail['documents']),'state':detail['incident']['state'],'decision_state':detail['incident']['decision_state'],
                'not_proven':['Hosted agent coordination','Complex voice tools','Real voice execution','Refund payment']}
        Path(args.output).write_text(json.dumps(output,indent=2)+'\n')
        meta=runtime/'complex-rehearsal.json';meta.write_text(json.dumps({'incident_id':id,'case_id':cid}));meta.chmod(0o600)
        print(json.dumps({'incident_id':id,'documents':len(detail['documents']),'signed_receipts_verified':1,'state':detail['incident']['state'],'decision_state':detail['incident']['decision_state'],'real_phone_calls':0}))


if __name__=='__main__':main()
