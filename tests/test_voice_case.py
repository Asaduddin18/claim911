"""Reproducible scoped-tool case. Provider speech/telephony is explicitly mocked."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
import psycopg
from psycopg.rows import dict_row

from coordinator.gateway import create_app
from coordinator.worker import work_once, process_webhook_once
from tests.test_worker import FakeProvider, enabled
from tests.test_coordinator import create, consent, document, authorize
from tests.test_environment import seed, auth, submit, receipts


@pytest.mark.parametrize('scenario',['success','missing_receipt','access_refused'])
def test_full_voice_tool_case_with_independent_recipient_receipt(core,core_config,env,cfg,scenario):
    case=seed(env,cfg,withhold_receipt=scenario=='missing_receipt');incident=create(core,case);consent(core,incident)
    base=f'/v1/incidents/{incident}'
    headers={'Authorization':'Bearer synthetic-gateway'}
    with TestClient(create_app(core_config|{'environment':'operational','gateway_token':'synthetic-gateway'},client=core)) as gateway:
        def detail():
            return core.get(base).json()
        def start(role,purpose,action_id=None):
            participant=core.post(base+'/participants',json={'role':role,'phone':'+919999999999','verified':True,
                'demo_consent':'Synthetic integration fixture, never contact a person.','recording_consent':True})
            assert participant.status_code==201
            response=core.post(base+'/call-jobs',json={'participant_id':participant.json()['participant_id'],
                'purpose':purpose,'action_id':action_id},headers={'Idempotency-Key':str(uuid4())})
            assert response.status_code==201,response.text
            job=response.json();provider=FakeProvider()
            assert work_once(enabled(core_config),provider,job['job_id'])
            with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
                token=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']['user_data']['call_token']
            context=gateway.post('/voice/context',json={'call_token':token},headers=headers)
            assert context.status_code==200,context.text
            assert context.json()['participant_role']==role
            return token,provider,context.json()
        def fact(token,predicate,value):
            response=gateway.post('/voice/statement',json={'call_token':token,'predicate':predicate,
                'reference':'HOSP-FINAL-1042','fact_value':value},headers=headers)
            assert response.status_code==201,response.text
            return response.json()
        def finish(provider):
            response=core.post('/v1/webhooks/bolna',headers={'X-Webhook-Token':core_config['webhook_token']},
                json={'id':provider.execution_id,'status':'completed','transcript':'Synthetic provider fixture; not a real conversation.'})
            assert response.status_code==202
            assert process_webhook_once(core_config,execution_id=provider.execution_id)

        assert detail()['next_step']['purpose']=='HOSPITAL_INITIAL'
        token,provider,context=start('hospital','HOSPITAL_INITIAL')
        assert context['statements']==[] and context['documents']==[]
        assert 'old-tpa.example.invalid' not in str(context)
        initial=gateway.post('/voice/statement',json={'call_token':token,'predicate':'SUBMITTED',
            'reference':'PREAUTH-077','request_type':'PREAUTHORIZATION','fact_value':'Initial preauthorization submission only.'},headers=headers)
        assert initial.status_code==201,initial.text
        assert detail()['assertions'][-1]['request_type']=='PREAUTHORIZATION'
        assert detail()['incident']['reference']=='HOSP-FINAL-1042'
        fact(token,'SUBMITTED','Final authorization sent, reference read back.')
        finish(provider)
        assert detail()['next_step']['purpose']=='CLAIMS_LOOKUP'

        token,provider,context=start('claims','CLAIMS_LOOKUP')
        assert any(f['predicate']=='SUBMITTED' and f['request_type']=='FINAL_AUTHORIZATION' for f in context['statements'])
        assert all('request_type' in f for f in context['statements'])
        if scenario=='access_refused':
            fact(token,'ACCESS_REFUSED','Role player declined to discuss the synthetic case.')
            finish(provider)
            held=detail()
            assert held['next_step']['kind']=='HUMAN_REVIEW'
            assert held['incident']['state']=='HUMAN_REVIEW'
            assert not held['actions'] and not held['verified_receipts']
            return
        lookup=env.post('/claims/request-lookups',headers=auth(cfg,'claims'),json={'case_id':case,
            'patient_id':'DEMO-PATIENT-42','reference':'HOSP-FINAL-1042','request_type':'FINAL_AUTHORIZATION'})
        assert lookup.status_code==200 and lookup.json()['requests']==[]
        fact(token,'NOT_RECEIVED','Searched designated claims queue for the final authorization reference.')
        finish(provider)
        assert detail()['next_step']['kind']=='COLLECT_DISPATCH'

        dispatch=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions'][0]
        document(core,incident,'hospital-original-dispatch.json',dispatch,'dispatch')
        token,provider,context=start('hospital','HOSPITAL_FOLLOWUP')
        assert {f['predicate'] for f in context['statements']}=={'SUBMITTED','NOT_RECEIVED'}
        assert 'Do not repeat submission' in context['objective']
        assert 'destination' in context['objective']
        fact(token,'DESTINATION',dispatch['destination'])
        proposal=gateway.post('/voice/propose',json={'call_token':token},headers=headers)
        assert proposal.status_code==201,proposal.text
        aid=proposal.json()['action_id']
        finish(provider)
        assert detail()['next_step']['kind']=='APPROVAL_REQUIRED'
        assert authorize(core,incident,aid).status_code==200
        assert detail()['next_step']['purpose']=='CORRECTION_REQUEST'

        token,provider,context=start('hospital','CORRECTION_REQUEST',aid)
        assert context['authorized_actions'][0]['id']==aid
        # Institutional credentials remain outside the voice gateway and coordinator.
        submit(env,cfg,case)
        finish(provider)
        assert detail()['next_step']['kind']=='VERIFY_RECEIPT'
        assert detail()['incident']['state']!='BLOCKER_RESOLVED'
        corrected=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions'][-1]
        corrected['submission_id']=corrected['id']
        doc=document(core,incident,'hospital-corrected-dispatch.json',corrected,'dispatch')
        if scenario=='missing_receipt':
            assert receipts(env,cfg,case)==[]
            response=core.post(base+'/verify',json={'action_id':aid,'dispatch_document_id':doc,'receipt':{}})
            assert response.status_code==422
            held=detail()
            assert held['next_step']['kind']=='VERIFY_RECEIPT'
            assert held['incident']['state']!='BLOCKER_RESOLVED'
            assert not held['verified_receipts']
            return
        receipt=receipts(env,cfg,case)[0]
        response=core.post(base+'/verify',json={'action_id':aid,'dispatch_document_id':doc,'receipt':receipt})
        assert response.status_code==200,response.text
        final=detail()
        assert final['next_step']['kind']=='RESOLVED'
        assert final['incident']['decision_state']=='PENDING'
        assert len(final['verified_receipts'])==1
        assert len(final['calls'])==4
        assert all(c['mode']=='BOLNA_MOCK' for c in final['calls'])
        assert all(c['state']=='COMPLETED' for c in final['calls'])
        assert all(c['recording_url'] is None for c in final['calls'])
