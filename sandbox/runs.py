"""Durable synthetic run lifecycle, independent of conversational success claims."""
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from sandbox.actors import scenario_manifest


def initialize(conn,*,environment):
    if environment!='sandbox':raise ValueError('Scenario runs require isolated sandbox storage')
    conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_runs(
      id uuid PRIMARY KEY,scenario_id text NOT NULL,scenario_version integer NOT NULL,
      language text NOT NULL,manifest jsonb NOT NULL,state text NOT NULL DEFAULT 'PREPARED',
      incident_id uuid REFERENCES coordinator.incidents(id),institution_case_id uuid,
      consent_version integer,
      provider_configuration jsonb,checkpoint integer NOT NULL DEFAULT 0,
      elapsed_seconds integer NOT NULL DEFAULT 0,faults jsonb NOT NULL DEFAULT '[]',
      lease_token uuid,lease_until timestamptz,created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now())''')
    conn.execute('ALTER TABLE coordinator.sandbox_runs ADD COLUMN IF NOT EXISTS consent_version integer')
    conn.execute("ALTER TABLE coordinator.sandbox_runs ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'AUDIO_RUN'")
    conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_run_events(
      sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,run_id uuid NOT NULL REFERENCES coordinator.sandbox_runs(id),
      type text NOT NULL,payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now())''')
    conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_workers(
      id uuid PRIMARY KEY,expires_at timestamptz NOT NULL)''')


def event(conn,id,kind,payload):
    conn.execute('INSERT INTO coordinator.sandbox_run_events(run_id,type,payload) VALUES(%s,%s,%s)',(id,kind,Jsonb(payload)))


def get(conn,id,lock=False):
    row=conn.execute('SELECT * FROM coordinator.sandbox_runs WHERE id=%s'+(' FOR UPDATE' if lock else ''),(id,)).fetchone()
    if not row:raise HTTPException(404,'Synthetic run not found')
    return row


def valid_provider_configuration(provider_configuration):
    pipecat={'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'}
    bolna=(isinstance(provider_configuration,dict)
        and set(provider_configuration)=={'transport','assistant_config_sha256'}
        and provider_configuration.get('transport')=='BOLNA_WEBRTC'
        and isinstance(provider_configuration.get('assistant_config_sha256'),str)
        and len(provider_configuration['assistant_config_sha256'])==64
        and all(c in '0123456789abcdef' for c in provider_configuration['assistant_config_sha256']))
    return provider_configuration==pipecat or bolna


def execution_manifest(component=None):
    manifest=scenario_manifest()
    if component is not None:
        # Only independent entry-stage components are supported. Later stages
        # require legitimate prerequisite evidence, never fabricated checkpoints.
        if component not in {'caregiver_intake_confirmed','hospital_references_reported','claims_query_discovered'}:
            raise ValueError('Unsupported independent voice component')
        if component not in manifest['checkpoints']:
            raise ValueError('Component is absent from the versioned scenario')
        manifest['checkpoints']=[component]
        manifest['execution_scope']='COMPONENT'
        if component=='claims_query_discovered':
            manifest['starting_state']='EXPLICIT_SYNTHETIC_FINAL_REFERENCE_FIXTURE'
    return manifest


def full_case_completed(row):
    return (row['state']=='COMPLETED'
        and row['manifest'].get('execution_scope','FULL_CASE')=='FULL_CASE'
        and row['manifest']['checkpoints']==scenario_manifest()['checkpoints'])


def create(conn,*,language='en',origin='AUDIO_RUN',component=None):
    if origin not in {'AUDIO_RUN','AUDIO_DEMONSTRATION','USER_PREPARED','VERIFICATION_FIXTURE'}:raise ValueError('Known scenario origin required')
    manifest=execution_manifest(component)
    if language not in manifest['languages']:raise HTTPException(422,'Scenario language unavailable')
    id=uuid4()
    row=conn.execute('''INSERT INTO coordinator.sandbox_runs(id,scenario_id,scenario_version,language,manifest,faults,origin)
      VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *''',(id,manifest['id'],manifest['version'],language,Jsonb(manifest),Jsonb(manifest['default_faults']),origin)).fetchone()
    event(conn,id,'RUN_PREPARED',{'scenario_id':manifest['id'],'scenario_version':manifest['version'],'transport':'SANDBOX_AUDIO'})
    return row


def attach_case(conn,id,*,incident_id,institution_case_id,provider_configuration):
    row=get(conn,id,True)
    if row['state']!='PREPARED':raise HTTPException(409,'Run has already been bound')
    # Only public provenance and the reviewed Bolna configuration fingerprint,
    # never raw runtime configuration or credentials.
    if not valid_provider_configuration(provider_configuration):
        raise HTTPException(422,'Exact public provider provenance required')
    incident=conn.execute('SELECT case_id,is_test,consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(incident_id,)).fetchone()
    if not incident or not incident['is_test'] or not incident['consent_active'] or str(incident['case_id'])!=str(institution_case_id):
        raise HTTPException(409,'Consented synthetic incident must match the institution case')
    result=conn.execute("UPDATE coordinator.sandbox_runs SET incident_id=%s,institution_case_id=%s,consent_version=%s,provider_configuration=%s,state='READY',updated_at=now() WHERE id=%s RETURNING *",(incident_id,institution_case_id,incident['consent_version'],Jsonb(provider_configuration),id)).fetchone()
    event(conn,id,'RUN_READY',{'incident_id':str(incident_id),'institution_case_id':str(institution_case_id),'provider_configuration':provider_configuration})
    return result


def claim(conn,id,*,now=None):
    now=now or datetime.now(timezone.utc);row=get(conn,id,True)
    if row['state'] in {'RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'} and row['lease_until'] and row['lease_until']<=now:
        conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN',lease_token=NULL,lease_until=NULL,updated_at=%s WHERE id=%s",(now,id))
        event(conn,id,'RUN_WORKER_LOST',{'automatic_retry':False,'checkpoint':row['checkpoint']})
        return None
    if row['state']!='READY':return None
    incident=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(row['incident_id'],)).fetchone()
    if not incident or not incident['consent_active'] or incident['consent_version']!=row['consent_version']:
        conn.execute("UPDATE coordinator.sandbox_runs SET state='CANCELLED',updated_at=%s WHERE id=%s",(now,id))
        event(conn,id,'RUN_CONSENT_CANCELLED',{'automatic_restart':False});return None
    if row['elapsed_seconds']>=row['manifest']['limits']['max_run_minutes']*60:
        conn.execute("UPDATE coordinator.sandbox_runs SET state='ESCALATED',updated_at=%s WHERE id=%s",(now,id))
        event(conn,id,'RUN_TIME_LIMIT_REACHED',{'verified_outcome':False});return None
    token=uuid4()
    result=conn.execute("UPDATE coordinator.sandbox_runs SET state='RUNNING',lease_token=%s,lease_until=%s,updated_at=%s WHERE id=%s RETURNING *",(token,now+timedelta(minutes=3),now,id)).fetchone()
    event(conn,id,'RUN_STARTED',{'checkpoint':row['checkpoint']})
    return result


def renew(conn,id,lease_token,*,now=None):
    """Extend only a live worker lease whose case permission is still current."""
    now=now or datetime.now(timezone.utc);row=get(conn,id,True)
    if (row['state']!='RUNNING' or str(row['lease_token'])!=str(lease_token)
        or not row['lease_until'] or row['lease_until']<=now):return False
    incident=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(row['incident_id'],)).fetchone()
    if not incident or not incident['consent_active'] or incident['consent_version']!=row['consent_version']:
        return False
    conn.execute('UPDATE coordinator.sandbox_runs SET lease_until=%s,updated_at=%s WHERE id=%s',
                 (now+timedelta(minutes=3),now,id))
    return True


def complete_checkpoint(conn,id,lease_token,checkpoint,evidence_references,*,verify):
    row=get(conn,id,True)
    if row['state']!='RUNNING' or str(row['lease_token'])!=str(lease_token) or row['lease_until']<=datetime.now(timezone.utc):
        raise HTTPException(409,'Current running worker lease required')
    checkpoints=row['manifest']['checkpoints']
    if row['checkpoint']>=len(checkpoints) or checkpoint!=checkpoints[row['checkpoint']]:
        raise HTTPException(409,'Checkpoint does not match the next required gate')
    if not isinstance(evidence_references,list) or not evidence_references or len(evidence_references)>30 or not all(isinstance(x,str) and 0<len(x)<=200 for x in evidence_references):
        raise HTTPException(422,'Bounded case evidence references required')
    # verify is trusted code that queries authoritative institution/coordinator
    # state, never an LLM judge verdict or caller-provided boolean.
    if not verify(checkpoint,row['incident_id'],evidence_references):
        raise HTTPException(409,'Independent checkpoint verification failed')
    incident=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(row['incident_id'],)).fetchone()
    if not incident or not incident['consent_active'] or incident['consent_version']!=row['consent_version']:
        raise HTTPException(409,'Investigation consent changed before checkpoint completion')
    cursor=row['checkpoint']+1;state='COMPLETED' if cursor==len(checkpoints) else 'RUNNING'
    result=conn.execute("UPDATE coordinator.sandbox_runs SET checkpoint=%s,state=%s,lease_token=CASE WHEN %s='COMPLETED' THEN NULL ELSE lease_token END,lease_until=CASE WHEN %s='COMPLETED' THEN NULL ELSE lease_until END,updated_at=now() WHERE id=%s RETURNING *",(cursor,state,state,state,id)).fetchone()
    event(conn,id,'CHECKPOINT_VERIFIED',{'checkpoint':checkpoint,'evidence_references':evidence_references,'source':'INDEPENDENT_STATE_VERIFIER'})
    return result


def control(conn,id,operation):
    row=get(conn,id,True);state=row['state'];next_state=None
    if operation=='pause' and state=='RUNNING':next_state='PAUSE_REQUESTED'
    elif operation=='pause' and state=='READY':next_state='PAUSED'
    elif operation=='resume' and state=='PAUSED':next_state='READY'
    elif operation=='cancel' and state in {'RUNNING','PAUSE_REQUESTED'}:next_state='CANCEL_REQUESTED'
    elif operation=='cancel' and state in {'PREPARED','READY','PAUSED'}:next_state='CANCELLED'
    elif operation=='reset':
        fresh=create(conn,language=row['language'],origin=row['origin'])
        event(conn,fresh['id'],'RUN_RESET_FROM',{'previous_run_id':str(id),'previous_run_preserved':True})
        return fresh
    if next_state is None:raise HTTPException(409,'Run control is unavailable in its current state')
    result=conn.execute('UPDATE coordinator.sandbox_runs SET state=%s,updated_at=now() WHERE id=%s RETURNING *',(next_state,id)).fetchone()
    event(conn,id,'RUN_CONTROL',{'operation':operation,'state':next_state,'stopped_confirmed':next_state in {'PAUSED','CANCELLED'}})
    return result


def acknowledge_stop(conn,id,lease_token):
    row=get(conn,id,True)
    if str(row['lease_token'])!=str(lease_token) or row['state'] not in {'PAUSE_REQUESTED','CANCEL_REQUESTED'}:
        raise HTTPException(409,'Current stop request and worker lease required')
    state='PAUSED' if row['state']=='PAUSE_REQUESTED' else 'CANCELLED'
    result=conn.execute('UPDATE coordinator.sandbox_runs SET state=%s,lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s RETURNING *',(state,id)).fetchone()
    event(conn,id,'RUN_STOP_CONFIRMED',{'state':state,'institution_outcome_changed':False})
    return result


def advance_clock(conn,id,seconds):
    row=get(conn,id,True)
    if row['state'] not in {'PREPARED','READY','PAUSED'} or type(seconds) is not int or not 0<seconds<=900:
        raise HTTPException(409,'Advance the synthetic clock only while no worker is running')
    elapsed=row['elapsed_seconds']+seconds
    result=conn.execute('UPDATE coordinator.sandbox_runs SET elapsed_seconds=%s,updated_at=now() WHERE id=%s RETURNING *',(elapsed,id)).fetchone()
    event(conn,id,'SYNTHETIC_CLOCK_ADVANCED',{'seconds':seconds,'elapsed_seconds':elapsed,'institution_receiving_time_rewritten':False})
    return result


def public(row):
    return {'execution_scope':row['manifest'].get('execution_scope','FULL_CASE'),
      'checkpoint_count':len(row['manifest']['checkpoints']),**{k:row[k] for k in ['id','scenario_id','scenario_version','language','state','incident_id',
      'provider_configuration','origin','checkpoint','elapsed_seconds','faults','created_at','updated_at']}}


def mark_uncertain(conn,id,lease_token,reason):
    row=get(conn,id,True)
    # Another trusted boundary may already have withheld the session and
    # cleared the lease. Preserve its evidence and the original worker error.
    if row['state']=='UNCERTAIN' and row['lease_token'] is None:
        return row
    if row['state'] not in {'RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'} or str(row['lease_token'])!=str(lease_token):
        raise HTTPException(409,'Current worker lease required to record an uncertain execution')
    result=conn.execute("UPDATE coordinator.sandbox_runs SET state='UNCERTAIN',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s RETURNING *",(id,)).fetchone()
    event(conn,id,'RUN_EXECUTION_UNCERTAIN',{'reason':reason[:200],'automatic_retry':False})
    return result


def enqueue(conn,id):
    """Use the existing durable jobs table; never enqueue real call work."""
    row=get(conn,id,True)
    if row['state'] not in {'READY','PAUSED'} or not row['incident_id']:
        raise HTTPException(409,'A bound ready or paused synthetic run is required')
    incident=conn.execute('SELECT is_test,consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(row['incident_id'],)).fetchone()
    if not incident or not incident['is_test'] or not incident['consent_active'] or incident['consent_version']!=row['consent_version']:
        raise HTTPException(409,'Current synthetic investigation permission required')
    transport=(row.get('provider_configuration') or {}).get('transport')
    if transport not in {'PIPECAT_STDIO','BOLNA_WEBRTC'}:
        raise HTTPException(409,'The run does not have an approved assistant transport')
    prior=conn.execute("SELECT id,state FROM coordinator.jobs WHERE kind='SANDBOX_PHASE' AND payload->>'run_id'=%s AND state IN ('QUEUED','DISPATCHING','DISPATCH_UNKNOWN') ORDER BY created_at DESC LIMIT 1",(str(id),)).fetchone()
    if prior:return {'job_id':str(prior['id']),'state':prior['state'],'new_job':False}
    job_id=uuid4()
    conn.execute("INSERT INTO coordinator.jobs(id,incident_id,kind,payload) VALUES(%s,%s,'SANDBOX_PHASE',%s)",
                 (job_id,row['incident_id'],Jsonb({'run_id':str(id),'transport':transport})))
    event(conn,id,'RUN_EXECUTION_QUEUED',{'job_id':str(job_id),'transport':transport,'phone_dispatch':False})
    return {'job_id':str(job_id),'state':'QUEUED','new_job':True}


def configure_faults(conn,id,faults):
    from sandbox.scenario_faults import validate_faults
    faults=validate_faults(faults);row=get(conn,id,True)
    if row['state']!='PREPARED' or row['incident_id'] or row['origin']!='USER_PREPARED':
        raise HTTPException(409,'Scenario faults can change only before this case is bound. Prepare a fresh run.')
    if sorted(row['faults'])==faults:return row
    result=conn.execute('UPDATE coordinator.sandbox_runs SET faults=%s,updated_at=now() WHERE id=%s RETURNING *',(Jsonb(faults),id)).fetchone()
    event(conn,id,'SCENARIO_FAULTS_CONFIGURED',{'faults':faults,'case_seeded':False,'provider_request':False})
    return result


def escalate_callback(conn,id,lease_token,callback_id):
    """Stop a leased run after an authoritative callback limit/deadline result."""
    row=get(conn,id,True)
    if row['state']!='RUNNING' or str(row['lease_token'])!=str(lease_token) or not row['lease_until'] or row['lease_until']<=datetime.now(timezone.utc):
        raise HTTPException(409,'Current running lease required for escalation')
    callback=conn.execute('SELECT state,incident_id FROM coordinator.workflow_callbacks WHERE id=%s',(callback_id,)).fetchone()
    if not callback or callback['incident_id']!=row['incident_id'] or callback['state']!='ESCALATED':
        raise HTTPException(409,'Case-bound escalated callback required')
    result=conn.execute("UPDATE coordinator.sandbox_runs SET state='ESCALATED',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s RETURNING *",(id,)).fetchone()
    event(conn,id,'RUN_CALLBACK_ESCALATED',{'callback_id':str(callback_id),'checkpoint':row['checkpoint'],'verified_outcome':False,'automatic_retry':False})
    return result
