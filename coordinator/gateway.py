"""Public surface: call-scoped voice tools and a token-authenticated webhook.

No dashboard, uploads, operator endpoints, documentation or institution writes are exposed.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI,Request,HTTPException,Header
from fastapi.responses import Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
import httpx
from coordinator.voice_contracts import COMMON_CALL_CLOSING_NOTE
from pydantic import BaseModel,ConfigDict,Field

SANDBOX_ROUTE_TTL_SECONDS=900  # Matches the scoped sandbox call-token lifetime.


class ToolInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    call_token:str=Field(min_length=20,max_length=100)


class FactInput(ToolInput):
    request_type:Literal['PREAUTHORIZATION','FINAL_AUTHORIZATION']='FINAL_AUTHORIZATION'
    predicate:str=Field(min_length=1,max_length=50)
    reference:str=Field(min_length=1,max_length=100)
    fact_value:str=Field(max_length=2000)


class WorkflowInput(ToolInput):
    operation:Literal['REPORT_QUERY','REPORT_DOCUMENT','REPORT_UPDATE']
    details_json:str=Field(min_length=2,max_length=6000)


class ReferencesInput(ToolInput):
    admission_id:str=Field(min_length=1,max_length=100)
    initial_reference:str=Field(min_length=1,max_length=100)
    enhancement_reference:str=Field(min_length=1,max_length=100)
    final_reference:str=Field(min_length=1,max_length=100)
    submission_status:Literal['REPORTED_SUBMITTED','UNKNOWN']
    summary:str=Field(min_length=1,max_length=2000)


class QueryInput(ToolInput):
    query_reference:str=Field(min_length=1,max_length=100)
    claim_reference:str=Field(min_length=1,max_length=100)
    admission_id:str=Field(min_length=1,max_length=100)
    enhancement_reference:str=Field(min_length=1,max_length=100)
    received_at:str=Field(min_length=10,max_length=80)
    required_documents:Literal['itemized_bill,signed_discharge_summary,implant_invoice']
    enhancement_linked:Literal['true','false']


class DocumentInput(ToolInput):
    document_kind:Literal['itemized_bill','signed_discharge_summary','implant_invoice']
    document_reference:str=Field(min_length=1,max_length=100)
    ready:Literal['true','false']
    summary:str=Field(min_length=1,max_length=2000)


class UpdateInput(ToolInput):
    summary:str=Field(min_length=1,max_length=2000)
    dispatch_reference:str|None=Field(default=None,max_length=100)
    callback_at:str|None=Field(default=None,max_length=100)


class SandboxRouteRegistration(BaseModel):
    model_config=ConfigDict(extra='forbid')
    execution_id:str=Field(pattern=r'^[0-9a-fA-F-]{36}$')
    call_token:str=Field(pattern=r'^sbx_[A-Za-z0-9_-]{40,100}$')


def create_app(config=None,client=None,sandbox_client=None):
    if config is None:
        config=json.loads(Path(os.environ['CLAIM911_CORE_CONFIG']).read_text())
    core_url=config.get('core_url','http://127.0.0.1:8110').rstrip('/')
    target=urlsplit(core_url)
    if (target.scheme!='http' or target.hostname not in {'127.0.0.1','localhost'} or target.port is None
        or target.username or target.password or target.path or target.query or target.fragment):
        raise ValueError('Voice gateway upstream must be a local Claim911 API endpoint')
    if config.get('environment')=='sandbox':
        raise ValueError('Public voice gateway cannot use the isolated sandbox API as its default upstream')
    sandbox_url=config.get('sandbox_core_url','').rstrip('/')
    if sandbox_url:
        sandbox_target=urlsplit(sandbox_url)
        if (sandbox_target.scheme!='http' or sandbox_target.hostname not in {'127.0.0.1','localhost'}
            or sandbox_target.port is None or sandbox_target.username or sandbox_target.password
            or sandbox_target.path or sandbox_target.query or sandbox_target.fragment):
            raise ValueError('Sandbox voice upstream must be a separate local Claim911 coordinator endpoint')
    route_db=config.get('sandbox_route_db')
    route_registry_token=config.get('sandbox_route_registry_token')
    if sandbox_url and (not isinstance(route_db,str) or not Path(route_db).is_absolute() or not route_registry_token):
        raise ValueError('Sandbox voice routing requires a private persistent execution registry and broker token')
    if route_db:
        route_path=Path(route_db)
        route_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with sqlite3.connect(route_path) as registry:
            registry.execute('''CREATE TABLE IF NOT EXISTS sandbox_voice_routes(
                execution_id TEXT PRIMARY KEY,call_token_hash TEXT NOT NULL,expires_at REAL NOT NULL)''')
        os.chmod(route_path,0o600)
    app=FastAPI(title='Claim911 voice gateway',docs_url=None,redoc_url=None,openapi_url=None)
    counts={}

    @app.exception_handler(RequestValidationError)
    async def invalid_tool_input(request,exc):
        # Field locations/types help diagnose provider templates without logging tokens or values.
        print(json.dumps({'voice_tool_validation':request.url.path,
            'errors':[{'location':e['loc'],'type':e['type']} for e in exc.errors()]}),flush=True)
        return await request_validation_exception_handler(request,exc)

    @app.middleware('http')
    async def limits(request,call_next):
        # A single low-volume demo; shared process bucket also limits unauthenticated traffic.
        minute=int(time.time()//60);counts.setdefault(minute,0);counts[minute]+=1
        for old in list(counts):
            if old<minute-1:counts.pop(old,None)
        if counts[minute]>180:
            return Response('Rate limit exceeded',status_code=429)
        if int(request.headers.get('content-length','0'))>1024*1024:
            return Response('Payload exceeds limit',status_code=413)
        return await call_next(request)

    def auth(authorization):
        expected=config.get('gateway_token')
        if not expected or not secrets.compare_digest(authorization,'Bearer '+expected):
            raise HTTPException(403,'Voice gateway authentication required')

    async def forward(path,body=None,token=None,webhook=False,sandbox=False):
        sandbox=sandbox or (isinstance(token,str) and token.startswith('sbx_'))
        if sandbox and not sandbox_url:
            raise HTTPException(503,'Synthetic voice tools are not connected')
        target_url=sandbox_url if sandbox else core_url
        downstream=sandbox_client if sandbox else client
        headers={'X-Webhook-Token':config.get('sandbox_webhook_token') if sandbox else config['webhook_token']} if webhook else {'X-Call-Token':token}
        if webhook and not headers.get('X-Webhook-Token'):
            raise HTTPException(503,'Synthetic voice event route is not configured')
        if downstream is not None:
            response=downstream.request('GET' if body is None else 'POST',path,headers=headers,**({'json':body} if body is not None else {}))
        else:
            async with httpx.AsyncClient(base_url=target_url,timeout=15) as http:
                response=await http.request('GET' if body is None else 'POST',path,headers=headers,**({'json':body} if body is not None else {}))
        content=response.content
        if response.status_code==200 and path in {'/v1/tools/workflow','/v1/tools/references','/v1/tools/statements'}:
            value=response.json()
            if isinstance(value,dict):
                value['call_closing_note']=COMMON_CALL_CLOSING_NOTE
                value['call_closing_instruction']='When this call objective is finished or blocked, state the actual result and then say call_closing_note verbatim. Do not speak field names. An unfinished evidence check must continue first.'
                content=json.dumps(value).encode()
        return Response(content,status_code=response.status_code,media_type='application/json')

    def sandbox_call_token(body):
        """Find the provider-injected scoped token without trusting it for authorization."""
        stack=[body]
        while stack:
            value=stack.pop()
            if isinstance(value,dict):
                token=value.get('call_token')
                if isinstance(token,str) and token.startswith('sbx_'):
                    return token
                stack.extend(value.values())
            elif isinstance(value,list):
                stack.extend(value)
        return None

    def registered_sandbox_route(execution_id):
        if not route_db or not isinstance(execution_id,str):return None
        try:
            with sqlite3.connect(route_db,timeout=2) as registry:
                return registry.execute('SELECT call_token_hash FROM sandbox_voice_routes WHERE execution_id=? AND expires_at>?',
                                        (execution_id,time.time())).fetchone()
        except sqlite3.Error:
            raise HTTPException(503,'Sandbox voice route registry is unavailable') from None

    @app.get('/voice/sandbox-readiness',include_in_schema=False)
    def sandbox_readiness(authorization:str=Header(default='')):
        if not route_db or not route_registry_token or not secrets.compare_digest(authorization,'Bearer '+route_registry_token):
            raise HTTPException(403,'Trusted sandbox broker required')
        with sqlite3.connect(route_db,timeout=3) as registry:
            registry.execute('SELECT 1 FROM sandbox_voice_routes LIMIT 1').fetchone()
        return {'ready':bool(sandbox_url),'scope':'sandbox_callback_registry','phone_dispatch':False}

    @app.post('/voice/register-sandbox-session',include_in_schema=False)
    def register_sandbox_session(body:SandboxRouteRegistration,authorization:str=Header(default='')):
        if not route_db or not route_registry_token or not secrets.compare_digest(authorization,'Bearer '+route_registry_token):
            raise HTTPException(403,'Sandbox route registration is restricted to the trusted session broker')
        try:
            from uuid import UUID
            execution_id=str(UUID(body.execution_id))
            token_hash=hashlib.sha256(body.call_token.encode()).hexdigest()
            with sqlite3.connect(route_db,timeout=2) as registry:
                registry.execute('DELETE FROM sandbox_voice_routes WHERE expires_at<=?',(time.time(),))
                prior=registry.execute('SELECT call_token_hash FROM sandbox_voice_routes WHERE execution_id=?',(execution_id,)).fetchone()
                if prior and not secrets.compare_digest(prior[0],token_hash):
                    raise HTTPException(409,'Provider execution is already bound to another sandbox call')
                registry.execute('INSERT INTO sandbox_voice_routes(execution_id,call_token_hash,expires_at) VALUES(?,?,?) ON CONFLICT(execution_id) DO UPDATE SET expires_at=excluded.expires_at',
                                 (execution_id,token_hash,time.time()+SANDBOX_ROUTE_TTL_SECONDS))
            os.chmod(route_db,0o600)
        except sqlite3.Error:
            raise HTTPException(503,'Sandbox route registration could not be persisted') from None
        return {'registered':True,'environment':'sandbox','phone_dispatch':False}

    @app.post('/voice/references')
    async def references(body:ReferencesInput,authorization:str=Header(default='')):
        auth(authorization)
        return await forward('/v1/tools/references',body=body.model_dump(exclude={'call_token'}),token=body.call_token)

    @app.post('/voice/context')
    async def context(body:ToolInput,authorization:str=Header(default='')):
        auth(authorization)
        return await forward('/v1/tools/context',token=body.call_token)

    @app.post('/voice/statement')
    async def statement(body:FactInput,authorization:str=Header(default='')):
        auth(authorization)
        values={
            'SUBMITTED':{'submitted':True,'details':body.fact_value},
            'SUBMISSION_UNKNOWN':{'confirmed':False,'details':body.fact_value},
            'NOT_RECEIVED':{'found':False,'lookup_scope':body.fact_value},
            'DESTINATION':{'destination':body.fact_value},
            'RECEIVED':{'found':True,'details':body.fact_value},
            'REFERENCE_CORRECTION':{'corrected_reference':body.fact_value},
            'ACCESS_REFUSED':{'reason':body.fact_value},
        }
        if body.predicate not in values:
            raise HTTPException(422,'Unsupported statement predicate')
        return await forward('/v1/tools/statements',body={
            'predicate':body.predicate,'reference':body.reference,'request_type':body.request_type,
            'value':values[body.predicate]},token=body.call_token)

    @app.post('/voice/propose')
    async def propose(body:ToolInput,authorization:str=Header(default='')):
        auth(authorization)
        return await forward('/v1/tools/propose',body={},token=body.call_token)

    @app.post('/voice/workflow')
    async def workflow(body:WorkflowInput,authorization:str=Header(default='')):
        auth(authorization)
        try:
            details=json.loads(body.details_json)
            if not isinstance(details,dict):
                raise ValueError()
        except ValueError:
            print('Workflow tool details_json was not a JSON object',flush=True)
            raise HTTPException(422,'Workflow details must be a JSON object')
        return await forward('/v1/tools/workflow',body={'operation':body.operation,'details':details},token=body.call_token)

    @app.post('/voice/query')
    async def query_report(body:QueryInput,authorization:str=Header(default='')):
        auth(authorization)
        details=body.model_dump(exclude={'call_token'})
        details['required_documents']=body.required_documents.split(',')
        details['enhancement_linked']=body.enhancement_linked=='true'
        return await forward('/v1/tools/workflow',body={'operation':'REPORT_QUERY','details':details},token=body.call_token)

    @app.post('/voice/document')
    async def document_report(body:DocumentInput,authorization:str=Header(default='')):
        auth(authorization)
        details=body.model_dump(exclude={'call_token'})
        details['ready']=body.ready=='true'
        return await forward('/v1/tools/workflow',body={'operation':'REPORT_DOCUMENT','details':details},token=body.call_token)

    @app.post('/voice/update')
    async def update_report(body:UpdateInput,authorization:str=Header(default='')):
        auth(authorization)
        details={key:value for key,value in body.model_dump(exclude={'call_token'},exclude_none=True).items() if value!=''}
        return await forward('/v1/tools/workflow',body={'operation':'REPORT_UPDATE','details':details},token=body.call_token)

    @app.post('/voice/webhook')
    async def webhook(request:Request,x_webhook_token:str=Header(default='')):
        if not secrets.compare_digest(x_webhook_token,config['webhook_token']):
            raise HTTPException(403,'Webhook authentication required')
        raw=await request.body()
        if len(raw)>1024*1024:
            raise HTTPException(413,'Payload exceeds limit')
        try:
            body=json.loads(raw)
        except ValueError:
            raise HTTPException(422,'JSON payload required')
        token=sandbox_call_token(body)
        execution_id=body.get('id') or body.get('execution_id') if isinstance(body,dict) else None
        route=registered_sandbox_route(execution_id)
        if route:
            if token and not secrets.compare_digest(route[0],hashlib.sha256(token.encode()).hexdigest()):
                raise HTTPException(403,'Provider webhook scope does not match its registered execution')
            return await forward('/v1/webhooks/bolna',body=body,token=token,webhook=True,sandbox=True)
        if token and token.startswith('sbx_') and sandbox_url:
            raise HTTPException(403,'Sandbox browser execution was not registered by its trusted broker')
        return await forward('/v1/webhooks/bolna',body=body,token=token,webhook=True,sandbox=False)

    return app
