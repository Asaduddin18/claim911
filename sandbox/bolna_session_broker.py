"""Trusted host service for sandbox-only Bolna browser sessions.

This process holds the Bolna key. It has no database, institution credential,
operational API URL, or telephone dispatch capability. Package workers cannot
reach it; the sandbox product API invokes it using a separate local token.
"""
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from coordinator.bolna import Bolna, DispatchUnknown, ProviderRejected
from coordinator.workflow_calls import WORKFLOW_ROLES


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    call_token: str = Field(pattern=r'^sbx_[A-Za-z0-9_-]{40,100}$')
    recording_consent: Literal[True]
    context: dict


class RecordingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    execution_id: UUID
    call_id: UUID
    incident_id: UUID


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    execution_id: UUID
    call_id: UUID
    incident_id: UUID


def validate_config(config):
    if config.get('environment') != 'sandbox_bolna_broker':
        raise ValueError('This broker can serve only the isolated synthetic sandbox')
    forbidden = {'dsn', 'core_url', 'simulator_url', 'legacy_read_dsn', 'operator_token',
                 'simulator_agent_token', 'hospital_token', 'claims_token', 'insurer_token'}
    if forbidden.intersection(config):
        raise ValueError('The Bolna broker must not receive database, institution, or operational credentials')
    for key in ('bolna_api_key', 'bolna_agent_id', 'bolna_agent_config_sha256',
                'broker_token', 'gateway_registry_token', 'gateway_url','broker_registry_db'):
        if not config.get(key):
            raise ValueError('Required private sandbox broker configuration is missing')
    registry_path=Path(config['broker_registry_db'])
    if not registry_path.is_absolute():
        raise ValueError('Private broker session registry must use an absolute path')
    UUID(config['bolna_agent_id'])
    if not re.fullmatch(r'[a-f0-9]{64}', config['bolna_agent_config_sha256']):
        raise ValueError('Reviewed Bolna assistant fingerprint is required')
    parsed = urlsplit(config['gateway_url'].rstrip('/'))
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.trycloudflare.com')
        or parsed.username or parsed.password or parsed.port not in (None, 443)
        or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('A reviewed HTTPS voice gateway root is required')


def greeting(context):
    if context.get('purpose') == 'CAREGIVER_INTAKE':
        return "Hi, I'm Claim911. I have the synthetic case ready. What is holding things up?"
    if (context.get('purpose')=='RECORDS_DOCUMENT'
        and (context.get('workflow') or {}).get('active_followup',{}).get('purpose')=='RECORDS_DOCUMENT'):
        return "Hi, this is Claim911 following up about the unsigned discharge summary. Could you follow up with the treating team and upload its signed summary if it can now be released?"
    patient=context.get('patient_id','the synthetic patient')
    purpose=context.get('purpose')
    reference=context.get('reference')
    if reference and reference!='UNCONFIRMED_FINAL_REFERENCE':
        from coordinator.identifier_readbacks import readback
        reference=readback(reference)['spoken']
    openings={
        'HOSPITAL_REFERENCE_DISCOVERY':f"Hi, this is Claim911 calling about patient {patient}. Could you check the admission ID for me?",
        'QUERY_DISCOVERY':f"Hi, this is Claim911 calling about final request {reference} for patient {patient}. Is there an open information request on it?",
        'BILLING_DOCUMENT':f"Hi, this is Claim911 calling about the synthetic discharge for patient {patient}. Is the itemized bill ready?",
        'RECORDS_DOCUMENT':f"Hi, this is Claim911 calling about the synthetic discharge for patient {patient}. Has the treating team signed the discharge summary?",
        'IMPLANT_DOCUMENT':f"Hi, this is Claim911 calling about the synthetic discharge for patient {patient}. Is the implant invoice ready?",
        'PACKET_SUBMISSION':f"Hi, this is Claim911 calling about final request {reference}. Can you submit the approved response packet?",
        'TPA_QUERY_FOLLOWUP':f"Hi, this is Claim911 calling about final request {reference}. Has the response cleared the open query?",
        'INSURER_FOLLOWUP':f"Hi, this is Claim911 calling about final request {reference}. Has the insurer issued its decision?",
        'DISCHARGE_FOLLOWUP':f"Hi, this is Claim911 calling about final request {reference}. Has billing confirmed discharge clearance?",
        'CAREGIVER_COMPLEX_UPDATE':"Hi, this is Claim911. I have the verified hospital and insurer update. May I explain what it means for discharge?",
    }
    return openings.get(purpose,"Hi, this is Claim911 calling about the synthetic discharge. Could you help me check the current status?")


def initial_voice_context(context):
    """A task seed, not a copy of the accumulated case history.

    The full current context remains available through the authenticated tool.
    No case facts are invented, truncated or promoted to verified status.
    """
    keys={'incident_id','call_id','purpose','patient_id','reference','participant_role','simulated',
          'investigation_consent_active','recording_consent','allowed_statement_predicates','tool_policy',
          'uploaded_reference_candidates','uploaded_query_candidates','uploaded_document_candidates','uploaded_dispatch_candidates'}
    result={k:context[k] for k in keys if k in context}
    workflow=context.get('workflow') or {}
    fields={'query_reference','claim_reference','admission_id','original_received_at','target_at',
            'active_followup','assigned_document_kind','collected_document_kinds','approval_current',
            'receipt_verified','query_completion_verified','state'}
    if context.get('purpose')=='CAREGIVER_COMPLEX_UPDATE':fields.add('caregiver_summary')
    else:fields.update({'decision','clearance'})
    if context.get('purpose')=='PACKET_SUBMISSION':fields.add('approved_packet')
    result['workflow']={k:workflow[k] for k in fields if k in workflow}
    return result


def create_app(config=None, *, provider=None, registry_client=None):
    if config is None:
        config = json.loads(Path(__import__('os').environ['CLAIM911_BOLNA_BROKER_CONFIG']).read_text())
    validate_config(config)
    provider = provider or Bolna(config['bolna_api_key'])
    app = FastAPI(title='Claim911 trusted sandbox voice broker', docs_url=None,
                  redoc_url=None, openapi_url=None)
    registry_path=Path(config['broker_registry_db'])
    registry_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sqlite3.connect(registry_path) as registry:
        registry.execute('''CREATE TABLE IF NOT EXISTS sandbox_bolna_sessions(
            execution_id TEXT PRIMARY KEY,call_id TEXT NOT NULL,incident_id TEXT NOT NULL,
            created_at REAL NOT NULL,expires_at REAL NOT NULL)''')
        registry.execute('''CREATE TABLE IF NOT EXISTS sandbox_bolna_attempts(
            call_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,stage TEXT NOT NULL,
            execution_id TEXT,updated_at REAL NOT NULL)''')
    os.chmod(registry_path,0o600)

    def attempt(call_id, incident_id, stage, execution_id=None, *, begin=False):
        # Never persist the ephemeral session, call token, or provider error body.
        with sqlite3.connect(registry_path,timeout=3) as registry:
            if begin:
                try:
                    registry.execute('INSERT INTO sandbox_bolna_attempts VALUES(?,?,?,?,?)',
                        (call_id,incident_id,stage,None,time.time()))
                except sqlite3.IntegrityError:
                    raise HTTPException(409,'This call already has a session attempt; reconcile before another mint') from None
            else:
                registry.execute('UPDATE sandbox_bolna_attempts SET stage=?,execution_id=?,updated_at=? WHERE call_id=? AND incident_id=?',
                    (stage,execution_id,time.time(),call_id,incident_id))

    @app.middleware('http')
    async def bound_body(request, call_next):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 24000:
                return JSONResponse({'detail': 'Sandbox voice request exceeds its limit'}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @app.post('/session', status_code=201)
    def session(body: SessionRequest, authorization: str = Header(default='')):
        if not secrets.compare_digest(authorization, 'Bearer '+config['broker_token']):
            raise HTTPException(403, 'Trusted sandbox product API required')
        context = body.context
        if body.recording_consent is not True:
            raise HTTPException(422, 'Explicit recording permission is required for this synthetic run')
        if (not isinstance(context, dict) or context.get('simulated') is not True
            or context.get('purpose') not in WORKFLOW_ROLES
            or context.get('participant_role') != WORKFLOW_ROLES[context.get('purpose')]
            or not isinstance(context.get('objective'), str) or not 0 < len(context['objective']) <= 4000):
            raise HTTPException(422, 'A current, role-scoped synthetic call context is required')
        try:
            call_id = str(UUID(context['call_id']))
            incident_id = str(UUID(context['incident_id']))
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, 'A case-bound synthetic call context is required') from None
        try:
            current = provider.agent_configuration_fingerprint(config['bolna_agent_id'])
        except Exception:
            raise HTTPException(503, 'The reviewed Bolna assistant configuration could not be checked') from None
        if not secrets.compare_digest(current, config['bolna_agent_config_sha256']):
            raise HTTPException(409, 'The Bolna assistant changed after review; session withheld')
        # Probe the public path before incurring a provider mint. A stale tunnel
        # must never consume another session just to discover it is unavailable.
        probe=registry_client
        owns_probe=probe is None
        try:
            if owns_probe:
                import httpx
                probe=httpx.Client(timeout=5,follow_redirects=False)
            ready=probe.get(config['gateway_url'].rstrip('/')+'/voice/sandbox-readiness',
                headers={'Authorization':'Bearer '+config['gateway_registry_token']})
            if ready.status_code!=200 or ready.json()!={'ready':True,'scope':'sandbox_callback_registry','phone_dispatch':False}:
                raise ValueError('Sandbox callback registry is unavailable')
        except Exception:
            raise HTTPException(503,'Sandbox callback gateway is unavailable; no provider session was requested') from None
        finally:
            if owns_probe and probe is not None:probe.close()
        user_data = {
            'call_token': body.call_token,
            'claim911_case_id': incident_id,
            'claim911_purpose': context['purpose'],
            'claim911_objective': context['objective'],
            'claim911_context': json.dumps(initial_voice_context(context), separators=(',', ':'), default=str),
            'claim911_greeting': greeting(context),
        }
        if len(json.dumps(user_data).encode())>12000:
            raise HTTPException(422,'The task seed exceeds the browser-session context limit; no session requested')
        attempt(call_id,incident_id,'MINT_REQUESTED',begin=True)
        try:
            browser_session = provider.web_session(config['bolna_agent_id'], user_data)
        except ProviderRejected:
            attempt(call_id,incident_id,'PROVIDER_REJECTED')
            raise HTTPException(503, 'Bolna rejected the synthetic browser session') from None
        except DispatchUnknown:
            attempt(call_id,incident_id,'MINT_UNCERTAIN')
            raise HTTPException(503, 'Bolna session result is uncertain; reconcile before another attempt') from None
        except Exception:
            attempt(call_id,incident_id,'MINT_UNCERTAIN')
            raise HTTPException(503, 'Bolna browser session could not be prepared') from None
        attempt(call_id,incident_id,'MINTED',browser_session['run_id'])
        try:
            register = registry_client
            owns_client = register is None
            if owns_client:
                import httpx
                register = httpx.Client(timeout=5, follow_redirects=False)
            response = register.post(config['gateway_url'].rstrip('/')+'/voice/register-sandbox-session',
                headers={'Authorization': 'Bearer '+config['gateway_registry_token']},
                json={'execution_id': browser_session['run_id'], 'call_token': body.call_token})
            if response.status_code != 200:
                raise ValueError('Gateway did not persist the sandbox execution route')
        except Exception:
            attempt(call_id,incident_id,'CALLBACK_ROUTE_FAILED',browser_session['run_id'])
            raise HTTPException(503, 'Sandbox callback route was not secured; browser credentials withheld') from None
        finally:
            if 'owns_client' in locals() and owns_client:
                register.close()
        try:
            with sqlite3.connect(registry_path,timeout=3) as registry:
                prior=registry.execute('SELECT call_id,incident_id FROM sandbox_bolna_sessions WHERE execution_id=?',
                    (browser_session['run_id'],)).fetchone()
                expected=(call_id,incident_id)
                if prior and prior!=expected:
                    raise ValueError('Provider execution is already bound to another sandbox case')
                registry.execute('''INSERT INTO sandbox_bolna_sessions(execution_id,call_id,incident_id,created_at,expires_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(execution_id) DO UPDATE SET expires_at=excluded.expires_at''',
                    (browser_session['run_id'],call_id,incident_id,time.time(),time.time()+7*24*60*60))
            os.chmod(registry_path,0o600)
        except Exception:
            attempt(call_id,incident_id,'REGISTRY_FAILED',browser_session['run_id'])
            raise HTTPException(503, 'Sandbox recording access could not be secured; browser credentials withheld') from None
        attempt(call_id,incident_id,'READY',browser_session['run_id'])
        return {'call_id': call_id, 'transport': 'BOLNA_WEBRTC', 'synthetic': True,
                'phone_dispatch': False, 'assistant_config_sha256': current,
                'session': browser_session}

    @app.post('/recording')
    def recording(body:RecordingRequest,authorization:str=Header(default='')):
        if not secrets.compare_digest(authorization,'Bearer '+config['broker_token']):
            raise HTTPException(403,'Trusted sandbox product API required')
        with sqlite3.connect(registry_path,timeout=3) as registry:
            allowed=registry.execute('''SELECT 1 FROM sandbox_bolna_sessions WHERE execution_id=?
                AND call_id=? AND incident_id=? AND expires_at>?''',
                (str(body.execution_id),str(body.call_id),str(body.incident_id),time.time())).fetchone()
        if not allowed:
            raise HTTPException(404,'Recording is not available to this synthetic conversation')
        try:
            audio,mime=provider.recording(str(body.execution_id))
        except Exception:
            raise HTTPException(404,'The provider recording is not available yet') from None
        return Response(audio,media_type=mime,headers={
            'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'",
        })

    @app.post('/execution')
    def execution(body:ExecutionRequest,authorization:str=Header(default='')):
        if not secrets.compare_digest(authorization,'Bearer '+config['broker_token']):
            raise HTTPException(403,'Trusted sandbox product API required')
        with sqlite3.connect(registry_path,timeout=3) as registry:
            allowed=registry.execute('''SELECT 1 FROM sandbox_bolna_sessions WHERE execution_id=?
                AND call_id=? AND incident_id=? AND expires_at>?''',
                (str(body.execution_id),str(body.call_id),str(body.incident_id),time.time())).fetchone()
        if not allowed:
            raise HTTPException(404,'Execution is not available to this synthetic conversation')
        try:
            payload=provider.execution(str(body.execution_id))
            if not isinstance(payload,dict) or payload.get('id')!=str(body.execution_id):
                raise ValueError('Execution identity mismatch')
            transcript=payload.get('transcript','')
            status=payload.get('status')
            terminal_without_transcript={'balance-low','failed','busy','no-answer','cancelled'}
            if transcript is None and status in terminal_without_transcript:
                transcript=''
            if not isinstance(transcript,str) or len(transcript)>100_000:
                raise ValueError('Provider transcript is outside the response limit')
            if not isinstance(status,str) or status.lower() not in {
                'queued','ringing','in-progress','call-disconnected','completed','failed','busy','no-answer','cancelled','balance-low'
            }:
                raise ValueError('Provider execution status is unknown')
        except Exception:
            raise HTTPException(503,'Bolna execution evidence is temporarily unavailable') from None
        return {'execution_id':str(body.execution_id),'status':status.lower(),'transcript':transcript,
                'conversation_duration':payload.get('conversation_duration')}

    return app
