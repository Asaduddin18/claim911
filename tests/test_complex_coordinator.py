"""Cross-service complex case: manual evidence explicitly labeled; no telephony."""
from copy import deepcopy
from uuid import uuid4
import pytest


from coordinator.complex import digest
from tests.test_environment import auth
from tests.test_coordinator import document,consent


def setup(core,env,cfg):
    cid=env.post('/evaluator/complex-runs',headers=auth(cfg,'evaluator')).json()['case_id']
    r=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={
        'case_id':cid,'title':'Synthetic complex discharge query','patient_id':'DEMO-PATIENT-84','reference':'FIN63'})
    assert r.status_code==201
    id=r.json()['incident_id'];consent(core,id)
    call=core.post(f'/v1/incidents/{id}/calls',json={'participant_role':'claims','purpose':'Manual complex query reconstruction',
        'transcript':[{'speaker':'participant','text':'Synthetic claims desk reports outstanding query QRY25 and three required documents.'}]}).json()['call_id']
    q=env.get(f'/claims/complex/{cid}/query',headers=auth(cfg,'claims')).json()
    did=document(core,id,'claims-query.json',q,'other')
    r=core.post(f'/v1/incidents/{id}/complex/query',json={'call_id':call,'document_id':did})
    assert r.status_code==201,r.text
    return id,cid


def collect(core,env,cfg,id,cid):
    env.post(f'/hospital/complex/{cid}/documents/summary-signed/release',headers=auth(cfg,'hospital'))
    for desk in ['billing','medical_records','implant_store']:
        record=env.get(f'/hospital/complex/{cid}/desks/{desk}',headers=auth(cfg,'hospital')).json()['documents'][0]
        did=document(core,id,desk+'.json',record,'other')
        r=core.post(f'/v1/incidents/{id}/complex/documents',json={'document_id':did})
        assert r.status_code==200,r.text
    return core.get(f'/v1/incidents/{id}/complex').json()


def approve(core,id,w):
    return core.post(f'/v1/incidents/{id}/complex/approve',json={'accepted':True,'packet_hash':w['packet_hash'],
        'confirmation':'Synthetic caregiver explicitly approves disclosure of the displayed exact packet.'})


def test_complex_coordination_exact_approval_and_independent_receipt(core,env,cfg):
    id,cid=setup(core,env,cfg);base=f'/v1/incidents/{id}/complex'
    w=core.get(base).json()
    assert len(w['tasks'])==3 and w['source_mode']=='MANUAL_RECONSTRUCTION'
    assert w['next_step']=='COLLECT_DOCUMENTS'
    assert approve(core,id,{'packet_hash':'premature'}).status_code==409
    w=collect(core,env,cfg,id,cid)
    assert w['next_step']=='EXACT_PACKET_APPROVAL'
    assert approve(core,id,w).status_code==200
    packet=w['packet'];request={k:packet[k] for k in ['query_id','claim_id','reference','documents']}
    s=env.post(f'/hospital/complex/{cid}/dispatches',headers={**auth(cfg,'hospital'),'Idempotency-Key':str(uuid4())},json=request)
    assert s.status_code==201,s.text
    sub=s.json()
    assert sub['packet_hash']==w['packet_hash']
    did=document(core,id,'hospital-query-dispatch.json',sub,'dispatch')
    ack=env.post(f'/claims/complex/{cid}/receive/{sub["id"]}',headers=auth(cfg,'claims')).json()
    bad=deepcopy(ack);bad['envelope']['packet_hash']='wrong'
    assert core.post(base+'/verify',json={'dispatch_document_id':did,'receipt':bad}).status_code==422
    r=core.post(base+'/verify',json={'dispatch_document_id':did,'receipt':ack})
    assert r.status_code==200,r.text
    assert r.json()['receipt']==ack
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']=='QUERY_RESPONSE_RECEIVED'
    assert detail['incident']['decision_state']=='PENDING'
    assert len(detail['verified_receipts'])==1
    assert r.json()['next_step']=='TPA_QUERY_AND_ENHANCEMENT_FOLLOWUP'


def test_complex_packet_revision_and_consent_invalidate_approval(core,env,cfg):
    id,cid=setup(core,env,cfg);base=f'/v1/incidents/{id}/complex'
    w=collect(core,env,cfg,id,cid);assert approve(core,id,w).status_code==200
    bill=deepcopy(w['documents']['itemized_bill']['record']);bill['revision']=3;bill['amount_inr']=249000
    bill['hash']=digest({k:v for k,v in bill.items() if k!='hash'})
    did=document(core,id,'changed-bill-v3.json',bill,'bill')
    r=core.post(base+'/documents',json={'document_id':did})
    assert r.status_code==200
    assert not r.json()['approval_current'] and r.json()['packet_hash']!=w['packet_hash']
    assert approve(core,id,w).status_code==409
    assert approve(core,id,r.json()).status_code==200
    consent(core,id,False)
    assert core.get(base).json()['next_step']=='CONSENT_REQUIRED'
    assert approve(core,id,r.json()).status_code==409
    consent(core,id,True)
    assert not core.get(base).json()['approval_current']


def test_complex_documents_reject_wrong_admission_and_unsigned_summary(core,env,cfg):
    id,cid=setup(core,env,cfg);base=f'/v1/incidents/{id}/complex'
    records=env.get(f'/hospital/complex/{cid}/desks/medical_records',headers=auth(cfg,'hospital')).json()['documents']
    did=document(core,id,'unsigned.json',records[0],'other')
    assert core.post(base+'/documents',json={'document_id':did}).status_code==422
    bill=env.get(f'/hospital/complex/{cid}/desks/billing',headers=auth(cfg,'hospital')).json()['documents'][0]
    bill['admission_id']='ANOTHER-ADMISSION'
    bill['hash']=digest({k:v for k,v in bill.items() if k!='hash'})
    did=document(core,id,'wrong-patient.json',bill,'bill')
    assert core.post(base+'/documents',json={'document_id':did}).status_code==422
    assert all(t['state']=='NEEDED' for t in core.get(base).json()['tasks'])


def test_complex_workflow_does_not_queue_old_routing_call_objectives(core,env,cfg):
    id,cid=setup(core,env,cfg)
    participant=core.post(f'/v1/incidents/{id}/participants',json={'role':'hospital','phone':'+919999999999',
        'verified':True,'demo_consent':'Synthetic fixture only, no telephone contact.'}).json()['participant_id']
    r=core.post(f'/v1/incidents/{id}/call-jobs',headers={'Idempotency-Key':str(uuid4())},
        json={'participant_id':participant,'purpose':'HOSPITAL_INITIAL'})
    assert r.status_code==409
    assert not any(c['mode']=='BOLNA' for c in core.get(f'/v1/incidents/{id}').json()['calls'])


def ready_for_final(core,env,cfg):
    id,cid=setup(core,env,cfg);base=f'/v1/incidents/{id}/complex'
    w=collect(core,env,cfg,id,cid);assert approve(core,id,w).status_code==200
    p=w['packet']
    sub=env.post(f'/hospital/complex/{cid}/dispatches',headers={**auth(cfg,'hospital'),'Idempotency-Key':str(uuid4())},
        json={k:p[k] for k in ['query_id','claim_id','reference','documents']}).json()
    ack=env.post(f'/claims/complex/{cid}/receive/{sub["id"]}',headers=auth(cfg,'claims')).json()
    did=document(core,id,'dispatch.json',sub,'dispatch')
    assert core.post(base+'/verify',json={'dispatch_document_id':did,'receipt':ack}).status_code==200
    return id,cid,base,{'dispatch_document_id':did,'receipt':ack}


@pytest.mark.parametrize('outcome,payable,expected_state,refund',[
    ('AUTHORIZED',230000,'DISCHARGE_CLEARED',12000),('DENIED',0,'PATIENT_BALANCE_PENDING',0)])
def test_complex_signed_final_outcome_and_hospital_reconciliation(core,env,cfg,outcome,payable,expected_state,refund):
    id,cid,base,receipt_body=ready_for_final(core,env,cfg)
    assert core.post(base+'/decision',json={'document_id':str(uuid4())}).status_code==409
    resolution=env.post(f'/claims/complex/{cid}/link-enhancement',headers=auth(cfg,'claims')).json()
    rd=document(core,id,'tpa-query-answer.json',resolution,'other')
    assert core.post(base+'/query-resolution',json={'document_id':rd}).status_code==200
    dec=env.post(f'/insurer/complex/{cid}/decision',headers=auth(cfg,'insurer'),
        json={'outcome':outcome,'payable_inr':payable,'reason':'Synthetic institution decision for test'}).json()
    dd=document(core,id,'insurer-decision.json',dec,'other')
    r=core.post(base+'/decision',json={'document_id':dd})
    assert r.status_code==200,r.text
    clear=env.post(f'/hospital/complex/{cid}/reconcile',headers=auth(cfg,'hospital')).json()
    cd=document(core,id,'hospital-clearance.json',clear,'other')
    r=core.post(base+'/clearance',json={'document_id':cd})
    assert r.status_code==200,r.text
    assert r.json()['clearance']['envelope']['refund_due_inr']==refund
    assert r.json()['clearance']['envelope']['refund_payment_state']=='NOT_VERIFIED'
    detail=core.get(f'/v1/incidents/{id}').json()
    assert detail['incident']['state']==expected_state
    assert detail['incident']['decision_state']==outcome
    # Replayed earlier checkpoints cannot regress a completed later state.
    assert core.post(base+'/verify',json=receipt_body).status_code==200
    assert core.post(base+'/query-resolution',json={'document_id':rd}).status_code==200
    assert core.post(base+'/decision',json={'document_id':dd}).status_code==200
    assert core.get(f'/v1/incidents/{id}').json()['incident']['state']==expected_state


def test_complex_issuer_signature_and_case_binding_are_required(core,env,cfg):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    from coordinator.complex import canonical
    id,cid,base,_=ready_for_final(core,env,cfg)
    resolution=env.post(f'/claims/complex/{cid}/link-enhancement',headers=auth(cfg,'claims')).json()
    bad=deepcopy(resolution);bad['envelope']['case_id']=str(uuid4())
    # Even a valid claims signature on a different case cannot close this query.
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(cfg['signing_private_key']))
    bad['signature']=base64.b64encode(key.sign(canonical(bad['envelope']))).decode()
    did=document(core,id,'wrong-case-resolution.json',bad,'other')
    assert core.post(base+'/query-resolution',json={'document_id':did}).status_code==422
    did=document(core,id,'valid-resolution.json',resolution,'other')
    assert core.post(base+'/query-resolution',json={'document_id':did}).status_code==200
    dec=env.post(f'/insurer/complex/{cid}/decision',headers=auth(cfg,'insurer'),
        json={'outcome':'AUTHORIZED','payable_inr':230000,'reason':'Synthetic scripted insurer review'}).json()
    bad=deepcopy(dec)
    bad['signature']=base64.b64encode(key.sign(canonical(bad['envelope']))).decode()
    did=document(core,id,'claims-impersonates-insurer.json',bad,'other')
    assert core.post(base+'/decision',json={'document_id':did}).status_code==422
    assert core.get(f'/v1/incidents/{id}').json()['incident']['decision_state']=='PENDING'
