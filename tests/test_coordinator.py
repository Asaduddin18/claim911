import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from coordinator.app import create_app
from tests.test_environment import auth, seed, hospital, submit, receipts


@pytest.fixture
def core_config():
    return json.loads(Path(os.environ['CLAIM911_CORE_CONFIG']).read_text())|{'test_mode':True,'live_calls_enabled':False,'bolna_api_key':None,'outbound_paused':False}


@pytest.fixture
def core(core_config):
    with TestClient(create_app(core_config)) as client:
        client.headers['Authorization']='Bearer '+core_config['operator_token']
        yield client


def create(core,case):
    r=core.post('/v1/intakes',json={'case_id':case},headers={'Idempotency-Key':str(uuid4())})
    assert r.status_code==201,r.text
    return r.json()['incident_id']


def consent(core,id,accepted=True):
    r=core.post(f'/v1/incidents/{id}/consent',json={'accepted':accepted,'confirmation':'Explicit consent from synthetic caregiver.'})
    assert r.status_code==200,r.text
    return r.json()


def document(core,id,name,data,kind):
    r=core.post(f'/v1/incidents/{id}/documents',files={'file':(name,json.dumps(data).encode(),'application/json')},data={'kind':kind})
    assert r.status_code==201,r.text
    assert r.json()['status']=='UPLOADED_UNVERIFIED'
    return r.json()['document_id']


def statement(core,id,role,predicate,value,document_id=None,reference='HOSP-FINAL-1042',request_type='FINAL_AUTHORIZATION'):
    c=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':role,'purpose':'Manual case reconstruction',
        'transcript':[{'speaker':'participant','text':json.dumps(value)}]})
    assert c.status_code==201,c.text
    r=core.post(f'/v1/incidents/{id}/statements',json={'call_id':c.json()['call_id'],'source_role':role,
        'predicate':predicate,'value':value,'reference':reference,'document_id':document_id,'request_type':request_type})
    assert r.status_code==201,r.text
    return r.json()['assertion_id']


def evidence(core,env,cfg,id,case):
    dispatch=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions'][0]
    doc=document(core,id,'original-dispatch.json',dispatch,'dispatch')
    return [statement(core,id,'hospital','SUBMITTED',{'submitted':True}),
            statement(core,id,'claims','NOT_RECEIVED',{'queue':'designated-claims','found':False}),
            statement(core,id,'hospital','DESTINATION',{'destination':dispatch['destination']},doc)]


def action(core,id,evidence_ids):
    r=core.post(f'/v1/incidents/{id}/actions',json={'destination':'current-tpa.example.invalid','evidence_ids':evidence_ids})
    assert r.status_code==201,r.text
    return r.json()['action_id']


def authorize(core,id,aid):
    return core.post(f'/v1/incidents/{id}/actions/{aid}/authorize',json={'accepted':True,'confirmation':'Caregiver approves exactly this correction request.'})


def test_complete_manual_incident_evidence_chain(core,env,cfg):
    case=seed(env,cfg)
    id=create(core,case)
    consent(core,id)
    aid=action(core,id,evidence(core,env,cfg,id,case))
    assert authorize(core,id,aid).status_code==200
    # Hospital credentials alone perform the submission.
    sub=submit(env,cfg,case)
    dispatch=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions'][-1]
    dispatch['submission_id']=dispatch['id']
    doc=document(core,id,'corrected-dispatch.json',dispatch,'dispatch')
    body={'action_id':aid,'dispatch_document_id':doc,'receipt':receipts(env,cfg,case)[0]}
    first=core.post(f'/v1/incidents/{id}/verify',json=body)
    second=core.post(f'/v1/incidents/{id}/verify',json=body)
    assert first.status_code==second.status_code==200,first.text
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']=='BLOCKER_RESOLVED'
    assert detail['incident']['decision_state']=='PENDING'
    assert len(detail['verified_receipts'])==1
    assert len([x for x in detail['events'] if x['type']=='RECEIPT_VERIFIED'])==1
    assert all(c['mode']=='MANUAL_RECONSTRUCTION' and c['execution_id'] is None for c in detail['calls'])
    assert detail['documents'][-1]['status']=='CORROBORATED_BY_RECIPIENT'
    consent(core,id,False)
    assert core.get(f'/v1/incidents/{id}').json()['incident']['state']=='BLOCKER_RESOLVED'


def test_consent_and_authorization_revocation(core,env,cfg):
    case=seed(env,cfg);id=create(core,case)
    r=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'hospital','purpose':'Attempt before consent'})
    assert r.status_code==409
    consent(core,id)
    aid=action(core,id,evidence(core,env,cfg,id,case))
    consent(core,id,False)
    assert authorize(core,id,aid).status_code==409
    consent(core,id,True)
    assert authorize(core,id,aid).status_code==409


def test_request_type_mismatch_does_not_create_discrepancy(core,env,cfg):
    id=create(core,seed(env,cfg));consent(core,id)
    statement(core,id,'hospital','SUBMITTED',{'submitted':True},request_type='PREAUTHORIZATION')
    statement(core,id,'claims','NOT_RECEIVED',{'found':False})
    assert core.get(f'/v1/incidents/{id}').json()['incident']['state']=='INVESTIGATING'


def test_cross_incident_evidence_and_raw_upload_do_not_resolve(core,env,cfg):
    case=seed(env,cfg);a=create(core,case);b=create(core,case);consent(core,a);consent(core,b)
    doc=document(core,a,'receipt.json',{'status':'APPROVED'},'receipt')
    r=core.post(f'/v1/incidents/{b}/statements',json={'document_id':doc,'source_role':'claims',
        'predicate':'RECEIVED','value':{},'reference':'HOSP-FINAL-1042'})
    assert r.status_code==422
    assert core.get(f'/v1/incidents/{a}').json()['incident']['state']=='INVESTIGATING'
    assert core.get(f'/v1/incidents/{b}/documents/{doc}').status_code==404


def test_reference_correction_preserved_and_action_staled(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    ids=evidence(core,env,cfg,id,case);aid=action(core,id,ids)
    call=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'hospital','purpose':'Read-back correction'}).json()['call_id']
    r=core.post(f'/v1/incidents/{id}/statements',json={'call_id':call,'source_role':'hospital','predicate':'REFERENCE_CORRECTION',
        'value':{'corrected_reference':'HOSP-FINAL-1043'},'reference':'HOSP-FINAL-1042','supersedes_id':ids[0]})
    assert r.status_code==201,r.text
    assert authorize(core,id,aid).status_code==409
    data=core.get(f'/v1/incidents/{id}').json()
    assert data['incident']['reference']=='HOSP-FINAL-1043'
    assert data['assertions'][0]['support_status']=='SUPERSEDED'
    assert data['actions'][0]['state']=='STALE'


def test_upload_limits_and_content_sniffing(core,env,cfg):
    id=create(core,seed(env,cfg))
    r=core.post(f'/v1/incidents/{id}/documents',files={'file':('evil.html',b'<script>alert(1)</script>','text/html')})
    assert r.status_code==201
    doc=r.json()['document_id']
    download=core.get(f'/v1/incidents/{id}/documents/{doc}')
    assert download.headers['content-type'].startswith('text/plain')
    assert 'attachment' in download.headers['content-disposition']
    assert download.headers['x-content-type-options']=='nosniff'
    assert core.post(f'/v1/incidents/{id}/documents',files={'file':('empty.txt',b'','text/plain')}).status_code==413
    assert core.post(f'/v1/incidents/{id}/documents',files={'file':('large.txt',b'a'*(10*1024*1024+1),'text/plain')}).status_code==413


def test_intake_idempotency_and_restart(core,env,cfg,core_config):
    case=seed(env,cfg);key=str(uuid4());body={'case_id':case}
    one=core.post('/v1/intakes',json=body,headers={'Idempotency-Key':key})
    two=core.post('/v1/intakes',json=body,headers={'Idempotency-Key':key})
    assert one.json()==two.json()
    id=one.json()['incident_id'];consent(core,id)
    with TestClient(create_app(core_config)) as restarted:
        r=restarted.get(f'/v1/incidents/{id}',headers={'Authorization':'Bearer '+core_config['operator_token']})
    assert r.status_code==200 and r.json()['incident']['consent_active']
    assert core.post('/v1/intakes',json=body|{'title':'different'},headers={'Idempotency-Key':key}).status_code==409


def test_access_refusal_handoffs(core,env,cfg):
    id=create(core,seed(env,cfg));consent(core,id)
    statement(core,id,'claims','ACCESS_REFUSED',{'reason':'Representative identity not accepted'})
    assert core.get(f'/v1/incidents/{id}').json()['incident']['state']=='HUMAN_REVIEW'


def test_unauthenticated_cannot_read_or_upload(core,env,cfg):
    id=create(core,seed(env,cfg))
    assert core.get(f'/v1/incidents/{id}',headers={'Authorization':'Bearer wrong'}).status_code==403


def test_recording_access_requires_same_incident_and_consent(core,env,cfg):
    id=create(core,seed(env,cfg));consent(core,id)
    call=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'hospital','purpose':'No recording permission'}).json()['call_id']
    assert core.get(f'/v1/incidents/{id}/calls/{call}/recording').status_code==403
    other=create(core,seed(env,cfg))
    assert core.get(f'/v1/incidents/{other}/calls/{call}/recording').status_code==404


def test_received_statement_blocks_selectively_omitted_conflict(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    ids=evidence(core,env,cfg,id,case)
    received=statement(core,id,'claims','RECEIVED',{'received':True})
    response=core.post(f'/v1/incidents/{id}/actions',json={'destination':'current-tpa.example.invalid','evidence_ids':ids})
    assert response.status_code==409
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['next_step']['kind']=='HUMAN_REVIEW'
    assert received in detail['next_step']['evidence_ids']
    assert not detail['actions']


def test_repeated_statement_is_one_evidence_record_and_event(core,env,cfg):
    id=create(core,seed(env,cfg));consent(core,id)
    cid=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'hospital','purpose':'Retry fixture'}).json()['call_id']
    body={'call_id':cid,'source_role':'hospital','predicate':'SUBMITTED','value':{'submitted':True},'reference':'HOSP-FINAL-1042'}
    first=core.post(f'/v1/incidents/{id}/statements',json=body)
    second=core.post(f'/v1/incidents/{id}/statements',json=body)
    assert first.status_code==second.status_code==201
    assert first.json()['assertion_id']==second.json()['assertion_id']
    detail=core.get(f'/v1/incidents/{id}').json()
    assert len(detail['assertions'])==1
    assert len([e for e in detail['events'] if e['type']=='STATEMENT_RECORDED'])==1
    # A changed report remains distinct, preserving the conversation evidence.
    body['value']={'submitted':False}
    changed=core.post(f'/v1/incidents/{id}/statements',json=body)
    assert changed.status_code==201
    assert changed.json()['assertion_id']!=first.json()['assertion_id']


def test_negative_submission_value_cannot_establish_routing_discrepancy(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    statement(core,id,'hospital','SUBMITTED',{'submitted':False})
    statement(core,id,'claims','NOT_RECEIVED',{'found':False})
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']=='INVESTIGATING'
    assert detail['next_step']['kind']=='HUMAN_REVIEW'
    assert not detail['actions']


def test_proposal_cannot_omit_contradictory_statement_value(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    ids=evidence(core,env,cfg,id,case)
    statement(core,id,'hospital','SUBMITTED',{'submitted':False})
    result=core.post(f'/v1/incidents/{id}/actions',json={'destination':'current-tpa.example.invalid','evidence_ids':ids})
    assert result.status_code==409
    assert core.get(f'/v1/incidents/{id}').json()['next_step']['kind']=='HUMAN_REVIEW'


def test_incident_list_separates_fixtures_without_hiding_detail(core,env,cfg):
    id=create(core,seed(env,cfg))
    assert id not in {row['id'] for row in core.get('/v1/incidents').json()}
    listed=core.get('/v1/incidents?include_tests=true').json()
    assert id in {row['id'] for row in listed}
    assert next(row for row in listed if row['id']==id)['is_test'] is True
    assert core.get(f'/v1/incidents/{id}').status_code==200


def test_reference_change_without_supersedes_invalidates_approved_action(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    ids=evidence(core,env,cfg,id,case);aid=action(core,id,ids)
    assert authorize(core,id,aid).status_code==200
    call=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'hospital','purpose':'Unscripted reference correction'}).json()['call_id']
    result=core.post(f'/v1/incidents/{id}/statements',json={'call_id':call,'source_role':'hospital','predicate':'REFERENCE_CORRECTION',
        'value':{'corrected_reference':'HOSP-FINAL-1043'},'reference':'HOSP-FINAL-1042'})
    assert result.status_code==201,result.text
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['actions'][0]['state']=='STALE'
    assert detail['incident']['reference']=='HOSP-FINAL-1043'
    assert detail['incident']['state']=='INVESTIGATING'
    assert detail['next_step']['purpose']=='HOSPITAL_INITIAL'
    assert len(detail['assertions'])==4
    assert detail['assertions'][0]['support_status']=='REPORTED'


def test_unknown_submission_invalidates_an_existing_correction_approval(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    aid=action(core,id,evidence(core,env,cfg,id,case));assert authorize(core,id,aid).status_code==200
    statement(core,id,'hospital','SUBMISSION_UNKNOWN',{'confirmed':False,'details':'Hospital cannot confirm this request was submitted.'})
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['actions'][0]['state']=='STALE'
    assert detail['incident']['state']=='HUMAN_REVIEW'
    assert authorize(core,id,aid).status_code==409


def test_reported_resend_keeps_authorized_correction_pending_receipt(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    aid=action(core,id,evidence(core,env,cfg,id,case));assert authorize(core,id,aid).status_code==200
    statement(core,id,'hospital','SUBMITTED',{'submitted':True,'details':'Exact authorized correction resent through hospital portal; recipient receipt pending.'})
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']=='COORDINATING_CORRECTION'
    assert detail['incident']['decision_state']=='PENDING'
    assert detail['actions'][0]['state']=='AUTHORIZED'
    assert not detail['verified_receipts']


def test_later_submission_report_does_not_clear_human_review(core,env,cfg):
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    statement(core,id,'hospital','SUBMITTED',{'submitted':True})
    statement(core,id,'claims','NOT_RECEIVED',{'found':False,'lookup_scope':'designated claims queue'})
    statement(core,id,'hospital','ACCESS_REFUSED',{'reason':'Staff declined further participation.'})
    statement(core,id,'hospital','SUBMITTED',{'submitted':True,'details':'Another unverified report'})
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']=='HUMAN_REVIEW'
    assert not detail['verified_receipts']
