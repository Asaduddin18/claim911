"""Incident coordinator. Hospital submission credentials are deliberately absent."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from simulator.app import canonical, digest
from simulator.verifier import verify_receipt, VerificationError
from coordinator.bolna import Bolna
from coordinator.planner import next_step
from coordinator.evidence import supports_predicate
from coordinator.objectives import call_objective


ROLE_PREDICATES={'hospital':{'SUBMITTED','SUBMISSION_UNKNOWN','DESTINATION','REFERENCE_CORRECTION','ACCESS_REFUSED'},
                 'claims':{'NOT_RECEIVED','RECEIVED','ACCESS_REFUSED'},'caregiver':{'ACCESS_REFUSED'}}


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Intake(Model):
    reference_known: bool = True
    case_id: UUID
    title: str = Field(default='Cashless discharge request delayed',min_length=1,max_length=160)
    patient_id: str = Field(default='DEMO-PATIENT-42',min_length=1,max_length=100)
    reference: str = Field(default='HOSP-FINAL-1042',min_length=1,max_length=100)


class Consent(Model):
    accepted: bool
    confirmation: str = Field(min_length=5,max_length=2000)


class Turn(Model):
    speaker: Literal['assistant','participant']
    text: str = Field(min_length=1,max_length=12000)


class CallRecord(Model):
    participant_role: Literal['caregiver','hospital','claims']
    purpose: str = Field(min_length=1,max_length=300)
    mode: Literal['MANUAL_RECONSTRUCTION'] = 'MANUAL_RECONSTRUCTION'
    transcript: list[Turn] = Field(default_factory=list,max_length=100)
    recording_consent: bool = False


class HostedTextEvidence(Model):
    source: Literal['BOLNA_HOSTED_TEXT_SIMULATOR']
    turns: list[Turn] = Field(min_length=1,max_length=100)
    attestation: str = Field(min_length=20,max_length=1000)


class Statement(Model):
    call_id: UUID | None = None
    document_id: UUID | None = None
    source_role: Literal['caregiver','hospital','claims']
    predicate: Literal['SUBMITTED','SUBMISSION_UNKNOWN','NOT_RECEIVED','DESTINATION','RECEIVED','REFERENCE_CORRECTION','ACCESS_REFUSED']
    value: dict
    reference: str
    request_type: Literal['PREAUTHORIZATION','FINAL_AUTHORIZATION'] = 'FINAL_AUTHORIZATION'
    supersedes_id: UUID | None = None


class Correction(Model):
    destination: str = Field(min_length=1,max_length=160)
    route_id: Literal['designated-claims'] = 'designated-claims'
    evidence_ids: list[UUID] = Field(min_length=2,max_length=20)


class Verify(Model):
    action_id: UUID
    dispatch_document_id: UUID
    receipt: dict


class Participant(Model):
    role: Literal['caregiver','hospital','claims']
    phone: str = Field(pattern=r'^\+[1-9]\d{7,14}$')
    verified: bool
    demo_consent: str = Field(min_length=10,max_length=2000)
    recording_consent: bool = False


class QueueCall(Model):
    participant_id: UUID
    purpose: Literal['CAREGIVER_INTAKE','CAREGIVER_COMPLEX_UPDATE','HOSPITAL_REFERENCE_DISCOVERY','HOSPITAL_INITIAL','CLAIMS_LOOKUP','HOSPITAL_FOLLOWUP','CORRECTION_REQUEST','CAREGIVER_UPDATE','QUERY_DISCOVERY','BILLING_DOCUMENT','RECORDS_DOCUMENT','IMPLANT_DOCUMENT','PACKET_SUBMISSION','TPA_QUERY_FOLLOWUP','INSURER_FOLLOWUP','DISCHARGE_FOLLOWUP']
    action_id: UUID | None = None


class HostedTextFailure(Model):
    source: Literal['BOLNA_HOSTED_TEXT_SIMULATOR']
    reason: Literal['CONNECTION_NOT_STARTED']
    attestation: str = Field(min_length=20,max_length=2000)


class ReferenceDiscovery(Model):
    admission_id: str = Field(min_length=1,max_length=100)
    initial_reference: str = Field(min_length=1,max_length=100)
    enhancement_reference: str = Field(min_length=1,max_length=100)
    final_reference: str = Field(min_length=1,max_length=100)
    submission_status: Literal['REPORTED_SUBMITTED','UNKNOWN']
    summary: str = Field(min_length=1,max_length=2000)


class ReconcileCall(Model):
    execution_id: UUID


class ToolStatement(Model):
    predicate: Literal['SUBMITTED','SUBMISSION_UNKNOWN','NOT_RECEIVED','DESTINATION','RECEIVED','REFERENCE_CORRECTION','ACCESS_REFUSED']
    value: dict
    reference: str
    request_type: Literal['PREAUTHORIZATION','FINAL_AUTHORIZATION']
    document_id: UUID | None = None
    supersedes_id: UUID | None = None


def create_app(config=None):
    if config is None:
        config=json.loads(Path(os.environ['CLAIM911_CORE_CONFIG']).read_text())
    app=FastAPI(title='Claim911 incident coordinator',version='0.1.0')
    app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:3110','http://localhost:3110'],
        allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type','Idempotency-Key'])

    @contextmanager
    def db():
        with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
            yield conn

    with db() as conn:
        conn.execute((Path(__file__).parent/'schema.sql').read_text())

    def operator(authorization: str=Header(default='')):
        if not secrets.compare_digest(authorization.removeprefix('Bearer '),config['operator_token']):
            raise HTTPException(403,'Operator session required')

    def incident(conn,id,lock=False):
        row=conn.execute('SELECT * FROM coordinator.incidents WHERE id=%s'+(' FOR UPDATE' if lock else ''),(id,)).fetchone()
        if not row:
            raise HTTPException(404,'Unknown incident')
        return row

    def hospital_report(conn,id):
        report=conn.execute("SELECT payload FROM coordinator.events WHERE incident_id=%s AND type='HOSPITAL_REFERENCES_REPORTED' ORDER BY sequence DESC LIMIT 1",(id,)).fetchone()
        return report['payload'] if report else None

    def event(conn,id,type,payload):
        conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',(id,type,Jsonb(payload)))

    def require_consent(row):
        if not row['consent_active']:
            raise HTTPException(409,'Incident consent is missing or revoked')

    from coordinator.complex import install
    complex_view=install(app,db,operator,incident,require_consent,event,config,lambda token:bound_call(token))
    from coordinator.sandbox_calls import install as install_sandbox_audio
    install_sandbox_audio(app,db,operator,incident,require_consent,event,config)
    from coordinator.browser_voice import install as install_browser_voice
    install_browser_voice(app,db,operator,incident,require_consent,event,config)

    @app.get('/health')
    def health():
        with db() as conn:
            conn.execute('SELECT 1')
        return {'status':'ok','simulated':True,'environment':config.get('environment','legacy'),'real_calls_enabled':bool(config.get('live_calls_enabled') and config.get('bolna_api_key'))}

    @app.get('/v1/calling-status',dependencies=[Depends(operator)])
    def calling_status():
        configured=bool(config.get('live_calls_enabled') and config.get('bolna_api_key') and config.get('bolna_agent_id'))
        paused=bool(config.get('outbound_paused'))
        return {'configured':configured,'paused':paused,'can_queue_calls':configured and not paused,
                'reason':config.get('call_pause_reason','Calls are on hold.') if paused else ('Calling is configured.' if configured else 'Live calling is not configured.')}

    @app.get('/v1/incidents',dependencies=[Depends(operator)])
    def list_incidents(include_tests:bool=False):
        with db() as conn:
            return conn.execute('SELECT * FROM coordinator.incidents WHERE (%s OR NOT is_test) ORDER BY created_at DESC LIMIT 100',(include_tests,)).fetchall()

    @app.post('/v1/intakes',dependencies=[Depends(operator)],status_code=201)
    def intake(body:Intake,idempotency_key:str=Header(min_length=8,max_length=128)):
        bh=digest(body.model_dump(mode='json'))
        with db() as conn:
            # A global key lock serializes concurrent duplicate commands.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(idempotency_key,))
            old=conn.execute('SELECT * FROM coordinator.command_results WHERE key=%s',(idempotency_key,)).fetchone()
            if old:
                if old['body_hash']!=bh:
                    raise HTTPException(409,'Command key conflicts with prior payload')
                return old['response']
            id=uuid4()
            title=('[Integration test] ' if config.get('test_mode') else '')+body.title
            conn.execute('INSERT INTO coordinator.incidents(id,case_id,title,patient_id,reference,is_test) VALUES(%s,%s,%s,%s,%s,%s)',
                (id,body.case_id,title,body.patient_id,body.reference if body.reference_known else 'UNCONFIRMED_FINAL_REFERENCE',bool(config.get('test_mode'))))
            event(conn,id,'INTAKE_CREATED',{'simulated':True,'case_id':str(body.case_id)})
            response={'incident_id':str(id),'state':'AWAITING_CONSENT','simulated':True}
            conn.execute('INSERT INTO coordinator.command_results(key,body_hash,response) VALUES(%s,%s,%s)',
                (idempotency_key,bh,Jsonb(response)))
            return response

    @app.get('/v1/incidents/{id}',dependencies=[Depends(operator)])
    def detail(id:UUID):
        with db() as conn:
            row=incident(conn,id)
            result={'incident':row,'simulated':True}
            for table in ['calls','assertions','actions','verified_receipts','events']:
                order='sequence' if table=='events' else ('verified_at' if table=='verified_receipts' else 'created_at')
                result[table]=conn.execute(f'SELECT * FROM coordinator.{table} WHERE incident_id=%s ORDER BY {order}',(id,)).fetchall()
            for call in result['calls']:
                call.pop('tool_token_hash',None)
            result['documents']=conn.execute('''SELECT id,filename,content_type,kind,content_hash,status,created_at
                FROM coordinator.documents WHERE incident_id=%s ORDER BY created_at''',(id,)).fetchall()
            result['next_step']=next_step(row,result['calls'],result['assertions'],result['actions'],result['documents'],result['verified_receipts'])
            discovery=next((e['payload'] for e in reversed(result['events']) if e['type']=='HOSPITAL_REFERENCES_REPORTED'),None)
            if discovery:
                source=next((c for c in result['calls'] if str(c['id'])==discovery['call_id']),None)
                result['reference_discovery']={**discovery,'source_mode':source['mode'] if source else 'UNKNOWN'}
            if row['reference']=='UNCONFIRMED_FINAL_REFERENCE' and row['consent_active']:
                result['next_step']={'kind':'HOSPITAL_REFERENCE_DISCOVERY','reason':'Ask the hospital for separate request references before claims lookup.',
                    'purpose':'HOSPITAL_REFERENCE_DISCOVERY','evidence_ids':[],'automatic_dispatch':False,'simulated':True}

            if conn.execute('SELECT 1 FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone():
                workflow=complex_view(id)
                result['complex_workflow']=workflow
                result['next_step']={'kind':workflow['next_step'],'reason':'Follow the document-query tasks and exact packet approval in Discharge workflow.',
                    'purpose':None,'evidence_ids':[],'automatic_dispatch':False,'simulated':True}
            return result

    @app.post('/v1/incidents/{id}/calls/{cid}/text-evidence',dependencies=[Depends(operator)])
    def hosted_text_evidence(id:UUID,cid:UUID,body:HostedTextEvidence):
        with db() as conn:
            row=incident(conn,id,True)
            call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s FOR UPDATE',(cid,id)).fetchone()
            if not call:
                raise HTTPException(404,'Unknown incident conversation')
            if not row['is_test'] or call['mode'] not in {'BOLNA_MOCK','BOLNA_TEXT_SIMULATOR'}:
                raise HTTPException(403,'Text evidence is restricted to isolated mock-call fixtures; real call transcripts cannot be replaced')
            turns=[t.model_dump() for t in body.turns]
            if call['mode']=='BOLNA_TEXT_SIMULATOR':
                if call['transcript']!=turns:
                    raise HTTPException(409,'Imported hosted-text evidence is immutable')
                return {'call_id':str(cid),'mode':'BOLNA_TEXT_SIMULATOR','real_phone_call':False}
            conn.execute("UPDATE coordinator.calls SET mode='BOLNA_TEXT_SIMULATOR',state='COMPLETED',transcript=%s,tool_expires_at=now() WHERE id=%s",(Jsonb(turns),cid))
            workflow=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s FOR UPDATE',(id,)).fetchone()
            if workflow:
                w=workflow['data']
                if w['query_call_id']==str(cid):
                    w['source_mode']='BOLNA_TEXT_SIMULATOR'
                for report in w.get('reports',[]):
                    if report['call_id']==str(cid):report['source_mode']='BOLNA_TEXT_SIMULATOR'
                conn.execute('UPDATE coordinator.complex_workflows SET data=%s WHERE incident_id=%s',(Jsonb(w),id))
            event(conn,id,'HOSTED_TEXT_TRANSCRIPT_IMPORTED',{'call_id':str(cid),'source':body.source,
                'transcript_hash':digest(turns),'attestation':body.attestation,'real_phone_call':False})
            return {'call_id':str(cid),'mode':'BOLNA_TEXT_SIMULATOR','real_phone_call':False}

    @app.post('/v1/incidents/{id}/calls/{cid}/text-failure',dependencies=[Depends(operator)])
    def hosted_text_failure(id:UUID,cid:UUID,body:HostedTextFailure):
        with db() as conn:
            row=incident(conn,id,True)
            call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s FOR UPDATE',(cid,id)).fetchone()
            if not call:
                raise HTTPException(404,'Unknown incident conversation')
            if not row['is_test'] or call['mode']!='BOLNA_MOCK':
                raise HTTPException(403,'Connection failure reporting is restricted to isolated mock fixtures')
            payload={'call_id':str(cid),**body.model_dump(),'conversation_started':False,'real_phone_call':False}
            prior=conn.execute("SELECT payload FROM coordinator.events WHERE incident_id=%s AND type='HOSTED_TEXT_CONNECTION_FAILED' AND payload->>'call_id'=%s ORDER BY created_at DESC LIMIT 1",(id,str(cid))).fetchone()
            if prior:
                if prior['payload']!=payload:
                    raise HTTPException(409,'Connection failure evidence is immutable')
                return {'call_id':str(cid),'state':'FAILED','conversation_started':False,'real_phone_call':False}
            used=conn.execute("SELECT 1 FROM coordinator.events WHERE incident_id=%s AND type='VOICE_TOOL_USED' AND payload->>'call_id'=%s AND payload->>'tool'!='claim911_context' LIMIT 1",(id,str(cid))).fetchone()
            if call['transcript'] or call['state'] in {'COMPLETED','CANCELLED'} or used:
                raise HTTPException(409,'An existing conversation or report cannot be relabeled as a connection failure')
            conn.execute("UPDATE coordinator.calls SET state='FAILED',tool_expires_at=now() WHERE id=%s",(cid,))
            event(conn,id,'HOSTED_TEXT_CONNECTION_FAILED',payload)
            return {'call_id':str(cid),'state':'FAILED','conversation_started':False,'real_phone_call':False}

    @app.post('/v1/incidents/{id}/calls/{cid}/reconcile',dependencies=[Depends(operator)])
    def reconcile_call(id:UUID,cid:UUID,body:ReconcileCall):
        # Read-only provider lookup: this endpoint never dispatches or redials.
        with db() as conn:
            incident(conn,id,True)
            call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s FOR UPDATE',(cid,id)).fetchone()
            if not call:
                raise HTTPException(404,'Unknown incident call')
            execution_id=str(body.execution_id)
            if call['execution_id']==execution_id:
                return {'call_id':str(cid),'execution_id':execution_id,'reconciled':True}
            if call['state']!='DISPATCH_UNKNOWN' or call['execution_id']:
                raise HTTPException(409,'Only an uncertain dispatch without an execution can be reconciled')
            if call['mode']!='BOLNA' and not config.get('test_mode'):
                raise HTTPException(409,'Test calls cannot be reconciled with the live provider')
            try:
                payload=Bolna(config.get('bolna_api_key')).execution(execution_id)
            except Exception:
                raise HTTPException(502,'Provider execution lookup failed; call remains on hold')
            if (payload.get('id') or payload.get('execution_id'))!=execution_id:
                raise HTTPException(422,'Provider execution identity does not match')
            context=payload.get('context_details')
            user_data=context.get('recipient_data') if isinstance(context,dict) else None
            if not isinstance(user_data,dict):
                user_data=payload.get('user_data')
            token=user_data.get('call_token') if isinstance(user_data,dict) else None
            if not isinstance(token,str) or not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(),call['tool_token_hash'] or ''):
                raise HTTPException(422,'Provider execution does not prove binding to this call; keep it on hold')
            if conn.execute('SELECT id FROM coordinator.calls WHERE execution_id=%s',(execution_id,)).fetchone():
                raise HTTPException(409,'Provider execution is already linked to another call')
            conn.execute("UPDATE coordinator.calls SET execution_id=%s,state='QUEUED',poll_failures=0,last_polled_at=NULL WHERE id=%s",(execution_id,cid))
            conn.execute("UPDATE coordinator.jobs SET state='DONE',lease_until=NULL,last_error=NULL WHERE payload->>'call_id'=%s",(str(cid),))
            payload['id']=execution_id
            conn.execute('INSERT INTO coordinator.webhook_inbox(dedupe_key,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING',('reconcile-'+digest(payload),Jsonb(payload)))
            event(conn,id,'CALL_EXECUTION_RECONCILED',{'call_id':str(cid),'execution_id':execution_id,'redialed':False})
        return {'call_id':str(cid),'execution_id':execution_id,'reconciled':True}

    @app.get('/v1/incidents/{id}/calls/{cid}/recording',dependencies=[Depends(operator)])
    def recording(id:UUID,cid:UUID):
        with db() as conn:
            row=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s',(cid,id)).fetchone()
        if not row:
            raise HTTPException(404,'Unknown incident call')
        if not row['recording_consent']:
            raise HTTPException(403,'Recording consent was not granted')
        if row['mode'] not in {'BOLNA','BOLNA_WEBRTC'} or row['state']!='COMPLETED' or not row['execution_id'] or not row['recording_url']:
            raise HTTPException(409,'No completed provider recording is available')
        try:
            audio,mime=Bolna(config['bolna_api_key']).recording(row['execution_id'])
        except Exception:
            raise HTTPException(502,'Provider recording could not be retrieved securely')
        return Response(audio,media_type=mime,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @app.post('/v1/incidents/{id}/participants',dependencies=[Depends(operator)],status_code=201)
    def participant(id:UUID,body:Participant):
        with db() as conn:
            incident(conn,id)
            pid=uuid4()
            conn.execute('''INSERT INTO coordinator.participants(id,incident_id,role,phone,verified,demo_consent,recording_consent)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',(pid,id,body.role,body.phone,body.verified,body.demo_consent,body.recording_consent))
            event(conn,id,'TEST_PARTICIPANT_REGISTERED',{'participant_id':str(pid),'role':body.role,'verified':body.verified})
        return {'participant_id':str(pid),'role':body.role}

    @app.get('/v1/incidents/{id}/participants',dependencies=[Depends(operator)])
    def participants(id:UUID):
        with db() as conn:
            incident(conn,id)
            rows=conn.execute('SELECT id,role,phone,verified,recording_consent FROM coordinator.participants WHERE incident_id=%s ORDER BY created_at',(id,)).fetchall()
        return [{**{k:v for k,v in p.items() if k!='phone'},'phone_suffix':p['phone'][-4:]} for p in rows]

    @app.post('/v1/incidents/{id}/call-jobs',dependencies=[Depends(operator)],status_code=201)
    def queue_call(id:UUID,body:QueueCall,idempotency_key:str=Header(min_length=8,max_length=128)):
        if config.get('outbound_paused'):
            raise HTTPException(409,config.get('call_pause_reason','Calls are on hold.'))
        with db() as conn:
            row=incident(conn,id,True)
            require_consent(row)
            from coordinator.workflow_calls import WORKFLOW_ROLES,prepare_context,packet_hash,approval_allows_call
            workflow_row=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone()
            workflow=workflow_row['data'] if workflow_row else None
            workflow_context=None
            if body.purpose=='HOSPITAL_REFERENCE_DISCOVERY' and row['reference']!='UNCONFIRMED_FINAL_REFERENCE':
                raise HTTPException(409,'Final reference is already known; do not restart discovery')
            if workflow or body.purpose in WORKFLOW_ROLES:
                if body.purpose not in WORKFLOW_ROLES:
                    raise HTTPException(409,'Use a purpose-specific complex discharge call')
                try:
                    workflow_context=prepare_context(row,workflow,body.purpose)
                    workflow_context['workflow']['reported_hospital_references']=hospital_report(conn,id)
                except ValueError as exc:
                    raise HTTPException(409,str(exc))
            if body.purpose=='PACKET_SUBMISSION' and not approval_allows_call(workflow,'BOLNA_MOCK' if config.get('test_mode') else 'BOLNA'):
                raise HTTPException(409,'Synthetic caregiver approval cannot authorize a real phone call')
            fingerprint=digest({'incident':str(id),'command':'queue-call',**body.model_dump(mode='json')})
            previous=conn.execute('SELECT * FROM coordinator.command_results WHERE key=%s',(idempotency_key,)).fetchone()
            if previous:
                if previous['body_hash']!=fingerprint:
                    raise HTTPException(409,'Call command key reused for a different payload')
                return previous['response']
            p=conn.execute('SELECT * FROM coordinator.participants WHERE id=%s AND incident_id=%s',(body.participant_id,id)).fetchone()
            roles={'HOSPITAL_INITIAL':'hospital','CLAIMS_LOOKUP':'claims','HOSPITAL_FOLLOWUP':'hospital',
                   'CORRECTION_REQUEST':'hospital','CAREGIVER_UPDATE':'caregiver',**WORKFLOW_ROLES}
            if not p or not p['verified'] or not p['demo_consent'] or p['role']!=roles[body.purpose]:
                raise HTTPException(422,'Verified consenting participant with matching role required')
            if row['state'] in ['PAUSED_REVOKED','HUMAN_REVIEW']:
                raise HTTPException(409,'Incident requires human review')
            if body.purpose=='CORRECTION_REQUEST':
                action=conn.execute("SELECT * FROM coordinator.actions WHERE id=%s AND incident_id=%s AND state='AUTHORIZED'",
                                    (body.action_id,id)).fetchone()
                if not action or action['consent_version']!=row['consent_version']:
                    raise HTTPException(409,'Current exact-action approval required')
            elif body.action_id:
                raise HTTPException(422,'Action binding is only valid for correction calls')
            active=conn.execute("SELECT id FROM coordinator.calls WHERE incident_id=%s AND mode IN ('BOLNA','BOLNA_MOCK') AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER')",(id,)).fetchone()
            if active:
                raise HTTPException(409,'An active or uncertain call must be reconciled first')
            count=conn.execute("SELECT count(*) AS n FROM coordinator.calls WHERE incident_id=%s AND mode IN ('BOLNA','BOLNA_MOCK')",(id,)).fetchone()['n']
            if count >= (config.get('max_complex_outbound_calls',12) if workflow_context else config.get('max_outbound_calls',7)):
                raise HTTPException(409,'Demo outgoing-call limit reached; human review required')
            facts=conn.execute("SELECT source_role,predicate,value,reference,request_type,support_status FROM coordinator.assertions WHERE incident_id=%s AND support_status!='SUPERSEDED' ORDER BY created_at",(id,)).fetchall()
            facts=[f for f in facts if f['reference']==row['reference'] and f['request_type']==row['request_type']]
            call_id,job_id=uuid4(),uuid4();tool_token=secrets.token_urlsafe(32)
            context={'incident_id':str(id),'case_id':str(row['case_id']),'patient_id':row['patient_id'],
                'reference':row['reference'],'request_type':row['request_type'],'purpose':body.purpose,
                'participant_role':p['role'],'allowed_statement_predicates':sorted(ROLE_PREDICATES[p['role']]),'objective':workflow_context['objective'] if workflow_context else call_objective(body.purpose,row['reference']),'known_statements':facts,'simulated':True,
                'insurance_decision':row['decision_state'],'call_id':str(call_id)}
            if workflow_context:
                context.update(workflow_context)
            if body.action_id:
                context['authorized_action']=action['payload']
            conn.execute('''INSERT INTO coordinator.calls(id,incident_id,participant_id,participant_role,purpose,mode,state,
                tool_token_hash,consent_version,tool_expires_at,recording_consent,action_id,workflow_packet_hash) VALUES(%s,%s,%s,%s,%s,%s,'SCHEDULED',%s,%s,now()+interval '15 minutes',%s,%s,%s)''',
                (call_id,id,p['id'],p['role'],body.purpose,'BOLNA_MOCK' if config.get('test_mode') else 'BOLNA',
                 hashlib.sha256(tool_token.encode()).hexdigest(),row['consent_version'],p['recording_consent'],body.action_id,
                 packet_hash(row,workflow) if body.purpose=='PACKET_SUBMISSION' else None))
            payload={'call_id':str(call_id),'action_id':str(body.action_id) if body.action_id else None,
                     'user_data':{'claim911_context':json.dumps(context,default=str),'claim911_objective':context['objective'],'call_token':tool_token}}
            conn.execute("INSERT INTO coordinator.jobs(id,incident_id,kind,payload) VALUES(%s,%s,'OUTBOUND_CALL',%s)",
                         (job_id,id,Jsonb(payload)))
            event(conn,id,'CALL_QUEUED',{'call_id':str(call_id),'job_id':str(job_id),'purpose':body.purpose,'role':p['role']})
            response={'job_id':str(job_id),'call_id':str(call_id),'state':'SCHEDULED'}
            conn.execute('INSERT INTO coordinator.command_results(key,body_hash,response) VALUES(%s,%s,%s)',
                         (idempotency_key,fingerprint,Jsonb(response)))
            return response

    def bound_call(token):
        with db() as conn:
            call=conn.execute('''SELECT c.*,i.consent_active,i.consent_version AS current_consent FROM coordinator.calls c
                JOIN coordinator.incidents i ON i.id=c.incident_id WHERE c.tool_token_hash=%s''',
                (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not call or not call['consent_active'] or call['consent_version']!=call['current_consent'] or (
                call['tool_expires_at']<datetime.now(timezone.utc)) or call['state'] not in ['DISPATCHING','QUEUED','INITIATED','RINGING','IN_PROGRESS']:
                raise HTTPException(403,'Call context is missing, expired, inactive or revoked')
            if call['action_id']:
                action=conn.execute("SELECT state,consent_version FROM coordinator.actions WHERE id=%s",(call['action_id'],)).fetchone()
                if not action or action['state']!='AUTHORIZED' or action['consent_version']!=call['current_consent']:
                    raise HTTPException(403,'The exact correction approval changed; further call tools are disabled')
            if call.get('workflow_packet_hash'):
                from coordinator.workflow_calls import approval_valid,approval_allows_call
                current=incident(conn,call['incident_id'])
                w=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(call['incident_id'],)).fetchone()
                if not w or not approval_valid(current,w['data'],call['workflow_packet_hash']) or not approval_allows_call(w['data'],call['mode']):
                    raise HTTPException(403,'Exact packet approval changed; further submission call tools disabled')
            return call

    @app.post('/v1/tools/references')
    def report_references(body:ReferenceDiscovery,x_call_token:str=Header(default='')):
        call=bound_call(x_call_token)
        if call['purpose']!='HOSPITAL_REFERENCE_DISCOVERY' or call['participant_role']!='hospital':
            raise HTTPException(403,'Reference discovery belongs only to its assigned hospital call')
        refs=[body.initial_reference,body.enhancement_reference,body.final_reference]
        if len(set(refs))!=3 or any(x=='UNCONFIRMED_FINAL_REFERENCE' for x in refs):
            raise HTTPException(422,'Initial, enhancement and final references must be distinct confirmed identifiers')
        with db() as conn:
            row=incident(conn,call['incident_id'],True)
            require_consent(row)
            from coordinator.sandbox_calls import require_current_context
            require_current_context(conn,call)
            if row['state']=='HUMAN_REVIEW':
                raise HTTPException(409,'Incident requires human review')
            from coordinator.reference_evidence import candidates, candidate_report_conflicts
            slips=candidates(conn,row)
            choices=[{'admission_id':s['admission_id'],
                      'initial_reference':s['references']['preauthorization'],
                      'enhancement_reference':s['references']['enhancement'],
                      'final_reference':s['references']['final_request']} for s in slips]
            conflicts=candidate_report_conflicts({k:getattr(body,k) for k in
                ('admission_id','initial_reference','enhancement_reference','final_reference')},choices)
            if conflicts:
                raise HTTPException(422,{'code':'REFERENCE_CONFIRMATION_REQUIRED','fields':conflicts,
                    'instruction':'The report conflicts with the uploaded hospital slip. Clarify these fields with staff or stop for review. Never invent or silently substitute a reference.'})
            payload={'call_id':str(call['id']),'patient_id':row['patient_id'],**body.model_dump(),
                'support_status':'REPORTED_FROM_CALL','receiving_side_verified':False}
            prior=conn.execute("SELECT payload FROM coordinator.events WHERE incident_id=%s AND type='HOSPITAL_REFERENCES_REPORTED' ORDER BY created_at DESC LIMIT 1",(row['id'],)).fetchone()
            if prior:
                if prior['payload']!=payload:
                    raise HTTPException(409,'Reference discovery is already recorded; preserve the original and seek review')
                from coordinator.voice_contracts import report_speech
                return {'recorded':True,'final_reference':body.final_reference,'receiving_side_verified':False,
                    **report_speech('The separate request references are recorded. Claims receipt still needs an independent check.')}
            if row['reference']!='UNCONFIRMED_FINAL_REFERENCE':
                raise HTTPException(409,'Final reference is already established')
            conn.execute('UPDATE coordinator.incidents SET reference=%s,version=version+1 WHERE id=%s',(body.final_reference,row['id']))
            event(conn,row['id'],'VOICE_TOOL_USED',{'call_id':str(call['id']),'tool':'claim911_report_references','purpose':call['purpose']})
            event(conn,row['id'],'HOSPITAL_REFERENCES_REPORTED',payload)
            from coordinator.voice_contracts import report_speech
            return {'recorded':True,'final_reference':body.final_reference,'receiving_side_verified':False,
                **report_speech('The separate request references are recorded. Hospital submission is reported only; claims receipt still needs an independent check.')}

    @app.get('/v1/tools/context')
    def tool_context(x_call_token:str=Header(default='')):
        call=bound_call(x_call_token)
        with db() as conn:
            row=incident(conn,call['incident_id'])
            material=conn.execute("SELECT coalesce(max(sequence),0) AS n FROM coordinator.events WHERE incident_id=%s AND type NOT IN ('VOICE_TOOL_USED','SANDBOX_PROVIDER_EXECUTION_BOUND')",(row['id'],)).fetchone()['n']
            event(conn,row['id'],'VOICE_TOOL_USED',{'call_id':str(call['id']),'tool':'claim911_context','purpose':call['purpose'],'material_sequence':material})
            facts=conn.execute("SELECT id,source_role,predicate,value,reference,request_type,support_status FROM coordinator.assertions WHERE incident_id=%s AND support_status!='SUPERSEDED' ORDER BY created_at",(row['id'],)).fetchall()
            facts=[f for f in facts if f['reference']==row['reference'] and f['request_type']==row['request_type']]
            docs=conn.execute('SELECT id,filename,kind,status FROM coordinator.documents WHERE incident_id=%s',(row['id'],)).fetchall()
            actions=conn.execute("SELECT id,payload,state FROM coordinator.actions WHERE incident_id=%s AND state IN ('AUTHORIZED','VERIFIED') AND consent_version=%s",(row['id'],row['consent_version'])).fetchall()
        from coordinator.workflow_calls import WORKFLOW_ROLES,prepare_context
        workflow_context=None
        if call['purpose'] in WORKFLOW_ROLES:
            with db() as conn:
                w=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(row['id'],)).fetchone()
            if call['purpose']=='QUERY_DISCOVERY' and w and str(call['id']) in {w['data'].get('query_call_id'),w['data'].get('query_confirmation_call_id')}:
                from coordinator.voice_contracts import report_speech
                closing=report_speech('The outstanding query and required documents are recorded. Document collection is the next step.')
                workflow_context={'objective':'The query was recorded. Say exactly: '+closing['spoken_outcome']+' Do not recap references, timestamps or documents, and do not ask another question.',
                                  'workflow':{'query_reference':w['data']['query']['references']['query'],'state':'QUERY_RECORDED'},'allowed_statement_predicates':['ACCESS_REFUSED']}
            else:
                try: workflow_context=prepare_context(row,w['data'] if w else None,call['purpose'])
                except ValueError as exc: raise HTTPException(409,str(exc))
                if call['purpose']=='QUERY_DISCOVERY':
                    with db() as conn:
                        reports=conn.execute("SELECT payload FROM coordinator.events WHERE incident_id=%s AND type='QUERY_DISCOVERY_UPDATE' ORDER BY sequence",(row['id'],)).fetchall()
                    workflow_context['workflow']['reported_updates']=[r['payload'] for r in reports]
        result={'call_id':str(call['id']),'incident_id':str(row['id']),'patient_id':row['patient_id'],
            'participant_role':call['participant_role'],
            'purpose':call['purpose'],'allowed_statement_predicates':sorted(ROLE_PREDICATES[call['participant_role']]),'objective':workflow_context['objective'] if workflow_context else call_objective(call['purpose'],row['reference']),'reference':row['reference'],'request_type':row['request_type'],
            'state':row['state'],'decision_state':row['decision_state'],'investigation_consent_active':row['consent_active'],'statements':facts,'documents':docs,'authorized_actions':actions,'simulated':True,
            'instructions':'Confirm permission to speak. Ask for missing submission reference, time, destination and recipient lookup scope. Report only supported facts. Uploaded evidence is not automatically verified.'}
        if call['purpose']=='HOSPITAL_REFERENCE_DISCOVERY' and call['mode']=='SANDBOX_AUDIO':
            from coordinator.reference_evidence import candidates
            with db() as conn:result['uploaded_reference_candidates']=candidates(conn,row)
        if call['purpose']=='QUERY_DISCOVERY' and call['mode']=='SANDBOX_AUDIO':
            from coordinator.reference_evidence import query_candidates
            with db() as conn:result['uploaded_query_candidates']=query_candidates(conn,row)
            with db() as conn:
                prior=conn.execute("SELECT id,transcript FROM coordinator.calls WHERE incident_id=%s AND id!=%s AND purpose='QUERY_DISCOVERY' AND mode='SANDBOX_AUDIO' AND state='COMPLETED' AND consent_version=%s ORDER BY created_at DESC LIMIT 1",(row['id'],call['id'],row['consent_version'])).fetchone()
            if prior:
                result['previous_reported_conversation']={'call_id':str(prior['id']),'support_status':'REPORTED_FROM_PRIOR_CALL',
                    'turns':[{'speaker':t['speaker'],'text':t['text'][:300]} for t in prior['transcript'][-8:]],
                    'instruction':'Continue unresolved questions from this case conversation. These statements are reported, not institution-verified outcomes.'}

        if call['mode']=='SANDBOX_AUDIO' and call['purpose'] in {'BILLING_DOCUMENT','RECORDS_DOCUMENT','IMPLANT_DOCUMENT'}:
            from coordinator.reference_evidence import document_candidates
            kind,owner={'BILLING_DOCUMENT':('itemized_bill','billing'),'RECORDS_DOCUMENT':('signed_discharge_summary','medical_records'),'IMPLANT_DOCUMENT':('implant_invoice','implant_store')}[call['purpose']]
            with db() as conn:result['uploaded_document_candidates']=document_candidates(conn,row,kind,owner,workflow_context['workflow']['admission_id'])
        if call['mode']=='SANDBOX_AUDIO' and call['purpose']=='PACKET_SUBMISSION':
            from coordinator.reference_evidence import dispatch_candidates
            with db() as conn:result['uploaded_dispatch_candidates']=dispatch_candidates(conn,row)
        if workflow_context:
            with db() as conn:
                workflow_context['workflow']['reported_hospital_references']=hospital_report(conn,row['id'])
                callback=conn.execute("SELECT purpose,attempts FROM coordinator.workflow_callbacks WHERE incident_id=%s AND purpose=%s AND state='RUNNING' AND consent_version=%s ORDER BY updated_at DESC LIMIT 1",(row['id'],call['purpose'],row['consent_version'])).fetchone()
            if callback:
                workflow_context['workflow']['active_followup']={'purpose':callback['purpose'],'attempt':callback['attempts']}
                if callback['purpose']=='RECORDS_DOCUMENT':
                    workflow_context['objective']=('SCHEDULED MEDICAL-RECORDS FOLLOW-UP: The earlier call established a missing treating-team signature. Ask staff to follow up with the treating team and upload its signed discharge summary if it can now be released. Do not merely repeat whether it is ready and close. Obtain the actual result; if released, confirm its identifier and revision and check it through the document report tool. If staff cannot obtain it, record their actual blocker without assuming release. You cannot sign a clinical document. Then follow these document verification rules: '+workflow_context['objective'])
            result.update(workflow_context)
            result['instructions']='Follow only this call objective. Use workflow reports for confirmed statements. Uploaded and spoken evidence is not automatically verified.'
        from coordinator.voice_guidance import context_guidance
        result['instructions']+='\n'+context_guidance(result)
        return result

    @app.post('/v1/tools/statements',status_code=201)
    def tool_statement(body:ToolStatement,x_call_token:str=Header(default='')):
        call=bound_call(x_call_token)
        from coordinator.workflow_calls import WORKFLOW_ROLES
        if call['purpose'] in WORKFLOW_ROLES and body.predicate!='ACCESS_REFUSED':
            raise HTTPException(403,'Use the scoped workflow reporting tool for this conversation')
        if body.predicate not in ROLE_PREDICATES[call['participant_role']]:
            raise HTTPException(403,'Statement predicate is outside this participant role')
        if body.predicate=='DESTINATION' and not body.document_id:
            # Link only an uploaded dispatch whose contents match this case and reported destination.
            with db() as conn:
                row=incident(conn,call['incident_id'])
                docs=conn.execute("SELECT id,data FROM coordinator.documents WHERE incident_id=%s AND kind='dispatch' ORDER BY created_at DESC",(row['id'],)).fetchall()
                for doc in docs:
                    try:
                        value=json.loads(bytes(doc['data']))
                        if value.get('case_id')==str(row['case_id']) and value.get('reference')==body.reference and value.get('destination')==body.value.get('destination'):
                            body.document_id=doc['id'];break
                    except (ValueError,TypeError):
                        continue
        return statement(call['incident_id'],Statement(**body.model_dump(),call_id=call['id'],source_role=call['participant_role']))

    @app.post('/v1/tools/propose',status_code=201)
    def tool_propose(x_call_token:str=Header(default='')):
        call=bound_call(x_call_token)
        if call['mode']=='SANDBOX_AUDIO':
            raise HTTPException(403,'This sandbox workflow has no routing-correction tool scope')
        if call['participant_role']!='hospital':
            raise HTTPException(403,'Routing correction proposal belongs to hospital follow-up')
        with db() as conn:
            ids=conn.execute("SELECT id FROM coordinator.assertions WHERE incident_id=%s AND support_status!='SUPERSEDED'",(call['incident_id'],)).fetchall()
        # The institutional route comes from the configured directory, not from the model.
        with httpx.Client(timeout=5) as client:
            r=client.get(config['simulator_url']+'/claims/routing',headers={'Authorization':'Bearer '+config['simulator_agent_token']})
        if r.status_code!=200 or not r.json().get('routes'):
            raise HTTPException(503,'Verified recipient route unavailable')
        route=r.json()['routes'][0]
        return propose(call['incident_id'],Correction(destination=route['destination'],route_id=route['id'],evidence_ids=[x['id'] for x in ids]))

    @app.post('/v1/webhooks/bolna',status_code=202)
    async def webhook(request:Request,x_webhook_token:str=Header(default='')):
        if not secrets.compare_digest(x_webhook_token,config['webhook_token']):
            raise HTTPException(403,'Webhook authentication required')
        raw=await request.body()
        if len(raw)>1024*1024:
            raise HTTPException(413,'Webhook payload exceeds limit')
        try:
            payload=json.loads(raw)
            execution_id=str(UUID(payload.get('id') or payload['execution_id']))
        except (ValueError,KeyError,TypeError):
            raise HTTPException(422,'Execution identity required')
        with db() as conn:
            call=conn.execute('SELECT id FROM coordinator.calls WHERE execution_id=%s',(execution_id,)).fetchone()
            if not call:
                # A webhook may precede persistence of the dispatch response. Preserve it for reconciliation.
                pass
            key=digest({'execution_id':execution_id,'payload':payload})
            conn.execute('INSERT INTO coordinator.webhook_inbox(dedupe_key,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING',
                         (key,Jsonb(payload)))
        return {'accepted':True}

    @app.post('/v1/incidents/{id}/consent',dependencies=[Depends(operator)])
    def consent(id:UUID,body:Consent):
        with db() as conn:
            row=incident(conn,id,True)
            state='INVESTIGATING' if body.accepted else 'PAUSED_REVOKED'
            if row['state']=='BLOCKER_RESOLVED':
                state=row['state']
            conn.execute('''UPDATE coordinator.incidents SET consent_active=%s,consent_version=consent_version+1,
                state=%s,version=version+1 WHERE id=%s''',(body.accepted,state,id))
            if not body.accepted:
                conn.execute("UPDATE coordinator.workflow_callbacks SET state='CANCELLED',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE incident_id=%s AND state IN ('WAITING','RUNNING')",(id,))
                conn.execute("UPDATE coordinator.actions SET state='REVOKED' WHERE incident_id=%s AND state IN ('PROPOSED','AUTHORIZED')",(id,))
                cancelled=conn.execute("UPDATE coordinator.jobs SET state='CANCELLED' WHERE incident_id=%s AND state='QUEUED' RETURNING payload",(id,)).fetchall()
                for job in cancelled:
                    conn.execute("UPDATE coordinator.calls SET state='CANCELLED' WHERE id=%s AND state='SCHEDULED' AND execution_id IS NULL",(job['payload']['call_id'],))
                active=conn.execute("SELECT id,execution_id FROM coordinator.calls WHERE incident_id=%s AND execution_id IS NOT NULL AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER')",(id,)).fetchall()
                for call in active:
                    existing=conn.execute("SELECT id FROM coordinator.jobs WHERE kind='STOP_CALL' AND payload->>'call_id'=%s",(str(call['id']),)).fetchone()
                    if not existing:
                        conn.execute("INSERT INTO coordinator.jobs(id,incident_id,kind,payload) VALUES(%s,%s,'STOP_CALL',%s)",
                            (uuid4(),id,Jsonb({'call_id':str(call['id']),'execution_id':call['execution_id']})))
                        event(conn,id,'CALL_STOP_REQUESTED',{'call_id':str(call['id']),'confirmed_stopped':False})
            event(conn,id,'CONSENT_GRANTED' if body.accepted else 'CONSENT_REVOKED',
                  {'confirmation':body.confirmation,'scope':'Synthetic case investigation and hospital correction request',
                   'version':row['consent_version']+1})
            return {'state':state,'consent_version':row['consent_version']+1}

    @app.post('/v1/incidents/{id}/calls',dependencies=[Depends(operator)],status_code=201)
    def record_call(id:UUID,body:CallRecord):
        with db() as conn:
            row=incident(conn,id,True)
            require_consent(row)
            call_id=uuid4()
            conn.execute('''INSERT INTO coordinator.calls(id,incident_id,participant_role,purpose,mode,transcript,recording_consent)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',(call_id,id,body.participant_role,body.purpose,body.mode,
                Jsonb([x.model_dump() for x in body.transcript]),body.recording_consent))
            event(conn,id,'MANUAL_CONVERSATION_RECORDED',{'call_id':str(call_id),'role':body.participant_role,
                  'mode':body.mode,'real_call':False})
            return {'call_id':str(call_id),'mode':body.mode}

    @app.post('/v1/incidents/{id}/statements',dependencies=[Depends(operator)],status_code=201)
    def statement(id:UUID,body:Statement):
        with db() as conn:
            row=incident(conn,id,True)
            require_consent(row)
            if row['state']=='BLOCKER_RESOLVED':
                raise HTTPException(409,'Resolved incident must be explicitly reopened before new investigation')
            for table,foreign in [('calls',body.call_id),('documents',body.document_id),('assertions',body.supersedes_id)]:
                if foreign and not conn.execute(f'SELECT id FROM coordinator.{table} WHERE id=%s AND incident_id=%s',(foreign,id)).fetchone():
                    raise HTTPException(422,'Evidence must belong to this incident')
            if not body.call_id and not body.document_id:
                raise HTTPException(422,'A source conversation or document is required')
            if body.call_id:
                call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s',(body.call_id,)).fetchone()
                if call['participant_role']!=body.source_role:
                    raise HTTPException(422,'Statement source differs from conversation participant')
                from coordinator.sandbox_calls import require_current_context
                require_current_context(conn,call)
            # Provider tool retries must not duplicate evidence or invalidate approval twice.
            repeated=conn.execute('''SELECT id,support_status FROM coordinator.assertions WHERE incident_id=%s
                AND call_id IS NOT DISTINCT FROM %s AND document_id IS NOT DISTINCT FROM %s
                AND source_role=%s AND predicate=%s AND value=%s AND reference=%s AND request_type=%s
                AND supersedes_id IS NOT DISTINCT FROM %s ORDER BY created_at LIMIT 1''',
                (id,body.call_id,body.document_id,body.source_role,body.predicate,Jsonb(body.value),
                 body.reference,body.request_type,body.supersedes_id)).fetchone()
            if repeated:
                return {'assertion_id':str(repeated['id']),'state':row['state'],'support_status':repeated['support_status']}
            aid=uuid4()
            if body.supersedes_id:
                conn.execute("UPDATE coordinator.assertions SET support_status='SUPERSEDED' WHERE id=%s",(body.supersedes_id,))
                conn.execute("UPDATE coordinator.actions SET state='STALE' WHERE incident_id=%s AND state IN ('PROPOSED','AUTHORIZED')",(id,))
                if row['state'] in {'AWAITING_ACTION_AUTHORIZATION','COORDINATING_CORRECTION'}:
                    row={**row,'state':'INVESTIGATING'}
            conn.execute('''INSERT INTO coordinator.assertions(id,incident_id,call_id,document_id,source_role,predicate,
                value,reference,request_type,supersedes_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (aid,id,body.call_id,body.document_id,body.source_role,body.predicate,Jsonb(body.value),
                 body.reference,body.request_type,body.supersedes_id))
            if body.predicate=='REFERENCE_CORRECTION' and body.request_type==row['request_type']:
                corrected=body.value.get('corrected_reference')
                if not isinstance(corrected,str) or not corrected.strip():
                    raise HTTPException(422,'Corrected reference required')
                corrected=corrected.strip()
                if corrected!=row['reference']:
                    conn.execute("UPDATE coordinator.actions SET state='STALE' WHERE incident_id=%s AND state IN ('PROPOSED','AUTHORIZED')",(id,))
                conn.execute('UPDATE coordinator.incidents SET reference=%s,version=version+1 WHERE id=%s',(corrected,id))
                row={**row,'reference':corrected,'state':'INVESTIGATING'}
            same=conn.execute('''SELECT predicate,value FROM coordinator.assertions WHERE incident_id=%s
                AND reference=%s AND request_type=%s AND support_status!='SUPERSEDED' ''',
                (id,row['reference'],row['request_type'])).fetchall()
            kinds={x['predicate'] for x in same if supports_predicate(x)}
            state=row['state']
            if state=='INVESTIGATING' and {'SUBMITTED','NOT_RECEIVED'}<=kinds and body.request_type==row['request_type']:
                state='DISCREPANCY_OPEN'
            if body.predicate in {'ACCESS_REFUSED','SUBMISSION_UNKNOWN'}:
                state='HUMAN_REVIEW'
                conn.execute("UPDATE coordinator.actions SET state='STALE' WHERE incident_id=%s AND state IN ('PROPOSED','AUTHORIZED')",(id,))
            conn.execute('UPDATE coordinator.incidents SET state=%s,version=version+1 WHERE id=%s',(state,id))
            event(conn,id,'STATEMENT_RECORDED',{'assertion_id':str(aid),'predicate':body.predicate,'state':state,
                  'support_status':'REPORTED','supersedes_id':str(body.supersedes_id) if body.supersedes_id else None})
            return {'assertion_id':str(aid),'state':state,'support_status':'REPORTED'}

    @app.post('/v1/incidents/{id}/documents',dependencies=[Depends(operator)],status_code=201)
    async def upload(id:UUID,file:UploadFile=File(),kind:Literal['dispatch','receipt','policy','bill','other']=Form('other')):
        data=await file.read(10*1024*1024+1)
        if not data or len(data)>10*1024*1024:
            raise HTTPException(413,'Document must be between 1 byte and 10 MiB')
        name=Path((file.filename or 'document').replace('\\','/')).name[:160]
        if data.startswith(b'%PDF-'):
            mime='application/pdf'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime='image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime='image/jpeg'
        else:
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                raise HTTPException(415,'Use PDF, PNG, JPEG, JSON or UTF-8 text')
            mime='application/json' if name.lower().endswith('.json') else 'text/plain'
        doc_id=uuid4()
        with db() as conn:
            incident(conn,id)
            conn.execute('''INSERT INTO coordinator.documents(id,incident_id,filename,content_type,kind,content_hash,data)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',(doc_id,id,name,mime,kind,hashlib.sha256(data).hexdigest(),data))
            event(conn,id,'DOCUMENT_UPLOADED',{'document_id':str(doc_id),'filename':name,'status':'UPLOADED_UNVERIFIED'})
        return {'document_id':str(doc_id),'status':'UPLOADED_UNVERIFIED','content_type':mime}

    @app.get('/v1/incidents/{id}/documents/{doc_id}',dependencies=[Depends(operator)])
    def document(id:UUID,doc_id:UUID):
        with db() as conn:
            doc=conn.execute('SELECT * FROM coordinator.documents WHERE id=%s AND incident_id=%s',(doc_id,id)).fetchone()
        if not doc:
            raise HTTPException(404,'Unknown incident document')
        return Response(bytes(doc['data']),media_type=doc['content_type'],headers={
            'Content-Disposition':'attachment; filename="'+doc['filename'].replace('"','').replace('\r','').replace('\n','')+'"',
            'X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox; default-src 'none'"})

    @app.post('/v1/incidents/{id}/actions',dependencies=[Depends(operator)],status_code=201)
    def propose(id:UUID,body:Correction):
        with db() as conn:
            row=incident(conn,id,True)
            require_consent(row)
            if conn.execute('SELECT 1 FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone():
                raise HTTPException(409,'Use document-query packet approval for this incident')
            if row['state'] not in ['DISCREPANCY_OPEN','AWAITING_ACTION_AUTHORIZATION']:
                raise HTTPException(409,'An open discrepancy is required before proposing correction')
            current_facts=conn.execute('''SELECT predicate,value FROM coordinator.assertions WHERE incident_id=%s
                AND reference=%s AND request_type=%s AND support_status!='SUPERSEDED' ''',
                (id,row['reference'],row['request_type'])).fetchall()
            if any(not supports_predicate(f) for f in current_facts):
                raise HTTPException(409,'Clarify ambiguous or contradictory statement values before correction')
            conflict=conn.execute('''SELECT id FROM coordinator.assertions WHERE incident_id=%s
                AND reference=%s AND request_type=%s AND source_role='claims' AND predicate='RECEIVED'
                AND support_status!='SUPERSEDED' LIMIT 1''',(id,row['reference'],row['request_type'])).fetchone()
            if conflict:
                raise HTTPException(409,'Claims reports receipt; reconcile conflicting evidence before routing correction')
            facts=conn.execute('''SELECT * FROM coordinator.assertions WHERE incident_id=%s AND id=ANY(%s)
                AND support_status!='SUPERSEDED' ''',(id,body.evidence_ids)).fetchall()
            matched=[f for f in facts if f['reference']==row['reference'] and f['request_type']==row['request_type']]
            if any(not supports_predicate(f) for f in matched):
                raise HTTPException(422,'Statement values must support their labels before correction')
            if not {'SUBMITTED','NOT_RECEIVED','DESTINATION'}<={f['predicate'] for f in matched}:
                raise HTTPException(422,'Comparable submission, recipient lookup and destination assertions are required')
            if not any(f['predicate']=='SUBMITTED' and f['source_role']=='hospital' for f in matched) or not any(
                f['predicate']=='NOT_RECEIVED' and f['source_role']=='claims' for f in matched):
                raise HTTPException(422,'Submission must be hospital-attributed and lookup claims-attributed')
            dest=next(f for f in matched if f['predicate']=='DESTINATION')
            if not dest['document_id'] or dest['source_role']!='hospital':
                raise HTTPException(422,'Destination assertion needs dispatch evidence')
            doc=conn.execute("SELECT data FROM coordinator.documents WHERE id=%s AND incident_id=%s AND kind='dispatch'",
                             (dest['document_id'],id)).fetchone()
            try:
                evidence=json.loads(bytes(doc['data']))
                if (evidence['destination']!=dest['value'].get('destination') or
                    evidence['case_id']!=str(row['case_id']) or evidence['reference']!=row['reference'] or
                    evidence['request_type']!=row['request_type']):
                    raise ValueError('Dispatch evidence differs from statement')
            except (ValueError,KeyError,TypeError):
                raise HTTPException(422,'Matching synthetic dispatch JSON is required for routing diagnosis')
            with httpx.Client(timeout=5) as client:
                response=client.get(config['simulator_url']+'/claims/routing',headers={
                    'Authorization':'Bearer '+config['simulator_agent_token']})
            if response.status_code!=200:
                raise HTTPException(503,'Designated route could not be verified')
            routes=response.json()['routes']
            if not any(r['id']==body.route_id and r['destination']==body.destination for r in routes):
                raise HTTPException(422,'Destination is not the designated route')
            if dest['value'].get('destination')==body.destination:
                raise HTTPException(409,'Existing evidence does not establish a destination mismatch')
            payload={'case_id':str(row['case_id']),'reference':row['reference'],'request_type':row['request_type'],
                     'destination':body.destination,'route_id':body.route_id,'recipient_role':'hospital'}
            aid=uuid4()
            conn.execute('''INSERT INTO coordinator.actions(id,incident_id,kind,payload,payload_hash,evidence_ids,consent_version)
                VALUES(%s,%s,'REQUEST_HOSPITAL_CORRECTION',%s,%s,%s,%s)''',
                (aid,id,Jsonb(payload),digest(payload),Jsonb([str(x) for x in body.evidence_ids]),row['consent_version']))
            conn.execute("UPDATE coordinator.incidents SET state='AWAITING_ACTION_AUTHORIZATION',version=version+1 WHERE id=%s",(id,))
            event(conn,id,'CORRECTION_PROPOSED',{'action_id':str(aid),'payload':payload})
            return {'action_id':str(aid),'payload':payload,'state':'PROPOSED'}

    @app.post('/v1/incidents/{id}/actions/{aid}/authorize',dependencies=[Depends(operator)])
    def authorize(id:UUID,aid:UUID,body:Consent):
        if not body.accepted:
            raise HTTPException(422,'Explicit approval is required')
        with db() as conn:
            row=incident(conn,id,True)
            require_consent(row)
            action=conn.execute('SELECT * FROM coordinator.actions WHERE id=%s AND incident_id=%s FOR UPDATE',(aid,id)).fetchone()
            if not action or action['state']!='PROPOSED' or action['consent_version']!=row['consent_version']:
                raise HTTPException(409,'Action is absent, stale, or no longer authorized by current scope')
            conn.execute("UPDATE coordinator.actions SET state='AUTHORIZED' WHERE id=%s",(aid,))
            conn.execute("UPDATE coordinator.incidents SET state='COORDINATING_CORRECTION',version=version+1 WHERE id=%s",(id,))
            event(conn,id,'CORRECTION_AUTHORIZED',{'action_id':str(aid),'payload_hash':action['payload_hash'],
                  'confirmation':body.confirmation})
            return {'state':'AUTHORIZED','hospital_must_submit':True}

    @app.post('/v1/incidents/{id}/verify',dependencies=[Depends(operator)])
    def verify(id:UUID,body:Verify):
        with db() as conn:
            row=incident(conn,id,True)
            require_consent(row)
            action=conn.execute('SELECT * FROM coordinator.actions WHERE id=%s AND incident_id=%s',(body.action_id,id)).fetchone()
            if not action or action['state'] not in ['AUTHORIZED','VERIFIED'] or action['consent_version']!=row['consent_version']:
                raise HTTPException(409,'Current action authorization required')
            doc=conn.execute("SELECT * FROM coordinator.documents WHERE id=%s AND incident_id=%s AND kind='dispatch'",
                             (body.dispatch_document_id,id)).fetchone()
            if not doc:
                raise HTTPException(422,'Corrected dispatch document required')
            try:
                dispatch=json.loads(bytes(doc['data']))
                expected={k:dispatch[k] for k in ['submission_id','revision','packet_hash','dispatched_at']}
                expected|={'case_id':str(row['case_id']),'patient_id':row['patient_id'],'reference':row['reference'],
                           'request_type':row['request_type'],'route_id':action['payload']['route_id'],
                           'destination':action['payload']['destination']}
                result=verify_receipt(config['receipt_public_key'],body.receipt,expected)
            except (VerificationError,KeyError,ValueError,TypeError) as exc:
                raise HTTPException(422,str(exc))
            prior=conn.execute('SELECT incident_id FROM coordinator.verified_receipts WHERE id=%s',(result['receipt_id'],)).fetchone()
            if prior and prior['incident_id']!=id:
                raise HTTPException(409,'Receipt already belongs to another incident')
            if not prior:
                conn.execute('INSERT INTO coordinator.verified_receipts(id,incident_id,envelope,signature) VALUES(%s,%s,%s,%s)',
                    (result['receipt_id'],id,Jsonb(body.receipt['envelope']),body.receipt['signature']))
                conn.execute("UPDATE coordinator.documents SET status='CORROBORATED_BY_RECIPIENT' WHERE id=%s",(body.dispatch_document_id,))
                conn.execute("UPDATE coordinator.actions SET state='VERIFIED' WHERE id=%s",(body.action_id,))
                conn.execute("UPDATE coordinator.incidents SET state='BLOCKER_RESOLVED',decision_state='PENDING',version=version+1 WHERE id=%s",(id,))
                event(conn,id,'RECEIPT_VERIFIED',result)
            return result

    return app
