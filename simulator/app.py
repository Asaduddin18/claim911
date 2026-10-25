"""Synthetic institution environment. The coordinator cannot write institution data."""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Literal
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Seed(StrictModel):
    withhold_receipt: bool = False
    scenario: Literal['wrong_destination', 'already_received'] = 'wrong_destination'


class Submission(StrictModel):
    destination: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=80)
    request_type: Literal['FINAL_AUTHORIZATION'] = 'FINAL_AUTHORIZATION'
    packet: dict


class Lookup(StrictModel):
    case_id: UUID
    patient_id: str
    reference: str
    request_type: Literal['PREAUTHORIZATION','FINAL_AUTHORIZATION']
    queue: Literal['designated-claims'] = 'designated-claims'


def create_app(config=None):
    if config is None:
        config = json.loads(Path(os.environ['CLAIM911_SIM_CONFIG']).read_text())
    app = FastAPI(title='Claim911 institution simulator', version='0.1.0')
    app.state.config = config
    signing_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(config['signing_private_key']))

    @contextmanager
    def db(role):
        with psycopg.connect(config[f'{role}_dsn'], row_factory=dict_row) as conn:
            yield conn

    def permit(*roles):
        def auth(authorization: str = Header(default='')):
            token = authorization.removeprefix('Bearer ')
            for role in roles:
                expected = config['tokens'].get(role)
                if expected and secrets.compare_digest(token, expected):
                    return role
            raise HTTPException(403, 'Role is not permitted for this operation')
        return auth

    def get_case(case_id):
        with db('hospital') as conn:
            case = conn.execute('SELECT * FROM hospital.cases WHERE id=%s', (case_id,)).fetchone()
        if not case:
            raise HTTPException(404, 'Unknown synthetic case')
        return case

    def deliver(sub):
        """Claims-owned receipt creation, independent of hospital dispatch assertions."""
        with db('claims') as conn:
            route = conn.execute('SELECT * FROM claims.routes WHERE destination=%s AND active AND request_type=%s',
                                 (sub['destination'], sub['request_type'])).fetchone()
            if not route:
                return 'NOT_IN_DESIGNATED_QUEUE'
            required = {'patient_id','admission_id','final_bill','discharge_summary'}
            if not required.issubset(sub['packet']) or any(not sub['packet'][x] for x in required):
                return 'DOCUMENT_QUERY'
            case = get_case(sub['case_id'])
            if sub['packet']['patient_id'] != case['patient_id'] or sub['packet']['admission_id'] != case['admission_id']:
                return 'IDENTIFIER_MISMATCH'
            request_id = uuid4()
            received_at = datetime.now(timezone.utc)
            request = conn.execute('''INSERT INTO claims.requests
                (id,case_id,submission_id,patient_id,reference,request_type,revision,packet_hash,route_id,received_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(submission_id) DO NOTHING RETURNING *''',
                (request_id,sub['case_id'],sub['id'],sub['packet']['patient_id'],sub['reference'],sub['request_type'],
                 sub['revision'],sub['packet_hash'],route['id'],received_at)).fetchone()
            if not request:
                request = conn.execute('SELECT * FROM claims.requests WHERE submission_id=%s',(sub['id'],)).fetchone()
            control = conn.execute('SELECT withhold_receipt FROM claims.test_controls WHERE case_id=%s',
                                   (sub['case_id'],)).fetchone()
            if control and control['withhold_receipt']:
                return 'RECEIVED_WITHOUT_ACKNOWLEDGMENT'
            receipt_id = uuid4()
            envelope = {
                'source':'demo-designated-claims', 'event_id':str(receipt_id), 'receipt_id':str(receipt_id),
                'simulated':True, 'case_id':str(sub['case_id']), 'submission_id':str(sub['id']),
                'request_type':sub['request_type'], 'reference':sub['reference'], 'revision':sub['revision'],
                'patient_id':sub['packet']['patient_id'], 'packet_hash':sub['packet_hash'],
                'route_id':route['id'], 'destination':sub['destination'],
                'received_at':request['received_at'].isoformat(), 'issued_at':datetime.now(timezone.utc).isoformat(),
                'status':'RECEIVED', 'decision_status':'PENDING',
            }
            signature = base64.b64encode(signing_key.sign(canonical(envelope))).decode()
            conn.execute('INSERT INTO claims.receipts(id,request_id,envelope,signature) VALUES(%s,%s,%s,%s) ON CONFLICT(request_id) DO NOTHING',
                         (receipt_id,request['id'],Jsonb(envelope),signature))
        return 'RECEIVED'

    from simulator.complex import install
    install(app, db, permit, signing_key, config)

    @app.get('/health')
    def health():
        with db('hospital') as conn:
            conn.execute('SELECT 1')
        return {'status':'ok','simulated':True,'environment':config.get('environment','legacy')}

    @app.get('/', response_class=HTMLResponse)
    def home():
        return (Path(__file__).parent/'portal.html').read_text()

    @app.post('/evaluator/runs', dependencies=[Depends(permit('evaluator'))], status_code=201)
    def seed(body: Seed):
        case_id,run_id,sub_id = uuid4(),uuid4(),uuid4()
        packet = {'patient_id':'DEMO-PATIENT-42','admission_id':'DEMO-ADMISSION-9',
                  'final_bill':{'amount_inr':190000,'synthetic':True},
                  'discharge_summary':{'medical_status':'READY','synthetic':True}}
        created = datetime.now(timezone.utc)
        destination = 'old-tpa.example.invalid' if body.scenario=='wrong_destination' else 'current-tpa.example.invalid'
        with db('claims') as conn:
            conn.execute('''INSERT INTO claims.routes(id,organization,destination,request_type,active)
                VALUES('designated-claims','Demo Claims Desk','current-tpa.example.invalid','FINAL_AUTHORIZATION',true)
                ON CONFLICT(id) DO NOTHING''')
            conn.execute('INSERT INTO claims.test_controls(case_id,withhold_receipt) VALUES(%s,%s)',
                         (case_id,body.withhold_receipt))
        with db('hospital') as conn:
            conn.execute('''INSERT INTO hospital.cases(id,run_id,patient_alias,patient_id,admission_id,
                initial_reference,initial_status,final_reference,medical_status,packet)
                VALUES(%s,%s,'Demo Patient A','DEMO-PATIENT-42','DEMO-ADMISSION-9','PREAUTH-077',
                'AUTHORIZED','HOSP-FINAL-1042','READY',%s)''',(case_id,run_id,Jsonb(packet)))
            conn.execute('''INSERT INTO hospital.submissions(id,case_id,reference,request_type,revision,
                destination,packet,packet_hash,dispatched_at,transport_status,delivery_state,idempotency_key,body_hash)
                VALUES(%s,%s,'HOSP-FINAL-1042','FINAL_AUTHORIZATION',1,%s,%s,%s,%s,
                'ACCEPTED_BY_TRANSPORT','DISPATCHED',%s,%s)''',
                (sub_id,case_id,destination,Jsonb(packet),digest(packet),created,f'seed-{run_id}',digest(packet)))
        with db('hospital') as conn:
            sub = conn.execute('SELECT * FROM hospital.submissions WHERE id=%s',(sub_id,)).fetchone()
        state = deliver(sub)
        with db('hospital') as conn:
            conn.execute('UPDATE hospital.submissions SET delivery_state=%s WHERE id=%s',(state,sub_id))
        return {'case_id':str(case_id),'run_id':str(run_id),'simulated':True,
                'public_case_facts':'Reported confusion over initial versus final authorization and discharge delay.',
                'synthetic_additions':'Routing cause, identifiers, packet, timestamps, institutional operations.'}

    @app.get('/hospital/cases/{case_id}', dependencies=[Depends(permit('hospital','evaluator'))])
    def hospital_case(case_id: UUID):
        return get_case(case_id)

    @app.get('/hospital/cases/{case_id}/submissions', dependencies=[Depends(permit('hospital','evaluator'))])
    def submissions(case_id: UUID):
        get_case(case_id)
        with db('hospital') as conn:
            rows = conn.execute('SELECT * FROM hospital.submissions WHERE case_id=%s ORDER BY revision',(case_id,)).fetchall()
        return {'simulated':True,'submissions':rows}

    @app.post('/hospital/cases/{case_id}/submissions', dependencies=[Depends(permit('hospital'))], status_code=201)
    def submit(case_id: UUID, body: Submission, idempotency_key: str = Header(min_length=8,max_length=128)):
        get_case(case_id)
        payload_hash = digest({'case_id':str(case_id),**body.model_dump()})
        with db('hospital') as conn:
            # Serializing on the case prevents concurrent revision races.
            conn.execute('SELECT id FROM hospital.cases WHERE id=%s FOR UPDATE',(case_id,))
            existing = conn.execute('SELECT * FROM hospital.submissions WHERE idempotency_key=%s',(idempotency_key,)).fetchone()
            if existing:
                if existing['body_hash'] != payload_hash:
                    raise HTTPException(409,'Idempotency key already used for different submission')
                sub = existing
            else:
                revision = conn.execute('SELECT COALESCE(MAX(revision),0)+1 AS next FROM hospital.submissions WHERE case_id=%s',
                                        (case_id,)).fetchone()['next']
                sub = conn.execute('''INSERT INTO hospital.submissions(id,case_id,reference,request_type,revision,
                    destination,packet,packet_hash,dispatched_at,transport_status,delivery_state,idempotency_key,body_hash)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,now(),'ACCEPTED_BY_TRANSPORT','DISPATCHED',%s,%s) RETURNING *''',
                    (uuid4(),case_id,body.reference,body.request_type,revision,body.destination,Jsonb(body.packet),
                     digest(body.packet),idempotency_key,payload_hash)).fetchone()
        state = deliver(sub)
        with db('hospital') as conn:
            conn.execute('UPDATE hospital.submissions SET delivery_state=%s WHERE id=%s',(state,sub['id']))
        # Do not tell the hospital that final authorization was granted.
        return {'submission_id':str(sub['id']),'revision':sub['revision'],'packet_hash':sub['packet_hash'],
                'dispatch_status':'ACCEPTED_BY_TRANSPORT','simulated':True}

    @app.get('/claims/routing', dependencies=[Depends(permit('claims','agent','evaluator'))])
    def routes():
        with db('claims') as conn:
            return {'simulated':True,'routes':conn.execute('SELECT * FROM claims.routes WHERE active').fetchall()}

    @app.post('/claims/request-lookups', dependencies=[Depends(permit('claims','evaluator'))])
    def lookup(body: Lookup):
        with db('claims') as conn:
            rows = conn.execute('''SELECT * FROM claims.requests WHERE case_id=%s AND patient_id=%s AND reference=%s
                AND request_type=%s AND route_id=%s ORDER BY revision''',
                (body.case_id,body.patient_id,body.reference,body.request_type,body.queue)).fetchall()
            lookup_id = uuid4()
            conn.execute('INSERT INTO claims.lookups(id,case_id,scope,result_count) VALUES(%s,%s,%s,%s)',
                         (lookup_id,body.case_id,Jsonb(body.model_dump(mode='json')),len(rows)))
        return {'lookup_id':str(lookup_id),'scope':body.model_dump(mode='json'),'requests':rows,'simulated':True}

    @app.get('/claims/cases/{case_id}/receipts', dependencies=[Depends(permit('claims','agent','evaluator'))])
    def receipts(case_id: UUID):
        with db('claims') as conn:
            rows = conn.execute('''SELECT r.envelope,r.signature FROM claims.receipts r JOIN claims.requests q
                ON q.id=r.request_id WHERE q.case_id=%s ORDER BY q.revision''',(case_id,)).fetchall()
        return {'receipts':rows,'simulated':True}

    @app.get('/evaluator/cases/{case_id}', dependencies=[Depends(permit('evaluator'))])
    def truth(case_id: UUID):
        case = get_case(case_id)
        with db('claims') as conn:
            requests = conn.execute('SELECT * FROM claims.requests WHERE case_id=%s',(case_id,)).fetchall()
            lookups = conn.execute('SELECT * FROM claims.lookups WHERE case_id=%s',(case_id,)).fetchall()
        return {'case':case,'hospital':submissions(case_id),'claims_requests':requests,'lookups':lookups,
                'simulated':True}

    return app
