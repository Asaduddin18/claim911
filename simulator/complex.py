"""Role-separated synthetic discharge operations, independent of the coordinator."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib
import json
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Packet(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query_id: str
    claim_id: str
    reference: str
    documents: list[str] = Field(min_length=1, max_length=10)


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: str = Field(pattern='^(AUTHORIZED|DENIED)$')
    payable_inr: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=1000)


class SeedFaults(BaseModel):
    model_config=ConfigDict(extra='forbid')
    faults:list[str]=Field(default_factory=lambda:['unsigned_summary'],max_length=7)


def install(app, db, permit, signing_key, config):
    def attest(value,issuer):
        key=signing_key if issuer=='claims' else Ed25519PrivateKey.from_private_bytes(base64.b64decode(config[issuer+'_signing_private_key']))
        envelope={**value,'issued_at':datetime.now(timezone.utc).isoformat()}
        return {'envelope':envelope,'signature':base64.b64encode(key.sign(canonical(envelope))).decode()}
    def load(conn, table, case_id, lock=False):
        row = conn.execute(f"SELECT data FROM {table} WHERE id=%s" + (' FOR UPDATE' if lock else ''), (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Unknown synthetic complex case')
        return row['data']

    def save(conn, table, case_id, data):
        conn.execute(f"UPDATE {table} SET data=%s WHERE id=%s", (Jsonb(data), case_id))

    def seed_complex(case_id=None,faults=None):
        from sandbox.scenario_faults import validate_faults
        faults=validate_faults(['unsigned_summary'] if faults is None else faults)
        spec = json.loads((Path(__file__).parents[1]/'fixtures/complex-discharge/case.json').read_text())
        cid = case_id or uuid4()
        refs = spec['references']
        def doc(id, kind, owner, ready, amount=None):
            body = {'id': id, 'kind': kind, 'owner': owner, 'ready': ready, 'patient_id': spec['patient_id'],
                    'admission_id': spec['admission_id'], 'synthetic': True, 'revision': 2 if kind=='itemized_bill' else 1}
            if amount is not None:
                body['amount_inr'] = amount
            body['hash'] = sha(body)
            return body
        h = {'patient_id': spec['patient_id'], 'admission_id': spec['admission_id'], 'references': refs,
             'initial_provisional_inr': 150000, 'enhancement_requested_total_inr': 250000,
             'documents': [doc('bill-v2', 'itemized_bill', 'billing', True, 248000),
                           doc('summary-signed', 'signed_discharge_summary', 'medical_records', False),
                           doc('implant-invoice', 'implant_invoice', 'implant_store', True)],
             'dispatches': [], 'deposit_inr': 30000, 'clearance': None}
        h['scenario_faults']=faults
        h['billing_available']='desk_unavailable' not in faults
        for document in h['documents']:
            if document['kind']=='signed_discharge_summary':
                document['ready']='unsigned_summary' not in faults
                if document['ready']:document['signed_by']='SYNTHETIC_TREATING_TEAM'
            if document['kind']=='implant_invoice' and 'wrong_admission_invoice' in faults:document['admission_id']='ADM-SYN-OTHER'
            if document['kind']=='itemized_bill' and 'desk_unavailable' in faults:document['ready']=False
            if document['kind']=='itemized_bill' and 'old_bill' in faults:
                document.update(id='bill-v1',revision=1,amount_inr=252000)
            document['hash']=sha({k:v for k,v in document.items() if k!='hash'})
        q = {'references': refs, 'patient_id': spec['patient_id'], 'admission_id': spec['admission_id'],
             'query_state': 'OPEN', 'required_documents': ['itemized_bill', 'signed_discharge_summary', 'implant_invoice'],
             'packet_received': 'bill-v1', 'received_at': spec['clock']['received_at'],
             'target_at': spec['clock']['target'], 'enhancement_linked': False,
             'receipts': [], 'decision': None, 'synthetic': True}
        with db('hospital') as conn:
            conn.execute('INSERT INTO hospital.complex_cases(id,data) VALUES(%s,%s) ON CONFLICT(id) DO NOTHING', (cid, Jsonb(h)))
            # Check after the unique insert has serialized concurrent creators.
            # A conflicting seed must never be acknowledged with another fault set.
            previous=conn.execute('SELECT data FROM hospital.complex_cases WHERE id=%s FOR UPDATE',(cid,)).fetchone()
            if sorted(previous['data'].get('scenario_faults',['unsigned_summary']))!=faults:
                raise HTTPException(409,'Existing synthetic case has different seed faults')
        with db('claims') as conn:
            conn.execute('INSERT INTO claims.complex_cases(id,data) VALUES(%s,%s) ON CONFLICT(id) DO NOTHING', (cid, Jsonb(q)))
        return {'case_id': str(cid), 'scenario_id': spec['scenario_id'], 'synthetic': True,
                'patient_id': spec['patient_id'], 'admission_id': spec['admission_id'],
                'reported_problem': 'Medically cleared; hospital says insurance is pending.',
                'execution_mode': 'INSTITUTION_SIMULATOR_NO_PHONE_CALLS'}

    @app.post('/evaluator/complex-runs', dependencies=[Depends(permit('evaluator'))], status_code=201)
    def evaluator_seed():return seed_complex()

    if config.get('environment')=='sandbox':
        @app.post('/sandbox/scenarios/{run_id}',dependencies=[Depends(permit('sandbox_runner'))],status_code=201)
        def sandbox_seed(run_id:UUID,body:SeedFaults=SeedFaults()):
            seeded=seed_complex(run_id,body.faults)
            return {k:seeded[k] for k in ['case_id','patient_id','synthetic','execution_mode']}

    @app.get('/hospital/complex/{case_id}/desks/{desk}', dependencies=[Depends(permit('hospital'))])
    def desk_view(case_id: UUID, desk: str):
        if desk not in {'insurance', 'billing', 'medical_records', 'implant_store'}:
            raise HTTPException(404, 'Unknown desk')
        with db('hospital') as conn:
            h = load(conn, 'hospital.complex_cases', case_id)
        shared = {'synthetic': True, 'patient_id': h['patient_id'], 'admission_id': h['admission_id']}
        if desk == 'insurance':
            return shared | {'references': {k:h['references'][k] for k in ['preauthorization','enhancement','final_request']}, 'initial_provisional_inr': h['initial_provisional_inr'],
                             'enhancement_requested_total_inr': h['enhancement_requested_total_inr'],
                             'last_known_packet': 'bill-v1', 'dispatches': h['dispatches'], 'clearance': h['clearance']}
        return shared | {'documents': [d for d in h['documents'] if d['owner']==desk],
                         **({'deposit_inr': h['deposit_inr'],'available':h.get('billing_available',True),
                             'availability_reason':None if h.get('billing_available',True) else 'The billing sign-off officer is unavailable. The corrected bill cannot be released yet.',
                             'clearance':h['clearance']} if desk=='billing' else {})}

    @app.post('/hospital/complex/{case_id}/documents/{document_id}/release',
              dependencies=[Depends(permit('hospital'))])
    def release(case_id: UUID, document_id: str):
        # Institution-only release models records staff obtaining the clinician's signature.
        with db('hospital') as conn:
            h = load(conn, 'hospital.complex_cases', case_id, True)
            d = next((d for d in h['documents'] if d['id']==document_id), None)
            if not d:
                raise HTTPException(404, 'Unknown document')
            if not d['ready']:
                d['ready'] = True
                d['signed_by'] = 'SYNTHETIC_TREATING_TEAM'
                d['hash'] = sha({k:v for k,v in d.items() if k!='hash'})
                save(conn, 'hospital.complex_cases', case_id, h)
            return deepcopy(d)

    @app.get('/claims/complex/{case_id}/query', dependencies=[Depends(permit('claims'))])
    def query(case_id: UUID):
        with db('claims') as conn:
            return load(conn, 'claims.complex_cases', case_id)

    @app.post('/hospital/complex/{case_id}/dispatches', dependencies=[Depends(permit('hospital'))], status_code=201)
    def dispatch(case_id: UUID, body: Packet, idempotency_key: str = Header(min_length=8, max_length=128)):
        with db('hospital') as conn:
            h = load(conn, 'hospital.complex_cases', case_id, True)
            payload_hash = sha(body.model_dump())
            existing = next((s for s in h['dispatches'] if s['idempotency_key']==idempotency_key), None)
            if existing:
                if existing['body_hash']!=payload_hash:
                    raise HTTPException(409, 'Idempotency key payload conflict')
                return existing
            if len(body.documents)!=len(set(body.documents)):
                raise HTTPException(422, 'Duplicate document identifiers')
            if any(body.model_dump()[k]!=h['references'][r] for k,r in
                   [('query_id','query'),('claim_id','claim'),('reference','final_request')]):
                raise HTTPException(422, 'Query, claim and final reference must match this admission')
            docs = [next((d for d in h['documents'] if d['id']==id), None) for id in body.documents]
            if any(d is None or not d['ready'] for d in docs):
                raise HTTPException(422, 'Documents missing or not institution released')
            packet = {'case_id': str(case_id), 'patient_id': h['patient_id'], 'admission_id': h['admission_id'],
                      **body.model_dump(), 'document_records': docs}
            sub = {'id': str(uuid4()), 'submission_reference':f'HSP{len(h["dispatches"])+1:02d}', 'packet': packet, 'packet_hash': sha(packet), 'body_hash': payload_hash,
                   'idempotency_key': idempotency_key, 'status': 'DISPATCHED_NOT_VERIFIED',
                   'dispatched_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True}
            h['dispatches'].append(sub)
            save(conn, 'hospital.complex_cases', case_id, h)
            return sub

    @app.post('/claims/complex/{case_id}/receive/{submission_id}', dependencies=[Depends(permit('claims'))])
    def receive(case_id: UUID, submission_id: UUID):
        with db('hospital') as conn:
            h = load(conn, 'hospital.complex_cases', case_id)
        if 'withheld_receipt' in h.get('scenario_faults',[]):
            raise HTTPException(409,'Synthetic receiving desk has not confirmed this packet; receipt remains unverified')
        sub = next((s for s in h['dispatches'] if s['id']==str(submission_id)), None)
        if not sub:
            raise HTTPException(404, 'No such hospital dispatch')
        with db('claims') as conn:
            q = load(conn, 'claims.complex_cases', case_id, True)
            prior = next((r for r in q['receipts'] if r['envelope']['submission_id']==str(submission_id)), None)
            if prior:
                return prior
            packet = sub['packet']
            kinds = {d['kind'] for d in packet['document_records']}
            if not set(q['required_documents'])<=kinds:
                raise HTTPException(422, 'Query still missing required documents')
            if any(d['admission_id']!=q['admission_id'] or d['patient_id']!=q['patient_id']
                   for d in packet['document_records']):
                raise HTTPException(422, 'Document identity mismatch')
            envelope = {'receipt_id': str(uuid4()), 'case_id': str(case_id), 'submission_id': str(submission_id),
                        'packet_hash': sub['packet_hash'], 'query_id': q['references']['query'],
                        'claim_id': q['references']['claim'], 'status': 'RECEIVED',
                        'decision_status': 'PENDING', 'synthetic': True,
                        'source': 'demo-tpa-complex', 'issued_at': datetime.now(timezone.utc).isoformat()}
            if sub.get('submission_reference'):
                envelope['submission_reference']=sub['submission_reference']
            receipt = {'envelope': envelope, 'signature': base64.b64encode(signing_key.sign(canonical(envelope))).decode()}
            q['receipts'].append(receipt)
            q['query_state'] = 'RESPONSE_RECEIVED'
            save(conn, 'claims.complex_cases', case_id, q)
            return receipt

    @app.post('/claims/complex/{case_id}/link-enhancement', dependencies=[Depends(permit('claims'))])
    def link(case_id: UUID):
        with db('claims') as conn:
            q = load(conn, 'claims.complex_cases', case_id, True)
            if not q['receipts']:
                raise HTTPException(409, 'Complete query response receipt required')
            q['enhancement_linked'] = True
            q['query_state'] = 'ANSWERED'
            if not q.get('query_resolution'):
                q['query_resolution']=attest({'event_id':str(uuid4()),'case_id':str(case_id),
                    'source':'demo-tpa-complex','kind':'QUERY_ANSWERED','synthetic':True,
                    'query_id':q['references']['query'],'claim_id':q['references']['claim'],
                    'packet_hash':q['receipts'][-1]['envelope']['packet_hash'],
                    'receipt_id':q['receipts'][-1]['envelope']['receipt_id'],
                    'enhancement_reference':q['references']['enhancement'],'enhancement_linked':True,'query_state':'ANSWERED'},'claims')
            save(conn, 'claims.complex_cases', case_id, q)
            return {'synthetic': True, 'enhancement_linked': True, 'decision_status': 'PENDING',**q['query_resolution']}

    @app.get('/insurer/complex/{case_id}/review', dependencies=[Depends(permit('insurer'))])
    def review(case_id: UUID):
        with db('claims') as conn:
            q=load(conn,'claims.complex_cases',case_id)
        return {k:q.get(k) for k in ['patient_id','admission_id','references','query_state','enhancement_linked','decision','synthetic']}

    @app.post('/insurer/complex/{case_id}/decision', dependencies=[Depends(permit('insurer'))])
    def decision(case_id: UUID, body: Decision):
        with db('claims') as conn:
            q = load(conn, 'claims.complex_cases', case_id, True)
            if q['query_state']!='ANSWERED' or not q['enhancement_linked']:
                raise HTTPException(409, 'Query response and enhancement linkage required')
            with db('hospital') as hconn:
                h = load(hconn, 'hospital.complex_cases', case_id)
            conditions=h.get('scenario_faults',[])
            if 'pending_insurer' in conditions:raise HTTPException(409,'Synthetic insurer review is pending; no decision has been issued')
            if 'denied_insurer' in conditions and (body.outcome!='DENIED' or body.payable_inr!=0):
                raise HTTPException(409,'Synthetic institution review requires its fixed denial outcome')
            bill = next(d['amount_inr'] for d in h['documents'] if d['kind']=='itemized_bill')
            if body.payable_inr>bill or (body.outcome=='DENIED' and body.payable_inr!=0):
                raise HTTPException(422, 'Decision amounts inconsistent')
            value = {'id': str(uuid4()), **body.model_dump(), 'bill_inr': bill, 'synthetic': True,
                     'source': 'demo-insurer-complex', 'packet_hash': q['receipts'][-1]['envelope']['packet_hash'],
                     'case_id':str(case_id),'kind':'INSURER_DECISION','query_id':q['references']['query'],
                     'claim_id':q['references']['claim'],'reference':q['references']['final_request']}
            if q['decision']:
                if any(q['decision'][k]!=v for k,v in body.model_dump().items()):
                    raise HTTPException(409, 'Decision already issued')
                return q['decision']
            value={**value,**attest(value,'insurer')}
            q['decision'] = value
            save(conn, 'claims.complex_cases', case_id, q)
            return value

    @app.post('/insurer/complex/{case_id}/review-and-issue',dependencies=[Depends(permit('insurer'))])
    def review_and_issue(case_id:UUID):
        # The synthetic institution chooses its own result. The participant
        # cannot supply a coverage outcome or monetary arguments to this tool.
        with db('hospital') as conn:h=load(conn,'hospital.complex_cases',case_id)
        denied='denied_insurer' in h.get('scenario_faults',[])
        return decision(case_id,Decision(outcome='DENIED' if denied else 'AUTHORIZED',
            payable_inr=0 if denied else 230000,
            reason='Scripted synthetic insurer denial.' if denied else 'Scripted synthetic insurer adjudication. No coordinator or real insurance decision.'))

    @app.post('/hospital/complex/{case_id}/reconcile', dependencies=[Depends(permit('hospital'))])
    def reconcile(case_id: UUID):
        with db('claims') as conn:
            q = load(conn, 'claims.complex_cases', case_id)
        if not q['decision']:
            raise HTTPException(409, 'Institution-issued decision required')
        with db('hospital') as conn:
            h = load(conn, 'hospital.complex_cases', case_id, True)
            if h.get('clearance'):
                return h['clearance']
            decision = q['decision']
            patient = decision['bill_inr']-decision['payable_inr']
            h['clearance'] = {'synthetic': True, 'decision_id': decision['id'],
                              'bill_inr': decision['bill_inr'], 'insurer_payable_inr': decision['payable_inr'],
                              'patient_payable_inr': patient, 'deposit_inr': h['deposit_inr'],
                              'refund_due_inr': max(0,h['deposit_inr']-patient),
                              'balance_due_inr': max(0,patient-h['deposit_inr']),
                              'discharge_clearance': 'ISSUED' if patient<=h['deposit_inr'] else 'BALANCE_PENDING',
                              'refund_payment_state': 'NOT_VERIFIED'}
            h['clearance']={**h['clearance'],**attest({**h['clearance'],'case_id':str(case_id),
                'source':'demo-hospital-billing','kind':'DISCHARGE_RECONCILIATION',
                'packet_hash':decision['packet_hash'],'reference':q['references']['final_request']},'hospital')}
            save(conn, 'hospital.complex_cases', case_id, h)
            return h['clearance']
