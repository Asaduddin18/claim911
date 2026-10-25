"""Prepare a scoped complex-agent text test; fake provider only, never telephony."""
import argparse,json,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).parents[1]))
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from coordinator.app import create_app
from coordinator.worker import work_once
from coordinator.workflow_calls import WORKFLOW_ROLES
from simulator.app import create_app as institutions
from tests.test_worker import FakeProvider,enabled
from tests.test_environment import auth
from tests.test_coordinator import consent,document


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True)
    p.add_argument('--purpose',choices=WORKFLOW_ROLES,default='QUERY_DISCOVERY')
    p.add_argument('--incident');p.add_argument('--upload-proof',action='store_true');args=p.parse_args()
    runtime=Path(args.runtime);sim=json.loads((runtime/'simulator.json').read_text())
    cfg=json.loads((runtime/'coordinator.json').read_text())|{'test_mode':True,'live_calls_enabled':False,'outbound_paused':False,'bolna_api_key':None}
    with TestClient(create_app(cfg)) as core,TestClient(institutions(sim)) as env:
        core.headers['Authorization']='Bearer '+cfg['operator_token']
        if args.incident:
            id=args.incident;r=core.get('/v1/incidents/'+id);r.raise_for_status();detail=r.json()
            if not detail['incident']['is_test']:
                raise SystemExit('Text evaluation must use an isolated test incident.')
            cid=detail['incident']['case_id']
        else:
            if args.purpose not in {'QUERY_DISCOVERY','HOSPITAL_REFERENCE_DISCOVERY'}:
                raise SystemExit('Begin with query discovery, then reuse its isolated incident.')
            case=env.post('/evaluator/complex-runs',headers=auth(sim,'evaluator'));case.raise_for_status();cid=case.json()['case_id']
            r=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':cid,
                'title':'Complex discharge hosted-agent text evaluation','patient_id':'DEMO-PATIENT-84','reference':'FIN63','reference_known':args.purpose!='HOSPITAL_REFERENCE_DISCOVERY'})
            r.raise_for_status();id=r.json()['incident_id'];consent(core,id)
        if args.upload_proof:
            desk={'BILLING_DOCUMENT':'billing','RECORDS_DOCUMENT':'medical_records','IMPLANT_DOCUMENT':'implant_store'}.get(args.purpose)
            if not desk:raise SystemExit('Proof fixture upload applies only to document-desk tests.')
            if desk=='medical_records':
                env.post(f'/hospital/complex/{cid}/documents/summary-signed/release',headers=auth(sim,'hospital')).raise_for_status()
            r=env.get(f'/hospital/complex/{cid}/desks/{desk}',headers=auth(sim,'hospital'));r.raise_for_status()
            d=r.json()['documents'][0];document(core,id,d['id']+'.json',d,'other')
        r=core.post(f'/v1/incidents/{id}/participants',json={'role':WORKFLOW_ROLES[args.purpose],'phone':'+919999999999',
            'verified':True,'demo_consent':'Isolated synthetic text evaluation. Do not place an actual phone call.'})
        r.raise_for_status();participant=r.json()['participant_id']
        r=core.post(f'/v1/incidents/{id}/call-jobs',headers={'Idempotency-Key':str(uuid4())},
            json={'participant_id':participant,'purpose':args.purpose});r.raise_for_status();job=r.json()
        provider=FakeProvider();assert work_once(enabled(cfg),provider,job['job_id']);assert provider.count==1
        with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
            payload=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']
        output={'incident_id':id,'case_id':cid,'purpose':args.purpose,'job':job,'user_data':payload['user_data'],
                'real_phone_calls':0,'telephony':'MOCK_ONLY','preuploaded_proof_fixture':args.upload_proof}
        f=runtime/'complex-text-evaluation.json';f.write_text(json.dumps(output,indent=2));f.chmod(0o600)
        print(json.dumps({'incident_id':id,'purpose':args.purpose,'fixture_ready':True,'real_phone_calls':0}))


if __name__=='__main__':main()
