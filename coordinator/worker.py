"""Durable call worker. It never retries a call with an uncertain dispatch result."""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
import time
import hashlib
import re

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from coordinator.bolna import Bolna,DispatchUnknown,ProviderRejected
from sandbox import runs


class SandboxPhaseFailure(RuntimeError):
    """A local synthetic phase failed; retain only safe classification data."""
    def __init__(self,diagnostic):
        self.diagnostic=diagnostic
        super().__init__('Synthetic phase failed; review its preserved run evidence')


def _phase_failure_diagnostic(stdout,stderr,returncode):
    def safe_type(value):
        return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}',value) else 'SyntheticPhaseFailure'
    for stream in (stdout,stderr):
        for line in reversed((stream or '').splitlines()):
            try:message=json.loads(line)
            except (ValueError,TypeError):continue
            if message.get('state')=='REVIEW_REQUIRED':
                result={'exit_code':returncode,'error_type':safe_type(message.get('error_type'))}
                boundary=message.get('boundary')
                if isinstance(boundary,dict):
                    safe={}
                    if boundary.get('operation') in {'transcribe','synthesize','reply','judge','persona'}:safe['operation']=boundary['operation']
                    if type(boundary.get('status')) is int and 400<=boundary['status']<=599:safe['status']=boundary['status']
                    if boundary.get('failure') in {'InvalidApiKey','AuthenticationFailed','AuthorizationFailed','ResourceNotFound','QuotaExceeded','Forbidden'}:safe['failure']=boundary['failure']
                    if safe:result['boundary']=safe
                location=message.get('failure_location')
                if isinstance(location,dict):
                    safe_location={}
                    if isinstance(location.get('file'),str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',location['file']):safe_location['file']=location['file']
                    if isinstance(location.get('function'),str) and re.fullmatch(r'[A-Za-z0-9_]{1,100}',location['function']):safe_location['function']=location['function']
                    if type(location.get('line')) is int and location['line']>0:safe_location['line']=location['line']
                    if safe_location:result['failure_location']=safe_location
                return result
    types=re.findall(r'(?:^|\n)([A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):',(stderr or '')+'\n'+(stdout or ''))
    error_type=safe_type(types[-1]) if types else 'SyntheticPhaseFailure'
    return {'exit_code':returncode,'error_type':error_type}


SANDBOX_PHASE_TIMEOUT_SECONDS=600
SANDBOX_JOB_LEASE_SECONDS=SANDBOX_PHASE_TIMEOUT_SECONDS+120


def sandbox_phase_command(config,run_id,transport,*,runtime=None):
    """One explicit transport, runtime and budget category for queued phases."""
    import sys,shutil
    from uuid import UUID
    if config.get('environment')!='sandbox' or config.get('bolna_api_key') or config.get('live_calls_enabled'):
        raise PermissionError('Isolated non-phone phase required')
    UUID(str(run_id))
    selected={'BOLNA_WEBRTC':'bolna-browser','PIPECAT_STDIO':'pipecat'}.get(transport)
    if not selected:raise ValueError('Explicit known assistant transport required')
    phase=config.get('sandbox_spend_phase','rehearsal')
    if phase not in {'development','rehearsal'}:raise ValueError('Approved spend phase required')
    node=config.get('sandbox_node_binary') or shutil.which('node')
    if selected=='bolna-browser' and (not node or not Path(node).is_absolute() or not Path(node).is_file() or not os.access(node,os.X_OK)):
        raise ValueError('Existing absolute executable Node runtime required')
    script=Path(__file__).resolve().parents[1]/'scripts/run_sandbox_workflow.py'
    command=[sys.executable,str(script),'--run-id',str(run_id),'--single-step',
             '--transport',selected,'--phase',phase,'--participant-mode','adaptive']
    if selected=='bolna-browser':command+=['--node',node]
    if runtime is not None:
        root=Path(runtime).resolve()
        if not (root/'sandbox/coordinator.json').is_file():raise ValueError('Existing explicit sandbox runtime required')
        command+=['--runtime',str(root)]
    return command


def sandbox_once(config,execute_phase,job_id=None):
    """Consume one synthetic phase using the existing durable job machinery.

    The trusted executor, not its return value, owns independent verification.
    Lost executions require reconciliation and are never put back on the queue.
    """
    if config.get('environment')!='sandbox' or config.get('live_calls_enabled') or config.get('bolna_api_key'):
        raise PermissionError('Sandbox-only profile without phone credentials required')
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        expired=conn.execute("UPDATE coordinator.jobs SET state='DISPATCH_UNKNOWN',last_error='Synthetic worker lost; reconcile before retry' WHERE kind='SANDBOX_PHASE' AND state='DISPATCHING' AND lease_until<now() RETURNING payload").fetchall()
        for lost in expired:
            run=runs.get(conn,lost['payload']['run_id'],True)
            if run['state'] in {'RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'}:
                runs.mark_uncertain(conn,run['id'],run['lease_token'],'Synthetic job worker lost')
        job=conn.execute("SELECT j.* FROM coordinator.jobs j JOIN coordinator.sandbox_runs r ON r.id=(j.payload->>'run_id')::uuid WHERE j.kind='SANDBOX_PHASE' AND j.state='QUEUED' AND j.available_at<=now() AND (%s::uuid IS NOT NULL OR r.origin IN ('USER_PREPARED','AUDIO_DEMONSTRATION')) AND (%s::uuid IS NULL OR j.id=%s::uuid) ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1",(job_id,job_id,job_id)).fetchone()
        if not job:return bool(expired)
        run=runs.get(conn,job['payload']['run_id'],True)
        incident=conn.execute('SELECT is_test,consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(job['incident_id'],)).fetchone()
        transport=(run.get('provider_configuration') or {}).get('transport')
        allowed=(str(run['incident_id'])==str(job['incident_id']) and run['state'] in {'READY','PAUSED'} and incident
                 and incident['is_test'] and incident['consent_active'] and incident['consent_version']==run['consent_version']
                 and transport in {'PIPECAT_STDIO','BOLNA_WEBRTC'}
                 and job['payload'].get('transport')==transport)
        if not allowed:
            conn.execute("UPDATE coordinator.jobs SET state='CANCELLED',last_error='Synthetic run no longer eligible' WHERE id=%s",(job['id'],))
            return True
        # Offline verifier fixtures are consumed only by explicit test job IDs.
        # Genuine queued work must remain untouched while dispatch is disabled.
        if run['origin']!='VERIFICATION_FIXTURE':
            if not config.get('sandbox_execution_enabled'):return False
            from sandbox.spend import testing_readiness
            if not testing_readiness(conn)['allowed']:return False
        checkpoint=run['checkpoint']
        conn.execute("UPDATE coordinator.jobs SET state='DISPATCHING',lease_until=now()+(%s * interval '1 second'),attempts=attempts+1 WHERE id=%s",(SANDBOX_JOB_LEASE_SECONDS,job['id']))
    failed=False;failure=None
    try:execute_phase(str(run['id']))
    except Exception as exc:
        failed=True
        if isinstance(exc,SandboxPhaseFailure):failure=exc.diagnostic
        else:
            name=type(exc).__name__
            failure={'error_type':name if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}',name) else 'SyntheticPhaseFailure'}
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        current=runs.get(conn,run['id'],True)
        verified=(not failed and current['checkpoint']==checkpoint+1 and current['state'] in {'PAUSED','COMPLETED'})
        waiting=(not failed and current['checkpoint']==checkpoint and current['state']=='PAUSED' and conn.execute("SELECT 1 FROM coordinator.sandbox_run_events WHERE run_id=%s AND type='DOCUMENT_CALLBACK_WAITING' AND created_at>=%s",(run['id'],job['created_at'])).fetchone())
        escalated=(not failed and current['checkpoint']==checkpoint and current['state']=='ESCALATED' and conn.execute("SELECT 1 FROM coordinator.sandbox_run_events WHERE run_id=%s AND type='RUN_CALLBACK_ESCALATED' AND created_at>=%s",(run['id'],job['created_at'])).fetchone())
        state='DONE' if verified else 'WAITING_CALLBACK' if waiting else 'ESCALATED' if escalated else 'DISPATCH_UNKNOWN'
        conn.execute('UPDATE coordinator.jobs SET state=%s,lease_until=NULL,last_error=%s WHERE id=%s',
                     (state,None if verified or waiting or escalated else 'Synthetic outcome requires reconciliation',job['id']))
        payload={'job_id':str(job['id']),'state':state,'verified_checkpoint_advanced':verified,'run_escalated':bool(escalated),'automatic_retry':False}
        if failure:payload['failure']=failure
        runs.event(conn,run['id'],'RUN_JOB_RESULT',payload)
        if verified and current['state']=='PAUSED':runs.enqueue(conn,run['id'])
        if waiting and config.get('sandbox_accelerate_callbacks'):
            runs.advance_clock(conn,run['id'],60)
            runs.event(conn,run['id'],'CALLBACK_REHEARSAL_ACCELERATED',{'seconds':60,'original_receiving_time_unchanged':True})
            runs.enqueue(conn,run['id'])
    return True


def validate_webhook_only_profile(config):
    if (config.get('environment')!='sandbox' or config.get('bolna_api_key')
            or config.get('live_calls_enabled') or not config.get('outbound_paused')):
        raise PermissionError('Webhook-only mode requires the isolated, key-free, phone-paused sandbox profile')


def work_once(config,provider=None,job_id=None):
    """Return whether a job was handled. Provider injection is only used by tests."""
    if config.get('outbound_paused'):
        return False
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        # A process lost after dispatch may have placed a call. Never recycle it.
        expired=conn.execute("""UPDATE coordinator.jobs SET state='DISPATCH_UNKNOWN',
            last_error='Worker lease expired after dispatch; operator reconciliation required'
            WHERE kind='OUTBOUND_CALL' AND state='DISPATCHING' AND lease_until<now() RETURNING payload""").fetchall()
        for row in expired:
            conn.execute("UPDATE coordinator.calls SET state='DISPATCH_UNKNOWN' WHERE id=%s",(row['payload']['call_id'],))
        job=conn.execute("""SELECT j.* FROM coordinator.jobs j JOIN coordinator.calls c ON c.id=(j.payload->>'call_id')::uuid
            WHERE j.kind='OUTBOUND_CALL' AND j.state='QUEUED' AND j.available_at<=now() AND (%s OR c.mode='BOLNA')
            AND (%s::uuid IS NULL OR j.id=%s::uuid) ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (provider is not None,job_id,job_id)).fetchone()
        if not job:
            return bool(expired)
        incident=conn.execute('SELECT * FROM coordinator.incidents WHERE id=%s FOR UPDATE',(job['incident_id'],)).fetchone()
        payload=job['payload']
        call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s',(payload['call_id'],)).fetchone()
        participant=conn.execute('SELECT * FROM coordinator.participants WHERE id=%s',(call['participant_id'],)).fetchone()
        reason=None
        if call['mode']=='BOLNA_MOCK' and provider is None:
            reason='Test-provider calls cannot be sent to a live provider'
        elif not config.get('live_calls_enabled') or not config.get('bolna_api_key') or not config.get('bolna_agent_id'):
            reason='Live calling is not configured and enabled'
        elif not incident['consent_active'] or incident['consent_version']!=call['consent_version']:
            reason='Current investigation consent is missing or changed'
        elif not participant['verified'] or not participant['demo_consent']:
            reason='Participant verification or demo consent is missing'
        elif datetime.now(timezone.utc)>call['tool_expires_at']:
            reason='Call authorization expired before dispatch'
        elif incident['state'] in ['HUMAN_REVIEW','PAUSED_REVOKED']:
            reason='Incident is held for review or revoked'
        if payload.get('action_id'):
            action=conn.execute('SELECT * FROM coordinator.actions WHERE id=%s AND incident_id=%s',
                                (payload['action_id'],incident['id'])).fetchone()
            if not action or action['state']!='AUTHORIZED' or action['consent_version']!=incident['consent_version']:
                reason='Exact correction authorization is no longer valid'
        if call.get('workflow_packet_hash'):
            from coordinator.workflow_calls import approval_valid,approval_allows_call
            w=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(incident['id'],)).fetchone()
            if not w or not approval_valid(incident,w['data'],call['workflow_packet_hash']) or not approval_allows_call(w['data'],call['mode']):
                reason='Exact document packet authorization changed'
        if not reason and provider is None:
            from coordinator.gateway_preflight import check_gateway
            readiness=check_gateway(config)
            if not readiness['ready']:
                reason=readiness['reason']
        if reason:
            conn.execute("UPDATE coordinator.jobs SET state='CANCELLED',last_error=%s WHERE id=%s",(reason,job['id']))
            conn.execute("UPDATE coordinator.calls SET state='CANCELLED' WHERE id=%s",(call['id'],))
            conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',
                         (incident['id'],'CALL_CANCELLED_BEFORE_DISPATCH',Jsonb({'call_id':str(call['id']),'reason':reason})))
            return True
        conn.execute("UPDATE coordinator.jobs SET state='DISPATCHING',lease_until=now()+interval '2 minutes',attempts=attempts+1 WHERE id=%s",(job['id'],))
        conn.execute("UPDATE coordinator.calls SET state='DISPATCHING' WHERE id=%s",(call['id'],))
        # Commit intent before the network side effect.
    provider=provider or Bolna(config['bolna_api_key'])
    try:
        execution_id=provider.call(config['bolna_agent_id'],participant['phone'],payload['user_data'])
        state='QUEUED';error=None
    except DispatchUnknown as exc:
        execution_id=None;state='DISPATCH_UNKNOWN';error=str(exc)
    except ProviderRejected as exc:
        execution_id=None;state='FAILED';error=str(exc)
    except Exception:
        # Unexpected failures are also uncertain once the dispatch boundary was crossed.
        execution_id=None;state='DISPATCH_UNKNOWN';error='Unexpected dispatch failure; reconcile before retry'
    with psycopg.connect(config['dsn']) as conn:
        conn.execute('UPDATE coordinator.calls SET state=%s,execution_id=%s WHERE id=%s',(state,execution_id,call['id']))
        conn.execute('UPDATE coordinator.jobs SET state=%s,lease_until=NULL,last_error=%s WHERE id=%s',
                     ('DONE' if execution_id else state,error,job['id']))
        if execution_id:
            current=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(incident['id'],)).fetchone()
            if not current[0] or current[1]!=call['consent_version']:
                conn.execute("INSERT INTO coordinator.jobs(id,incident_id,kind,payload) VALUES(%s,%s,'STOP_CALL',%s)",
                    (uuid4(),incident['id'],Jsonb({'call_id':str(call['id']),'execution_id':execution_id})))
        conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',
                     (incident['id'],'CALL_DISPATCH_RESULT',Jsonb({'call_id':str(call['id']),'state':state,
                      'execution_id':execution_id,'error':error,'real_call':bool(execution_id and call['mode']=='BOLNA')})))
    return True


def stop_once(config,provider=None,call_id=None):
    """A stop command never dispatches a call. Failure does not assert cancellation."""
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        # Stop is safe to retry after a lost worker, unlike outbound dispatch.
        conn.execute("UPDATE coordinator.jobs SET state='QUEUED' WHERE kind='STOP_CALL' AND state='STOPPING' AND lease_until<now()")
        job=conn.execute("""SELECT j.*,c.mode FROM coordinator.jobs j JOIN coordinator.calls c ON c.id=(j.payload->>'call_id')::uuid
            WHERE j.kind='STOP_CALL' AND j.state='QUEUED' AND (%s OR c.mode IN ('BOLNA','BOLNA_WEBRTC'))
            AND (%s::uuid IS NULL OR c.id=%s::uuid) ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (provider is not None,call_id,call_id)).fetchone()
        if not job:
            return False
        conn.execute("UPDATE coordinator.jobs SET state='STOPPING',lease_until=now()+interval '1 minute',attempts=attempts+1 WHERE id=%s",(job['id'],))
    provider=provider or Bolna(config.get('bolna_api_key'))
    confirmed=False
    try:
        result=provider.stop(job['payload']['execution_id'])
        confirmed=result.get('status')=='stopped' and result.get('execution_id')==job['payload']['execution_id']
    except Exception:
        pass
    with psycopg.connect(config['dsn']) as conn:
        conn.execute("UPDATE coordinator.jobs SET state=%s,lease_until=NULL,last_error=%s WHERE id=%s",
            ('DONE' if confirmed else 'STOP_UNCONFIRMED',None if confirmed else 'Provider stop not confirmed; monitor call and obtain human assistance',job['id']))
        if confirmed:
            conn.execute("UPDATE coordinator.calls SET state='CANCELLED' WHERE id=%s AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER')",(job['payload']['call_id'],))
        conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',
            (job['incident_id'],'CALL_STOP_CONFIRMED' if confirmed else 'CALL_STOP_UNCONFIRMED',Jsonb({'call_id':job['payload']['call_id'],'confirmed_stopped':confirmed})))
    return True


def process_webhook_once(config,execution_id=None):
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        message=conn.execute('''SELECT i.* FROM coordinator.webhook_inbox i WHERE i.processed_at IS NULL
            AND (%s::text IS NULL OR COALESCE(i.payload->>'id',i.payload->>'execution_id')=%s)
            ORDER BY EXISTS (SELECT 1 FROM coordinator.calls c WHERE c.execution_id=COALESCE(i.payload->>'id',i.payload->>'execution_id')) DESC,i.id
            FOR UPDATE OF i SKIP LOCKED LIMIT 1''',(execution_id,execution_id)).fetchone()
        if not message:
            return False
        payload=message['payload'];execution_id=payload.get('id') or payload.get('execution_id')
        call=conn.execute('SELECT * FROM coordinator.calls WHERE execution_id=%s FOR UPDATE',(execution_id,)).fetchone()
        if not call:
            # Keep an early event, but do not starve later known executions forever.
            if (datetime.now(timezone.utc)-message['created_at']).total_seconds()>120:
                conn.execute('UPDATE coordinator.webhook_inbox SET processed_at=now() WHERE id=%s',(message['id'],))
                return True
            return False
        incoming=str(payload.get('status','')).upper().replace('-','_')
        allowed={'QUEUED','SCHEDULED','INITIATED','RINGING','IN_PROGRESS','CALL_DISCONNECTED','COMPLETED',
                 'FAILED','CANCELLED','BUSY','NO_ANSWER'}
        terminal={'COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER'}
        ranks={'SCHEDULED':0,'DISPATCHING':0,'QUEUED':1,'INITIATED':2,'RINGING':3,'IN_PROGRESS':4,'CALL_DISCONNECTED':5}
        state=call['state']
        if incoming in allowed and state not in terminal and (incoming in terminal or ranks.get(incoming,0)>=ranks.get(state,0)):
            state=incoming
        transcript=call['transcript']
        # Only finalized provider data populates the visible conversation.
        if incoming=='COMPLETED' and isinstance(payload.get('transcript'),str):
            transcript=[{'speaker':'provider_transcript','text':payload['transcript']}]
        elif incoming=='COMPLETED' and isinstance(payload.get('transcript'),list):
            cleaned=[]
            for turn in payload['transcript']:
                if isinstance(turn,dict) and isinstance(turn.get('content') or turn.get('text'),str):
                    cleaned.append({'speaker':str(turn.get('role') or turn.get('speaker') or 'unknown'),
                                    'text':turn.get('content') or turn.get('text')})
            if cleaned:
                transcript=cleaned
        recording=call['recording_url']
        telephony=payload.get('telephony_data')
        candidate=payload.get('recording_url') or (telephony.get('recording_url') if isinstance(telephony,dict) else None)
        if incoming=='COMPLETED' and call['recording_consent'] and isinstance(candidate,str) and candidate:
            recording=candidate
        conn.execute('UPDATE coordinator.calls SET state=%s,transcript=%s,recording_url=%s WHERE id=%s',
                     (state,Jsonb(transcript),recording,call['id']))
        conn.execute('UPDATE coordinator.webhook_inbox SET processed_at=now() WHERE id=%s',(message['id'],))
        conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',
                     (call['incident_id'],'CALL_STATUS_UPDATED',Jsonb({'call_id':str(call['id']),'state':state,
                      'transcript_available':bool(transcript),'recording_available':bool(recording)})))
        return True


def poll_once(config,provider=None,call_id=None):
    """Reconcile a known execution when callbacks are late or unavailable."""
    if not config.get('bolna_api_key'):
        return False
    with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
        row=conn.execute("""SELECT * FROM coordinator.calls WHERE execution_id IS NOT NULL
            AND (mode IN ('BOLNA','BOLNA_WEBRTC') OR (%s AND mode='BOLNA_MOCK'))
            AND (state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER') OR (state='COMPLETED' AND (transcript='[]'::jsonb OR (recording_consent AND recording_url IS NULL))))
            AND (%s::uuid IS NULL OR id=%s::uuid) AND poll_failures<8
            AND (last_polled_at IS NULL OR last_polled_at<now()-interval '5 seconds')
            ORDER BY last_polled_at NULLS FIRST,created_at FOR UPDATE SKIP LOCKED LIMIT 1""",
            (provider is not None,call_id,call_id)).fetchone()
        if not row:
            return False
        conn.execute('UPDATE coordinator.calls SET last_polled_at=now() WHERE id=%s',(row['id'],))
    provider=provider or Bolna(config['bolna_api_key'])
    try:
        payload=provider.execution(row['execution_id'])
        returned_id=payload.get('id') or payload.get('execution_id')
        if returned_id and returned_id!=row['execution_id']:
            raise ValueError('Provider returned a different execution')
        payload['id']=row['execution_id']
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
        with psycopg.connect(config['dsn']) as conn:
            conn.execute('INSERT INTO coordinator.webhook_inbox(dedupe_key,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING',
                         ('poll-'+fingerprint,Jsonb(payload)))
            conn.execute('UPDATE coordinator.calls SET poll_failures=0 WHERE id=%s',(row['id'],))
    except Exception:
        with psycopg.connect(config['dsn']) as conn:
            conn.execute('UPDATE coordinator.calls SET poll_failures=poll_failures+1 WHERE id=%s',(row['id'],))
    return True


def tick(config,observe_only=False):
    """Observation processes existing calls but never enters outbound dispatch."""
    worked=stop_once(config)
    worked=process_webhook_once(config) or worked
    worked=poll_once(config) or worked
    if not observe_only:
        worked=work_once(config) or worked
    return worked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observe-only',action='store_true',help='Process status and stop commands without dispatching calls')
    parser.add_argument('--sandbox',action='store_true',help='Consume isolated audio phases only; never process phone jobs')
    parser.add_argument('--webhook-only',action='store_true',help='Process sandbox provider callbacks without polling or dispatch')
    args=parser.parse_args()
    if sum((args.sandbox,args.observe_only,args.webhook_only))>1:parser.error('Choose one worker mode')
    if args.webhook_only:
        config=json.loads(Path(os.environ['CLAIM911_CORE_CONFIG']).read_text())
        try:validate_webhook_only_profile(config)
        except PermissionError as exc:parser.error(str(exc))
        print('Claim911 worker: sandbox webhooks only; no provider polling or call dispatch',flush=True)
        while True:
            try:worked=process_webhook_once(config)
            except Exception:
                print('Sandbox webhook processing failed; callback remains available for reconciliation',flush=True)
                worked=False
            if not worked:time.sleep(1)
    print('Claim911 worker: isolated synthetic audio only' if args.sandbox else 'Claim911 worker: observation only, outbound dispatch disabled' if args.observe_only else 'Claim911 worker: outbound dispatch enabled',flush=True)
    def execute_phase(run_id):
        import subprocess,sys
        script=Path(__file__).resolve().parents[1]/'scripts/run_sandbox_workflow.py'
        with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:
            run=runs.get(conn,run_id);transport=(run.get('provider_configuration') or {}).get('transport')
        profile=Path(os.environ['CLAIM911_CORE_CONFIG']).resolve()
        if profile.parent.name!='sandbox':raise PermissionError('Worker runtime must come from its sandbox profile directory')
        command=sandbox_phase_command(config,run_id,transport,runtime=profile.parent.parent)
        result=subprocess.run(command,capture_output=True,text=True,timeout=SANDBOX_PHASE_TIMEOUT_SECONDS)
        if result.returncode:
            raise SandboxPhaseFailure(_phase_failure_diagnostic(result.stdout,result.stderr,result.returncode))
    if args.sandbox:
        import atexit
        from sandbox.readiness import Heartbeat
        from sandbox.runs import initialize
        config=json.loads(Path(os.environ['CLAIM911_CORE_CONFIG']).read_text())
        with psycopg.connect(config['dsn'],row_factory=dict_row) as conn:initialize(conn,environment=config['environment'])
        pulse=Heartbeat(config);pulse.start();atexit.register(pulse.close)
    while True:
        config=json.loads(Path(os.environ['CLAIM911_CORE_CONFIG']).read_text())
        try:
            worked=sandbox_once(config,execute_phase) if args.sandbox else tick(config,observe_only=args.observe_only)
        except Exception:
            # Do not log private payloads, provider data or configuration on transient failures.
            print('Worker cycle failed; existing job identities preserved for recovery',flush=True)
            worked=False
        if not worked:
            time.sleep(1)


if __name__=='__main__':
    main()
