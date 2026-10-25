"""Prepare isolated actual-agent text scenarios. Never dispatch telephony."""
import argparse,json,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).parents[1]))
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from coordinator.app import create_app
from coordinator.worker import work_once
from simulator.app import create_app as environment
from tests.test_coordinator import create,consent,statement,document,action,authorize
from tests.test_environment import seed,auth
from tests.test_worker import FakeProvider,enabled

SCENARIOS={
 'hospital_followup':('hospital','HOSPITAL_FOLLOWUP'),
 'missing_proof':('hospital','HOSPITAL_FOLLOWUP'),
 'initial_unknown':('hospital','HOSPITAL_INITIAL'),
 'claims_reference':('claims','CLAIMS_LOOKUP'),
 'reference_correction':('hospital','HOSPITAL_INITIAL'),
 'correction_no_receipt':('hospital','CORRECTION_REQUEST'),
}

def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--scenario',choices=SCENARIOS,default='hospital_followup');args=p.parse_args();runtime=Path(args.runtime)
 cfg=json.loads((runtime/'coordinator.json').read_text())|{'test_mode':True,'live_calls_enabled':False,'outbound_paused':False,'bolna_api_key':None}
 sim=json.loads((runtime/'simulator.json').read_text());role,purpose=SCENARIOS[args.scenario]
 with TestClient(create_app(cfg)) as core,TestClient(environment(sim)) as env:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  case=seed(env,sim);incident=create(core,case);consent(core,incident);ids=[];aid=None
  if args.scenario not in {'initial_unknown','reference_correction'}:
   ids.append(statement(core,incident,'hospital','SUBMITTED',{'submitted':True,'details':'Prepared synthetic fixture: final request sent one hour ago.'}))
  if purpose in {'HOSPITAL_FOLLOWUP','CORRECTION_REQUEST'}:
   ids.append(statement(core,incident,'claims','NOT_RECEIVED',{'found':False,'lookup_scope':'Prepared fixture: designated claims queue.'}))
  if args.scenario=='claims_reference':
   statement(core,incident,'hospital','SUBMITTED',{'submitted':True,'details':'Separate initial submission fixture.'},reference='PREAUTH-077',request_type='PREAUTHORIZATION')
  if args.scenario in {'hospital_followup','correction_no_receipt'}:
   dispatch=env.get(f'/hospital/cases/{case}/submissions',headers=auth(sim,'hospital')).json()['submissions'][0]
   doc=document(core,incident,'original-dispatch-text-evaluation.json',dispatch,'dispatch')
   if purpose=='CORRECTION_REQUEST':
    ids.append(statement(core,incident,'hospital','DESTINATION',{'destination':dispatch['destination']},doc))
    aid=action(core,incident,ids);assert authorize(core,incident,aid).status_code==200
  person=core.post(f'/v1/incidents/{incident}/participants',json={'role':role,'phone':'+919999999999','verified':True,'demo_consent':'Synthetic text-only evaluation fixture. No phone contact permitted.'}).json()['participant_id']
  response=core.post(f'/v1/incidents/{incident}/call-jobs',headers={'Idempotency-Key':str(uuid4())},json={'participant_id':person,'purpose':purpose,'action_id':aid});response.raise_for_status();job=response.json()
  provider=FakeProvider();assert work_once(enabled(cfg),provider,job['job_id']);assert provider.count==1
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   payload=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']
  meta={'incident_id':incident,'case_id':case,'job':job,'user_data':payload['user_data'],'scenario':args.scenario,'purpose':purpose,'telephony':'MOCK_ONLY','preloaded_facts':'All prior facts and approvals are synthetic setup prerequisites, not model-generated evidence.'}
  out=runtime/'text-evaluation.json';out.write_text(json.dumps(meta,indent=2));out.chmod(0o600)
  print(json.dumps({'incident_id':incident,'purpose':purpose,'scenario':args.scenario,'real_phone_calls':0,'fixture_ready':True}))

if __name__=='__main__':main()
