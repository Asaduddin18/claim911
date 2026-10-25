import copy
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.errors import InsufficientPrivilege
import pytest

from simulator.app import create_app
from simulator.verifier import verify_receipt, VerificationError


@pytest.fixture(scope='session')
def cfg():
    path = os.environ.get('CLAIM911_SIM_CONFIG')
    if not path:
        pytest.fail('Integration tests require CLAIM911_SIM_CONFIG and a running PostgreSQL database')
    return json.loads(Path(path).read_text())


@pytest.fixture
def env(cfg):
    return TestClient(create_app(cfg))


def auth(cfg,role):
    return {'Authorization':'Bearer '+cfg['tokens'][role]}


def seed(env,cfg,**kwargs):
    r=env.post('/evaluator/runs',json=kwargs,headers=auth(cfg,'evaluator'))
    assert r.status_code==201,r.text
    return r.json()['case_id']


def hospital(env,cfg,case):
    r=env.get(f'/hospital/cases/{case}',headers=auth(cfg,'hospital'))
    assert r.status_code==200,r.text
    return r.json()


def submit(env,cfg,case,**overrides):
    c=hospital(env,cfg,case)
    data={'destination':'current-tpa.example.invalid','reference':c['final_reference'],
          'request_type':'FINAL_AUTHORIZATION','packet':c['packet']}
    data.update(overrides)
    key=overrides.pop('_key',None) if '_key' in overrides else str(uuid4())
    r=env.post(f'/hospital/cases/{case}/submissions',json=data,
               headers={**auth(cfg,'hospital'),'Idempotency-Key':key})
    assert r.status_code==201,r.text
    return r.json()


def expected(env,cfg,case,sub_id):
    rows=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions']
    sub=next(s for s in rows if s['id']==sub_id)
    return {k:sub[k] for k in ['case_id','request_type','reference','revision','packet_hash','destination','dispatched_at']} | {
        'submission_id':sub['id'],'patient_id':sub['packet']['patient_id'],'route_id':'designated-claims'}


def public_key(cfg):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(cfg['signing_private_key']))
        .public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()


def receipts(env,cfg,case):
    return env.get(f'/claims/cases/{case}/receipts',headers=auth(cfg,'agent')).json()['receipts']


def test_manual_reconstruction_resolves_only_routing(env,cfg):
    case=seed(env,cfg)
    c=hospital(env,cfg,case)
    assert c['initial_status']=='AUTHORIZED'
    r=env.post('/claims/request-lookups',json={'case_id':case,'patient_id':c['patient_id'],
        'reference':c['final_reference'],'request_type':'FINAL_AUTHORIZATION'},headers=auth(cfg,'claims'))
    assert r.json()['requests']==[]
    rows=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions']
    assert rows[0]['transport_status']=='ACCEPTED_BY_TRANSPORT'
    assert rows[0]['destination']=='old-tpa.example.invalid'
    assert receipts(env,cfg,case)==[]
    sub=submit(env,cfg,case)
    ack=receipts(env,cfg,case)
    assert len(ack)==1
    result=verify_receipt(public_key(cfg),ack[0],expected(env,cfg,case,sub['submission_id']))
    assert result['coordination_state']=='BLOCKER_RESOLVED'
    assert result['decision_state']=='PENDING'
    after=env.get(f'/hospital/cases/{case}/submissions',headers=auth(cfg,'hospital')).json()['submissions']
    assert [x['revision'] for x in after]==[1,2]
    assert after[0]['destination']=='old-tpa.example.invalid'


@pytest.mark.parametrize('role,path,method',[
    ('agent','/evaluator/runs','post'),('hospital','/evaluator/runs','post'),
    ('claims','/hospital/cases/{case}','get'),('agent','/hospital/cases/{case}','get'),
    ('agent','/hospital/cases/{case}/submissions','post'),
])
def test_role_boundaries(env,cfg,role,path,method):
    case=seed(env,cfg)
    r=getattr(env,method)(path.format(case=case),headers=auth(cfg,role),**({'json':{}} if method=='post' else {}))
    assert r.status_code==403,r.text


def test_core_database_cannot_write_institution_tables(core_config):
    dsn=core_config['dsn']
    for table in ['hospital.cases','claims.receipts']:
        with psycopg.connect(dsn) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute(f'SELECT * FROM {table}')


def test_missing_documents_and_identifiers_do_not_get_receipt(env,cfg):
    case=seed(env,cfg)
    submit(env,cfg,case,packet={'patient_id':'DEMO-PATIENT-42'})
    assert receipts(env,cfg,case)==[]
    packet=hospital(env,cfg,case)['packet']
    packet['patient_id']='OTHER-PATIENT'
    submit(env,cfg,case,packet=packet)
    assert receipts(env,cfg,case)==[]


def test_withheld_ack_does_not_mean_verified(env,cfg):
    case=seed(env,cfg,withhold_receipt=True)
    submit(env,cfg,case)
    assert receipts(env,cfg,case)==[]
    truth=env.get(f'/evaluator/cases/{case}',headers=auth(cfg,'evaluator')).json()
    assert len(truth['claims_requests'])==1
    assert truth['claims_requests'][0]['decision_status']=='PENDING'


def test_already_received_counterexample_and_request_scope(env,cfg):
    case=seed(env,cfg,scenario='already_received')
    c=hospital(env,cfg,case)
    base={'case_id':case,'patient_id':c['patient_id'],'reference':c['final_reference']}
    final=env.post('/claims/request-lookups',json=base|{'request_type':'FINAL_AUTHORIZATION'},headers=auth(cfg,'claims'))
    initial=env.post('/claims/request-lookups',json=base|{'request_type':'PREAUTHORIZATION'},headers=auth(cfg,'claims'))
    assert len(final.json()['requests'])==1
    assert initial.json()['requests']==[]


def test_idempotent_submission_and_payload_conflict(env,cfg):
    case=seed(env,cfg)
    c=hospital(env,cfg,case)
    data={'destination':'current-tpa.example.invalid','reference':c['final_reference'],'packet':c['packet']}
    headers=auth(cfg,'hospital')|{'Idempotency-Key':str(uuid4())}
    first=env.post(f'/hospital/cases/{case}/submissions',json=data,headers=headers)
    second=env.post(f'/hospital/cases/{case}/submissions',json=data,headers=headers)
    assert first.status_code==second.status_code==201
    assert first.json()==second.json()
    assert len(receipts(env,cfg,case))==1
    data['reference']='CHANGED'
    assert env.post(f'/hospital/cases/{case}/submissions',json=data,headers=headers).status_code==409


@pytest.mark.parametrize('field,value',[('case_id','wrong'),('revision',1),('patient_id','wrong'),
    ('request_type','PREAUTHORIZATION'),('packet_hash','wrong'),('destination','old-tpa.example.invalid')])
def test_receipt_mismatch_rejected(env,cfg,field,value):
    case=seed(env,cfg)
    sub=submit(env,cfg,case)
    exp=expected(env,cfg,case,sub['submission_id'])
    exp[field]=value
    with pytest.raises(VerificationError):
        verify_receipt(public_key(cfg),receipts(env,cfg,case)[0],exp)


def test_forged_receipt_and_expiry_rejected(env,cfg):
    from datetime import datetime,timezone,timedelta
    case=seed(env,cfg)
    sub=submit(env,cfg,case)
    receipt=receipts(env,cfg,case)[0]
    forged=copy.deepcopy(receipt)
    forged['envelope']['revision']=99
    exp=expected(env,cfg,case,sub['submission_id'])
    with pytest.raises(VerificationError,match='signature'):
        verify_receipt(public_key(cfg),forged,exp)
    with pytest.raises(VerificationError,match='chronology'):
        verify_receipt(public_key(cfg),receipt,exp,datetime.now(timezone.utc)+timedelta(minutes=11))
