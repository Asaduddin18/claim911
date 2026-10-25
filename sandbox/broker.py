"""Trusted, run-scoped tool gateway. Provider secrets never enter package workers.

This broker exposes no URL proxy, token-mint endpoint or operational transport.
It must be wired only to isolated synthetic institution executors.
"""
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

OPERATIONS = {
    'caregiver': frozenset(),
    'hospital_insurance': frozenset({'read_status', 'dispatch_approved_packet'}),
    'billing': frozenset({'read_status', 'reconcile'}),
    'medical_records': frozenset({'read_status', 'release_signed_summary'}),
    'implant_store': frozenset({'read_status'}),
    'tpa': frozenset({'read_status', 'acknowledge_packet', 'link_enhancement'}),
    'insurer': frozenset({'read_status', 'issue_fixed_decision'}),
}


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: UUID
    case_id: UUID
    role: Literal['caregiver', 'hospital_insurance', 'billing', 'medical_records', 'implant_store', 'tpa', 'insurer']
    operation: str = Field(min_length=1, max_length=50)
    arguments: dict = Field(default_factory=dict)
    request_id: UUID


@dataclass
class Grant:
    run_id: str
    case_id: str
    role: str
    expires_at: float
    remaining: int
    revoked: bool = False
    results: dict = field(default_factory=dict)


class CapabilityRegistry:
    """Private controller interface. Registry reset invalidates all worker grants."""
    def __init__(self, executor, clock=time.monotonic):
        self.executor = executor
        self.clock = clock
        self._grants = {}
        self._lock = threading.RLock()

    def issue(self, run_id, case_id, role, ttl=300, max_calls=20):
        if role not in OPERATIONS or not 0 < ttl <= 900 or not 0 < max_calls <= 100:
            raise ValueError('Invalid bounded synthetic worker grant')
        token = secrets.token_urlsafe(40)
        grant = Grant(str(UUID(str(run_id))), str(UUID(str(case_id))), role, self.clock()+ttl, max_calls)
        with self._lock:
            self._grants[hashlib.sha256(token.encode()).hexdigest()] = grant
        return token

    def revoke_run(self, run_id):
        with self._lock:
            for grant in self._grants.values():
                if grant.run_id == str(run_id):
                    grant.revoked = True

    def execute(self, token, body):
        # Serialize dispatch and cache receipt to prevent duplicate side effects.
        # A process loss invalidates grants; reconcile state before issuing new ones.
        with self._lock:
            grant = self._grants.get(hashlib.sha256(token.encode()).hexdigest())
            if not grant or grant.revoked or self.clock() >= grant.expires_at:
                raise HTTPException(401, 'Worker capability expired or revoked')
            if (str(body.run_id), str(body.case_id), body.role) != (grant.run_id, grant.case_id, grant.role):
                raise HTTPException(403, 'Worker capability scope mismatch')
            if body.operation not in OPERATIONS[grant.role]:
                raise HTTPException(403, 'Operation is outside this desk capability')
            encoded = json.dumps(body.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))
            if len(encoded.encode()) > 16384:
                raise HTTPException(413, 'Tool request exceeds synthetic gateway limit')
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            key = str(body.request_id)
            if key in grant.results:
                previous = grant.results[key]
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Request identifier was reused with different arguments')
                if previous['state'] != 'completed':
                    raise HTTPException(409, 'Prior execution requires reconciliation')
                return previous['result']
            if grant.remaining <= 0:
                raise HTTPException(429, 'Synthetic worker tool budget exhausted')
            grant.remaining -= 1
            grant.results[key] = {'fingerprint': fingerprint, 'state': 'uncertain'}
            try:
                result = self.executor(grant.case_id, grant.role, body.operation, body.arguments)
            except PermissionError:
                raise HTTPException(403, 'Institution policy rejected the requested operation') from None
            except Exception:
                raise HTTPException(409, 'Execution requires reconciliation before retry') from None
            grant.results[key].update(state='completed', result=result)
            return result


def create_broker(registry, *, environment):
    if environment != 'sandbox':
        raise ValueError('This gateway is exclusively for synthetic sandbox institutions')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def body_limit(request, call_next):
        # Limit streamed bodies too, including requests without Content-Length.
        from starlette.responses import JSONResponse
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 20000:
                return JSONResponse({'detail': 'Request too large'}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @app.post('/tools')
    def tools(body: ToolRequest, request: Request):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            raise HTTPException(401, 'Worker capability required')
        return registry.execute(auth[7:], body)

    return app
