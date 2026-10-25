"""Exercise institution operations; no model or telephony is used."""
import base64
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tests.test_environment import auth, public_key
from simulator.complex import canonical


def new(env,cfg):
    r=env.post('/evaluator/complex-runs',headers=auth(cfg,'evaluator'))
    assert r.status_code==201,r.text
    return r.json()['case_id']


def send(env,cfg,cid,documents):
    return env.post(f'/hospital/complex/{cid}/dispatches',headers={**auth(cfg,'hospital'),'Idempotency-Key':str(uuid4())},
        json={'query_id':'QRY25','claim_id':'CLM86','reference':'FIN63','documents':documents})


def release(env,cfg,cid):
    r=env.post(f'/hospital/complex/{cid}/documents/summary-signed/release',headers=auth(cfg,'hospital'))
    assert r.status_code==200
    assert r.json()['signed_by']=='SYNTHETIC_TREATING_TEAM'


def receive(env,cfg,cid,sub):
    return env.post(f'/claims/complex/{cid}/receive/{sub}',headers=auth(cfg,'claims'))


def test_complex_institutions_reconcile_only_after_recipient_and_insurer_gates(env,cfg):
    cid=new(env,cfg)
    hospital=env.get(f'/hospital/complex/{cid}/desks/insurance',headers=auth(cfg,'hospital')).json()
    assert 'required_documents' not in hospital and 'documents' not in hospital
    assert set(hospital['references'])=={'preauthorization','enhancement','final_request'}
    q=env.get(f'/claims/complex/{cid}/query',headers=auth(cfg,'claims')).json()
    assert q['query_state']=='OPEN' and not q['enhancement_linked']
    assert env.post(f'/hospital/complex/{cid}/reconcile',headers=auth(cfg,'hospital')).status_code==409
    assert env.post(f'/insurer/complex/{cid}/decision',headers=auth(cfg,'insurer'),
        json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Scripted synthetic review'}).status_code==409
    assert send(env,cfg,cid,['bill-v2','summary-signed','implant-invoice']).status_code==422
    release(env,cfg,cid)
    s=send(env,cfg,cid,['bill-v2','summary-signed','implant-invoice'])
    assert s.status_code==201,s.text
    sub=s.json()
    assert sub['status']=='DISPATCHED_NOT_VERIFIED'
    assert sub['submission_reference']=='HSP01'
    assert env.get(f'/claims/complex/{cid}/query',headers=auth(cfg,'claims')).json()['receipts']==[]
    r=receive(env,cfg,cid,sub['id'])
    assert r.status_code==200,r.text
    ack=r.json()
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key(cfg))).verify(
        base64.b64decode(ack['signature']),canonical(ack['envelope']))
    assert ack['envelope']['packet_hash']==sub['packet_hash']
    assert ack['envelope']['submission_reference']==sub['submission_reference']
    assert ack['envelope']['decision_status']=='PENDING'
    assert receive(env,cfg,cid,sub['id']).json()==ack
    assert env.post(f'/claims/complex/{cid}/link-enhancement',headers=auth(cfg,'claims')).status_code==200
    assert env.post(f'/hospital/complex/{cid}/reconcile',headers=auth(cfg,'hospital')).status_code==409
    decision=env.post(f'/insurer/complex/{cid}/decision',headers=auth(cfg,'insurer'),
        json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Scripted synthetic insurer review'})
    assert decision.status_code==200,decision.text
    clearance=env.post(f'/hospital/complex/{cid}/reconcile',headers=auth(cfg,'hospital')).json()
    assert clearance['patient_payable_inr']==18000
    assert clearance['refund_due_inr']==12000
    assert clearance['discharge_clearance']=='ISSUED'
    assert clearance['refund_payment_state']=='NOT_VERIFIED'


def test_incomplete_response_leaves_original_query_clock_and_decision_pending(env,cfg):
    cid=new(env,cfg)
    before=env.get(f'/claims/complex/{cid}/query',headers=auth(cfg,'claims')).json()
    sub=send(env,cfg,cid,['bill-v2']).json()
    assert receive(env,cfg,cid,sub['id']).status_code==422
    q=env.get(f'/claims/complex/{cid}/query',headers=auth(cfg,'claims')).json()
    assert q['query_state']=='OPEN' and not q['receipts'] and q['decision'] is None
    assert q['received_at']==before['received_at'] and q['target_at']==before['target_at']
    assert env.post(f'/claims/complex/{cid}/link-enhancement',headers=auth(cfg,'claims')).status_code==409


@pytest.mark.parametrize('role',['agent','hospital','claims'])
def test_only_insurer_can_issue_complex_decision(env,cfg,role):
    cid=new(env,cfg)
    assert env.post(f'/insurer/complex/{cid}/decision',headers=auth(cfg,role),
        json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Attempted unauthorized decision'}).status_code==403


def test_complex_org_views_and_mutations_are_role_scoped(env,cfg):
    cid=new(env,cfg)
    assert env.get(f'/claims/complex/{cid}/query',headers=auth(cfg,'hospital')).status_code==403
    assert env.get(f'/hospital/complex/{cid}/desks/billing',headers=auth(cfg,'claims')).status_code==403
    assert env.get(f'/hospital/complex/{cid}/desks/billing',headers=auth(cfg,'agent')).status_code==403
    assert env.post(f'/hospital/complex/{cid}/documents/summary-signed/release',headers=auth(cfg,'agent')).status_code==403
    assert env.post(f'/claims/complex/{cid}/receive/{uuid4()}',headers=auth(cfg,'hospital')).status_code==403


def test_billing_can_read_its_own_pending_clearance_without_inventing_an_outcome(env,cfg):
    cid=new(env,cfg)
    view=env.get(f'/hospital/complex/{cid}/desks/billing',headers=auth(cfg,'hospital')).json()
    assert 'clearance' in view and view['clearance'] is None
    assert view['deposit_inr']==30000
