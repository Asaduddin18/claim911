"""Call-scoped complex tools with mocked telephony; no hosted model claims."""
import json
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
import pytest

from coordinator.gateway import create_app
from coordinator.worker import work_once
from tests.test_worker import FakeProvider,enabled
from tests.test_coordinator import consent,document
from tests.test_environment import auth
from tests.test_complex_coordinator import setup,collect,approve

QUERY={'query_reference':'QRY25','claim_reference':'CLM86','admission_id':'ADM42',
       'enhancement_reference':'ENH18','received_at':'2026-10-23T10:20:00+05:30',
       'required_documents':['itemized_bill','signed_discharge_summary','implant_invoice'],'enhancement_linked':False}


def test_records_callback_guidance_reaches_shared_voice_context(core,core_config,env,cfg):
    id,_=setup(core,env,cfg)
    job,_,token=start(core,core_config,id,'hospital','RECORDS_DOCUMENT')
    headers={'X-Call-Token':token}
    first=core.get('/v1/tools/context',headers=headers).json()
    assert 'active_followup' not in first['workflow']
    assert 'scheduled medical-records callback' not in first['instructions']
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("""INSERT INTO coordinator.workflow_callbacks
            (id,incident_id,task_key,purpose,proposal,consent_version,available_at,state,attempts,lease_token,lease_until)
            SELECT %s,id,'records-guidance','RECORDS_DOCUMENT','{}'::jsonb,consent_version,now(),'RUNNING',1,%s,now()+interval '2 minutes'
            FROM coordinator.incidents WHERE id=%s""",(uuid4(),uuid4(),id))
    followup=core.get('/v1/tools/context',headers=headers).json()
    assert followup['workflow']['active_followup']=={'purpose':'RECORDS_DOCUMENT','attempt':1}
    assert 'follow up with the treating team' in followup['instructions']
    assert 'You cannot sign the document' in followup['instructions']
    assert core.get(f'/v1/incidents/{id}/complex').json()['documents']=={}
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.workflow_callbacks SET state='CANCELLED' WHERE incident_id=%s",(id,))
    assert 'active_followup' not in core.get('/v1/tools/context',headers=headers).json()['workflow']
    finish(core_config,job)


def start(core,core_config,id,role,purpose,dispatch=True):
    p=core.post(f'/v1/incidents/{id}/participants',json={'role':role,'phone':'+919999999999','verified':True,
        'demo_consent':'Synthetic text evaluation only; never contact a person.'}).json()['participant_id']
    r=core.post(f'/v1/incidents/{id}/call-jobs',headers={'Idempotency-Key':str(uuid4())},
        json={'participant_id':p,'purpose':purpose})
    assert r.status_code==201,r.text
    job=r.json();provider=FakeProvider()
    if dispatch:assert work_once(enabled(core_config),provider,job['job_id'])
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        data=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']
    return job,provider,data['user_data']['call_token']


def finish(core_config,job):
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET state='COMPLETED' WHERE id=%s",(job['call_id'],))


def test_scoped_voice_query_discovery_and_document_followup(core,core_config,env,cfg):
    case=env.post('/evaluator/complex-runs',headers=auth(cfg,'evaluator')).json()['case_id']
    id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':case,
        'patient_id':'DEMO-PATIENT-84','reference':'FIN63'}).json()['incident_id'];consent(core,id)
    job,provider,token=start(core,core_config,id,'claims','QUERY_DISCOVERY')
    headers={'Authorization':'Bearer test-workflow-gateway'}
    with TestClient(create_app(core_config|{'environment':'operational','gateway_token':'test-workflow-gateway'},client=core)) as gateway:
        def report(token,operation,details):
            details=dict(details)
            if operation=='REPORT_QUERY':
                if 'required_documents' in details:details['required_documents']=','.join(details['required_documents'])
                if 'enhancement_linked' in details:details['enhancement_linked']=str(details['enhancement_linked']).lower()
                route='/voice/query'
            elif operation=='REPORT_DOCUMENT':
                details['ready']=str(details['ready']).lower();route='/voice/document'
            else:route='/voice/update'
            return gateway.post(route,headers=headers,json={'call_token':token,**details})
        context=gateway.post('/voice/context',headers=headers,json={'call_token':token}).json()
        assert context['allowed_statement_predicates']==['ACCESS_REFUSED']
        assert context['workflow']['state']=='QUERY_NOT_YET_KNOWN'
        assert not any('QRY25' in str(v) for v in context.values())
        unavailable=report(token,'REPORT_UPDATE',{'summary':'Query desk unavailable; staff agreed to a callback at 11:55 IST.'})
        assert unavailable.status_code==200 and not unavailable.json()['automatic_callback_scheduled']
        refreshed=gateway.post('/voice/context',headers=headers,json={'call_token':token}).json()
        assert len(refreshed['workflow']['reported_updates'])==1
        assert report(token,'REPORT_QUERY',{'query_reference':'QRY25'}).status_code==422
        r=report(token,'REPORT_QUERY',QUERY)
        assert r.status_code==200,r.text
        w=r.json();assert w['query_call_id']==job['call_id']
        assert w['call_complete'] is True and len(w['spoken_outcome'].split())<=55
        assert "Thanks, that's all I need for this call." in w['spoken_outcome']
        assert w['source_mode']=='BOLNA_MOCK'
        assert len(w['tasks'])==3 and not w['approval'] and not w['receipt']
        assert report(token,'REPORT_QUERY',QUERY).status_code==200
        context=gateway.post('/voice/context',headers=headers,json={'call_token':token}).json()
        assert context['workflow']['state']=='QUERY_RECORDED'
        finish(core_config,job)
        job,provider,token=start(core,core_config,id,'hospital','BILLING_DOCUMENT')
        assert report(token,'REPORT_QUERY',QUERY).status_code==403
        bad={'document_kind':'implant_invoice','document_reference':'implant-invoice','ready':True,'summary':'Synthetic staff report'}
        assert report(token,'REPORT_DOCUMENT',bad).status_code==403
        body={'document_kind':'itemized_bill','document_reference':'bill-v2','ready':True,'summary':'Revised bill v2 INR 248000; prior duplicate removed.'}
        r=report(token,'REPORT_DOCUMENT',body)
        assert r.status_code==200 and r.json()['reported_document_result']=='AWAITING_UPLOADED_PROOF'
        assert core.get(f'/v1/incidents/{id}/complex').json()['documents']=={}
        bill=env.get(f'/hospital/complex/{case}/desks/billing',headers=auth(cfg,'hospital')).json()['documents'][0]
        document(core,id,'bill-v2.json',bill,'bill')
        wrong_ref=report(token,'REPORT_DOCUMENT',body|{'document_reference':'bill-v2_v2'})
        assert wrong_ref.status_code==200
        assert wrong_ref.json()['reported_document_result']=='REFERENCE_CONFIRMATION_REQUIRED'
        assert wrong_ref.json()['call_complete'] is False
        assert wrong_ref.json()['uploaded_reference_candidates']==['bill-v2']
        assert core.get(f'/v1/incidents/{id}/complex').json()['documents']=={}
        r=report(token,'REPORT_DOCUMENT',body)
        assert r.status_code==200,r.text
        assert r.json()['documents']['itemized_bill']['record']==bill
        assert r.json()['reported_document_result']=='UPLOADED_DOCUMENT_CHECKED'
        assert r.json()['call_complete'] is True
        audits=core.get(f'/v1/incidents/{id}').json()['events']
        assert any(e['type']=='VOICE_TOOL_USED' and e['payload'].get('operation')=='REPORT_DOCUMENT' and e['payload']['call_id']==job['call_id'] for e in audits)
        old=gateway.post('/voice/statement',headers=headers,json={'call_token':token,'predicate':'SUBMITTED',
            'reference':'FIN63','fact_value':'Should not enter routing workflow'})
        assert old.status_code==403
        update=report(token,'REPORT_UPDATE',{'summary':'Billing confirmed the refund is already paid.'})
        assert update.status_code==200
        assert not core.get(f'/v1/incidents/{id}/complex').json().get('clearance')
        consent(core,id,False)
        assert report(token,'REPORT_DOCUMENT',body).status_code==403


@pytest.mark.parametrize('dispatch_before_change',[False,True])
def test_packet_submission_call_is_bound_to_exact_current_approval(core,core_config,env,cfg,dispatch_before_change):
    id,cid=setup(core,env,cfg);w=collect(core,env,cfg,id,cid)
    participant=core.post(f'/v1/incidents/{id}/participants',json={'role':'hospital','phone':'+919999999999',
        'verified':True,'demo_consent':'Synthetic fixture only; no actual telephone contact.'}).json()['participant_id']
    r=core.post(f'/v1/incidents/{id}/call-jobs',headers={'Idempotency-Key':str(uuid4())},
        json={'participant_id':participant,'purpose':'PACKET_SUBMISSION'})
    assert r.status_code==409
    assert approve(core,id,w).status_code==200
    job,provider,token=start(core,core_config,id,'hospital','PACKET_SUBMISSION',dispatch_before_change)
    if dispatch_before_change:
        assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==200
        pending=core.post('/v1/tools/workflow',headers={'X-Call-Token':token},json={'operation':'REPORT_UPDATE','details':{'summary':'Hospital dispatch reference is still being checked.'}})
        assert pending.status_code==200 and pending.json()['call_complete'] is False
        assert 'do not submit it again' in pending.json()['spoken_outcome']
    bill=dict(w['documents']['itemized_bill']['record']);bill['revision']=3;bill['amount_inr']=249000
    from coordinator.complex import digest
    bill['hash']=digest({k:v for k,v in bill.items() if k!='hash'})
    did=document(core,id,'revised-again.json',bill,'bill')
    assert core.post(f'/v1/incidents/{id}/complex/documents',json={'document_id':did}).status_code==200
    if dispatch_before_change:
        assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403
    else:
        assert work_once(enabled(core_config),provider,job['job_id'])
        assert provider.count==0
        call=next(c for c in core.get(f'/v1/incidents/{id}').json()['calls'] if c['id']==job['call_id'])
        assert call['state']=='CANCELLED'


def test_hosted_text_evidence_is_labeled_immutable_and_cannot_replace_real_calls(core,core_config,env,cfg):
    case=env.post('/evaluator/complex-runs',headers=auth(cfg,'evaluator')).json()['case_id']
    id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':case,
        'patient_id':'DEMO-PATIENT-84','reference':'FIN63'}).json()['incident_id'];consent(core,id)
    job,provider,token=start(core,core_config,id,'claims','QUERY_DISCOVERY')
    body={'source':'BOLNA_HOSTED_TEXT_SIMULATOR','turns':[{'speaker':'assistant','text':'Synthetic hosted text fixture.'},
        {'speaker':'participant','text':'Synthetic participant text fixture.'}],
        'attestation':'Test fixture for operator-imported hosted text provenance; never represents a telephone call.'}
    url=f'/v1/incidents/{id}/calls/{job["call_id"]}/text-evidence'
    r=core.post(url,json=body)
    assert r.status_code==200 and r.json()['real_phone_call'] is False
    assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['calls'][0]['mode']=='BOLNA_TEXT_SIMULATOR'
    assert detail['calls'][0]['transcript']==body['turns']
    assert core.post(url,json=body).status_code==200
    body['turns'][0]['text']='Attempt to overwrite imported evidence'
    assert core.post(url,json=body).status_code==409
    # A real-call mode is never replaceable via this test-only endpoint.
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET mode='BOLNA' WHERE id=%s",(job['call_id'],))
    assert core.post(url,json=body).status_code==403
    assert core.get(f'/v1/incidents/{id}').json()['calls'][0]['transcript'][0]['text']=='Synthetic hosted text fixture.'


def test_synthetic_packet_approval_cannot_authorize_real_phone_submission(core,core_config,env,cfg):
    from coordinator.app import create_app as core_app
    id,cid=setup(core,env,cfg);w=collect(core,env,cfg,id,cid)
    body={'accepted':True,'packet_hash':w['packet_hash'],'source':'SYNTHETIC_REHEARSAL_FIXTURE',
          'confirmation':'Synthetic caregiver role fixture approves this exact packet for text rehearsal only.'}
    url=f'/v1/incidents/{id}/complex/approve'
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute('UPDATE coordinator.incidents SET is_test=false WHERE id=%s',(id,))
    assert core.post(url,json=body).status_code==403
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute('UPDATE coordinator.incidents SET is_test=true WHERE id=%s',(id,))
    approved=core.post(url,json=body)
    assert approved.status_code==200
    assert approved.json()['approval']['recorded_by']=='SYNTHETIC_CAREGIVER_ROLE_FIXTURE'
    job,provider,token=start(core,core_config,id,'hospital','PACKET_SUBMISSION',False)
    # A queued mock job cannot be converted into a real call with fixture approval.
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET mode='BOLNA' WHERE id=%s",(job['call_id'],))
    assert work_once(enabled(core_config),provider,job['job_id'])
    assert provider.count==0
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET state='IN_PROGRESS' WHERE id=%s",(job['call_id'],))
    assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403
    finish(core_config,job)
    participant=core.post(f'/v1/incidents/{id}/participants',json={'role':'hospital','phone':'+919999999999',
        'verified':True,'demo_consent':'Synthetic fixture only; no actual telephone contact.'}).json()['participant_id']
    with TestClient(core_app(core_config|{'environment':'operational','test_mode':False})) as live:
        live.headers['Authorization']='Bearer '+core_config['operator_token']
        result=live.post(f'/v1/incidents/{id}/call-jobs',headers={'Idempotency-Key':str(uuid4())},
            json={'participant_id':participant,'purpose':'PACKET_SUBMISSION'})
    assert result.status_code==409
    assert 'Synthetic caregiver approval' in result.json()['detail']


def test_hosted_connection_failure_expires_token_without_inventing_transcript(core,core_config,env,cfg):
    id,cid=setup(core,env,cfg)
    job,provider,token=start(core,core_config,id,'hospital','BILLING_DOCUMENT')
    url=f'/v1/incidents/{id}/calls/{job["call_id"]}/text-failure'
    body={'source':'BOLNA_HOSTED_TEXT_SIMULATOR','reason':'CONNECTION_NOT_STARTED',
          'attestation':'Browser displayed Chat could not start. No conversation or participant statement exists.'}
    assert core.post(url,json=body).status_code==200
    assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403
    assert core.post(url,json=body).status_code==200
    changed=body|{'attestation':'Changed connection-failure account, which must not overwrite the original evidence.'}
    assert core.post(url,json=changed).status_code==409
    detail=core.get(f'/v1/incidents/{id}').json()
    call=next(c for c in detail['calls'] if c['id']==job['call_id'])
    assert call['state']=='FAILED' and not call['transcript'] and call['mode']=='BOLNA_MOCK'
    job2,provider2,token2=start(core,core_config,id,'hospital','BILLING_DOCUMENT')
    report=core.post('/v1/tools/workflow',headers={'X-Call-Token':token2},json={'operation':'REPORT_UPDATE',
        'details':{'summary':'Billing desk reports a blocker; this is an existing conversation report.'}})
    assert report.status_code==200
    assert core.post(f'/v1/incidents/{id}/calls/{job2["call_id"]}/text-failure',json=body).status_code==409
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET mode='BOLNA' WHERE id=%s",(job2['call_id'],))
    assert core.post(f'/v1/incidents/{id}/calls/{job2["call_id"]}/text-failure',json=body).status_code==403


def test_hospital_discovers_distinct_references_before_claims_lookup(core,core_config,env,cfg):
    cid=env.post('/evaluator/complex-runs',headers=auth(cfg,'evaluator')).json()['case_id']
    id=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':cid,
        'patient_id':'DEMO-PATIENT-84','reference_known':False,'reference':'SHOULD-NOT-BE-USED'}).json()['incident_id']
    consent(core,id)
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['reference']=='UNCONFIRMED_FINAL_REFERENCE'
    assert detail['next_step']['purpose']=='HOSPITAL_REFERENCE_DISCOVERY'
    claims=core.post(f'/v1/incidents/{id}/participants',json={'role':'claims','phone':'+919999999999','verified':True,
        'demo_consent':'Synthetic fixture only; no actual phone call.'}).json()['participant_id']
    assert core.post(f'/v1/incidents/{id}/call-jobs',headers={'Idempotency-Key':str(uuid4())},
        json={'participant_id':claims,'purpose':'QUERY_DISCOVERY'}).status_code==409
    job,provider,token=start(core,core_config,id,'hospital','HOSPITAL_REFERENCE_DISCOVERY')
    body={'admission_id':'ADM42','initial_reference':'PRE37','enhancement_reference':'ENH18',
        'final_reference':'FIN63','submission_status':'UNKNOWN','summary':'Hospital confirms separate references but cannot yet confirm final dispatch.'}
    headers={'X-Call-Token':token}
    assert core.post('/v1/tools/references',headers=headers,json=body|{'final_reference':'PRE37'}).status_code==422
    with TestClient(create_app(core_config|{'environment':'operational'},core)) as gateway:
        response=gateway.post('/voice/references',headers={'Authorization':'Bearer '+core_config['gateway_token']},
            json={'call_token':token,**body})
    assert response.status_code==200 and response.json()['receiving_side_verified'] is False
    assert core.post('/v1/tools/references',headers=headers,json=body).status_code==200
    assert core.post('/v1/tools/references',headers=headers,json=body|{'final_reference':'OTHER-FINAL'}).status_code==409
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['reference']=='FIN63'
    assert detail['reference_discovery']['submission_status']=='UNKNOWN'
    assert not detail['verified_receipts'] and not detail['assertions']
    finish(core_config,job)
    claimsjob,provider,claimstoken=start(core,core_config,id,'claims','QUERY_DISCOVERY')
    scoped=core.get('/v1/tools/context',headers={'X-Call-Token':claimstoken}).json()
    assert scoped['workflow']['reported_hospital_references']['admission_id']=='ADM42'
    assert scoped['workflow']['reported_hospital_references']['receiving_side_verified'] is False
    assert core.post('/v1/tools/references',headers={'X-Call-Token':claimstoken},json=body).status_code==403
    mismatch=core.post('/v1/tools/workflow',headers={'X-Call-Token':claimstoken},json={'operation':'REPORT_QUERY',
        'details':QUERY|{'admission_id':'OTHER-ADMISSION'}})
    assert mismatch.status_code==409
    assert core.post('/v1/tools/workflow',headers={'X-Call-Token':claimstoken},json={'operation':'REPORT_QUERY','details':QUERY}).status_code==200


def test_caregiver_followup_explains_checked_state_without_changing_institution_outcome(core,core_config,env,cfg):
    id,cid=setup(core,env,cfg)
    job,provider,token=start(core,core_config,id,'caregiver','CAREGIVER_COMPLEX_UPDATE')
    context=core.get('/v1/tools/context',headers={'X-Call-Token':token}).json()
    summary=context['workflow']['caregiver_summary']
    assert context['participant_role']=='caregiver'
    assert any('No final insurer decision' in x for x in summary['pending'])
    assert not summary['refund_payment_verified']
    assert core.post('/v1/tools/workflow',headers={'X-Call-Token':token},json={'operation':'REPORT_QUERY','details':QUERY}).status_code==403
    r=core.post('/v1/tools/workflow',headers={'X-Call-Token':token},json={'operation':'REPORT_UPDATE',
        'details':{'summary':'Caregiver requests human assistance with the pending insurer review. No callback time promised.'}})
    assert r.status_code==200 and not r.json()['verified_state_changed']
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['decision_state']=='PENDING' and not detail['verified_receipts']
    assert detail['complex_workflow']['reports'][-1]['purpose']=='CAREGIVER_COMPLEX_UPDATE'
    consent(core,id,False)
    assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403
