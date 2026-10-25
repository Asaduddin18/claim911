"""Durable investigation callbacks. No phone dispatch or institution verification."""
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from coordinator.reasoning import evaluate,propose

SAFE_ACTIONS={'investigate','collect_document','verify_receipt','verify_query','verify_decision','verify_reconciliation','handoff'}


def aware(value):
    if value is None:return None
    result=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('Timezone required')
    return result


def schedule(conn,snapshot,proposal,due_at):
    decision=evaluate(proposal,snapshot)
    if decision.state!='permitted' or proposal.action not in SAFE_ACTIONS:
        raise HTTPException(409,'Only current policy-approved investigation tasks can be scheduled')
    due_at=aware(due_at)
    if due_at is None:raise HTTPException(422,'Callback time required')
    # Serialize scheduling with consent/revocation and other callers on this case.
    row=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s FOR UPDATE',(proposal.incident_id,)).fetchone()
    if not row or not row['consent_active'] or row['consent_version']!=proposal.consent_version:
        raise HTTPException(409,'Investigation consent changed before scheduling')
    query=(snapshot.get('complex_workflow') or {}).get('query',{})
    task_key=proposal.purpose+':'+proposal.expected_checkpoint
    existing=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE incident_id=%s AND task_key=%s',(proposal.incident_id,task_key)).fetchone()
    if existing:return existing
    return conn.execute('''INSERT INTO coordinator.workflow_callbacks
        (id,incident_id,task_key,purpose,proposal,consent_version,original_received_at,target_at,available_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
        (uuid4(),proposal.incident_id,task_key,proposal.purpose,Jsonb(proposal.model_dump(mode='json')),
         proposal.consent_version,aware(query.get('received_at')),aware(query.get('target_at')),due_at)).fetchone()


def claim(conn,snapshot,now=None):
    """Commit returned lease before invoking a transport. Snapshot must be fresh.

    The caller holds the incident lock while loading the snapshot. No executor
    may treat this task lease as authorization for protected tool writes.
    """
    now=aware(now) or datetime.now(timezone.utc);incident=snapshot['incident'];id=incident['id']
    current=conn.execute('SELECT consent_active,consent_version,state FROM coordinator.incidents WHERE id=%s FOR UPDATE',(id,)).fetchone()
    if not current:raise HTTPException(404,'Case not found')
    if not current['consent_active'] or current['consent_version']!=incident['consent_version'] or current['state'] in {'HUMAN_REVIEW','PAUSED_REVOKED'}:
        conn.execute("UPDATE coordinator.workflow_callbacks SET state='CANCELLED',lease_token=NULL,lease_until=NULL,updated_at=%s WHERE incident_id=%s AND state IN ('WAITING','RUNNING')",(now,id))
        return None
    # A lost worker might already have acted. Never reclaim its operation blindly.
    conn.execute("UPDATE coordinator.workflow_callbacks SET state='UNCERTAIN',lease_token=NULL,lease_until=NULL,updated_at=%s WHERE incident_id=%s AND state='RUNNING' AND lease_until<=%s",(now,id,now))
    conn.execute("UPDATE coordinator.workflow_callbacks SET state='ESCALATED',updated_at=%s WHERE incident_id=%s AND state='WAITING' AND target_at IS NOT NULL AND target_at<=%s",(now,id,now))
    tasks=conn.execute("SELECT * FROM coordinator.workflow_callbacks WHERE incident_id=%s AND state='WAITING' AND available_at<=%s ORDER BY available_at,id FOR UPDATE SKIP LOCKED",(id,now)).fetchall()
    candidates={p.purpose:p for p in propose(snapshot)}
    for task in tasks:
        if task['consent_version']!=current['consent_version']:
            conn.execute("UPDATE coordinator.workflow_callbacks SET state='CANCELLED',updated_at=%s WHERE id=%s",(now,task['id']));continue
        candidate=candidates.get(task['purpose'])
        if not candidate or evaluate(candidate,snapshot).state!='permitted' or candidate.action not in SAFE_ACTIONS:
            conn.execute("UPDATE coordinator.workflow_callbacks SET state='SUPERSEDED',updated_at=%s WHERE id=%s",(now,task['id']));continue
        if task['attempts']>=2:
            conn.execute("UPDATE coordinator.workflow_callbacks SET state='ESCALATED',updated_at=%s WHERE id=%s",(now,task['id']));continue
        return conn.execute("""UPDATE coordinator.workflow_callbacks SET state='RUNNING',attempts=attempts+1,
            lease_token=%s,lease_until=%s,proposal=%s,updated_at=%s WHERE id=%s RETURNING *""",
            (uuid4(),now+timedelta(minutes=2),Jsonb(candidate.model_dump(mode='json')),now,task['id'])).fetchone()
    return None


def finish(conn,id,lease_token,outcome,summary,next_at=None,now=None):
    if outcome not in {'reported','failed','uncertain'}:
        raise HTTPException(422,'Callback reports cannot verify institution outcomes')
    now=aware(now) or datetime.now(timezone.utc)
    row=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s FOR UPDATE',(id,)).fetchone()
    if not row or row['state']!='RUNNING' or str(row['lease_token'])!=str(lease_token):
        raise HTTPException(409,'Callback lease is no longer current')
    incident=conn.execute('SELECT consent_active,consent_version,state FROM coordinator.incidents WHERE id=%s',(row['incident_id'],)).fetchone()
    if not incident['consent_active'] or incident['consent_version']!=row['consent_version'] or incident['state'] in {'HUMAN_REVIEW','PAUSED_REVOKED'}:
        state='CANCELLED'
    elif now>=row['lease_until']:state='UNCERTAIN'
    elif outcome=='uncertain':state='UNCERTAIN'
    elif outcome=='reported':state='REPORTED'
    elif row['attempts']>=2:state='ESCALATED'
    else:state='WAITING'
    retry=aware(next_at) if next_at else now+timedelta(minutes=5)
    if state=='WAITING' and retry<=now:raise HTTPException(422,'Retry must be in the future')
    return conn.execute('''UPDATE coordinator.workflow_callbacks SET state=%s,result=%s,available_at=%s,
        lease_token=NULL,lease_until=NULL,updated_at=%s WHERE id=%s RETURNING *''',
        (state,Jsonb({'outcome':outcome,'summary':summary[:1000],'verified_state_changed':False}),retry,now,id)).fetchone()


def reconcile(conn,id,resolution,now=None):
    """Human reconciliation after independently inspecting provider/institution state."""
    if resolution not in {'CONFIRMED_NO_EXECUTION','CONFIRMED_REPORTED','ESCALATE'}:
        raise HTTPException(422,'Explicit reconciliation outcome required')
    now=aware(now) or datetime.now(timezone.utc)
    row=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s FOR UPDATE',(id,)).fetchone()
    if not row or row['state']!='UNCERTAIN':raise HTTPException(409,'Only uncertain callbacks require reconciliation')
    state='REPORTED' if resolution=='CONFIRMED_REPORTED' else 'WAITING' if resolution=='CONFIRMED_NO_EXECUTION' and row['attempts']<2 else 'ESCALATED'
    return conn.execute('UPDATE coordinator.workflow_callbacks SET state=%s,available_at=%s,updated_at=%s WHERE id=%s RETURNING *',(state,now,now,id)).fetchone()


def cancel_waiting(conn,incident_id,task_id,now=None):
    """Cancel queued work only. Never claim that an active call was stopped."""
    now=aware(now) or datetime.now(timezone.utc)
    incident=conn.execute('SELECT id FROM coordinator.incidents WHERE id=%s FOR UPDATE',(incident_id,)).fetchone()
    if not incident:raise HTTPException(404,'Case not found')
    row=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s AND incident_id=%s FOR UPDATE',(task_id,incident_id)).fetchone()
    if not row:raise HTTPException(404,'Follow-up not found in this case')
    if row['state']=='CANCELLED':return row
    if row['state']!='WAITING':raise HTTPException(409,'Only waiting follow-ups can be cancelled here. Active or uncertain execution needs reconciliation.')
    result=conn.execute("""UPDATE coordinator.workflow_callbacks SET state='CANCELLED',
        lease_token=NULL,lease_until=NULL,updated_at=%s WHERE id=%s RETURNING *""",(now,task_id)).fetchone()
    conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',
                 (incident_id,'FOLLOWUP_CANCELLED',Jsonb({'callback_id':str(task_id),'previous_state':'WAITING','recorded_by':'AUTHENTICATED_CONTROLLER'})))
    return result


def reschedule_after_review(conn,snapshot,task_id,reason,now=None):
    """Explicit operator recovery, preserving the exhausted task and its attempts."""
    if not isinstance(reason,str) or not 20<=len(reason.strip())<=1000:
        raise HTTPException(422,'A concrete review reason is required')
    now=aware(now) or datetime.now(timezone.utc);incident=snapshot['incident']
    conn.execute('SELECT id FROM coordinator.incidents WHERE id=%s FOR UPDATE',(incident['id'],)).fetchone()
    task=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s AND incident_id=%s FOR UPDATE',(task_id,incident['id'])).fetchone()
    if not task or task['state'] not in {'ESCALATED','UNCERTAIN'}:
        raise HTTPException(409,'Only reviewed escalated or uncertain work can be rescheduled')
    if conn.execute("SELECT 1 FROM coordinator.calls WHERE incident_id=%s AND state NOT IN ('COMPLETED','FAILED','CANCELLED','BUSY','NO_ANSWER') LIMIT 1",(incident['id'],)).fetchone():
        raise HTTPException(409,'Reconcile active conversations before scheduling reviewed work')
    proposal=next((p for p in propose(snapshot) if p.purpose==task['purpose']),None)
    if not proposal or evaluate(proposal,snapshot).state!='permitted':
        raise HTTPException(409,'Current policy must permit the reviewed follow-up')
    conn.execute("UPDATE coordinator.workflow_callbacks SET state='SUPERSEDED',task_key=task_key||':reviewed:'||id::text,lease_token=NULL,lease_until=NULL,updated_at=%s WHERE id=%s",(now,task_id))
    replacement=schedule(conn,snapshot,proposal,now)
    conn.execute('INSERT INTO coordinator.events(incident_id,type,payload) VALUES(%s,%s,%s)',
        (incident['id'],'FOLLOWUP_RESCHEDULED_AFTER_REVIEW',Jsonb({'previous_callback_id':str(task_id),'callback_id':str(replacement['id']),'previous_attempts':task['attempts'],'reason':reason.strip(),'verified_state_changed':False})))
    return replacement
