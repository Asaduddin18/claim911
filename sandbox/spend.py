"""Atomic credit reservations for synthetic provider requests, in sandbox storage."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from uuid import UUID
from fastapi import HTTPException

PHASE_LIMITS={'integration':10_000_000,'development':60_000_000,'rehearsal':20_000_000,'reserve':10_000_000}
OPERATIONS={'reply','transcribe','synthesize','judge','persona','bolna-participant-reply',
            'bolna-participant-transcribe','bolna-participant-synthesize','bolna-institution-participant'}


def microdollars(value):
    amount=Decimal(str(value))
    if not amount.is_finite() or amount<0:raise ValueError('Non-negative USD amount required')
    return int(amount*1_000_000)


def initialize(conn,*,environment,remaining_credit_usd,checked_at):
    if environment!='sandbox':raise ValueError('Synthetic provider ledger requires sandbox storage')
    if checked_at.tzinfo is None:raise ValueError('Credit verification timestamp requires timezone')
    conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_budget (
      id integer PRIMARY KEY CHECK(id=1),credit_micro bigint NOT NULL,
      credit_checked_at timestamptz NOT NULL,ceiling_micro bigint NOT NULL CHECK(ceiling_micro<=100000000),
      suspended boolean NOT NULL DEFAULT false)''')
    conn.execute('ALTER TABLE coordinator.sandbox_budget ADD COLUMN IF NOT EXISTS suspended boolean NOT NULL DEFAULT false')
    conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_spend (
      request_id uuid PRIMARY KEY,run_id uuid NOT NULL,phase text NOT NULL,operation text NOT NULL,
      reserved_micro bigint NOT NULL CHECK(reserved_micro>0),charged_micro bigint,
      state text NOT NULL DEFAULT 'RESERVED',created_at timestamptz NOT NULL DEFAULT now(),
      CHECK(charged_micro IS NULL OR charged_micro>=0))''')
    conn.execute('ALTER TABLE coordinator.sandbox_spend ADD COLUMN IF NOT EXISTS cost_evidence jsonb')
    conn.execute('''INSERT INTO coordinator.sandbox_budget(id,credit_micro,credit_checked_at,ceiling_micro) VALUES(1,%s,%s,100000000)
      ON CONFLICT(id) DO UPDATE SET credit_micro=excluded.credit_micro,credit_checked_at=excluded.credit_checked_at''',
      (microdollars(remaining_credit_usd),checked_at))


def reserve(conn,*,request_id,run_id,phase,operation,maximum_micro,now=None):
    if phase not in PHASE_LIMITS or operation not in OPERATIONS:
        raise HTTPException(422,'Unknown synthetic provider cost category')
    if type(maximum_micro) is not int or not 0<maximum_micro<=1_000_000:
        raise HTTPException(422,'Each provider request requires a bounded reservation of at most USD 1')
    now=now or datetime.now(timezone.utc)
    budget=conn.execute('SELECT * FROM coordinator.sandbox_budget WHERE id=1 FOR UPDATE').fetchone()
    if budget and budget['suspended']:raise HTTPException(503,'Provider cost reconciliation required before more paid requests')
    if not budget or now-budget['credit_checked_at']>timedelta(hours=24) or now<budget['credit_checked_at']:
        raise HTTPException(503,'Credit verification must be refreshed before paid runs')
    request_id=UUID(str(request_id));run_id=UUID(str(run_id))
    previous=conn.execute('SELECT * FROM coordinator.sandbox_spend WHERE request_id=%s',(request_id,)).fetchone()
    if previous:
        if (previous['run_id'],previous['phase'],previous['operation'],previous['reserved_micro'])!=(run_id,phase,operation,maximum_micro):
            raise HTTPException(409,'Cost request identifier reused with a different operation')
        # Never use a duplicate reservation as permission for a duplicate request.
        return {'new_reservation':False,'record':previous}
    rows=conn.execute('''SELECT phase,sum(CASE WHEN state='CONFIRMED' THEN charged_micro ELSE reserved_micro END) AS held
       FROM coordinator.sandbox_spend GROUP BY phase''').fetchall()
    total=sum(r['held'] for r in rows);phase_held=sum(r['held'] for r in rows if r['phase']==phase)
    ceiling=min(budget['ceiling_micro'],budget['credit_micro']-10_000_000)
    if total+maximum_micro>ceiling or phase_held+maximum_micro>PHASE_LIMITS[phase]:
        raise HTTPException(429,'Synthetic provider spend limit reached; no paid fallback allowed')
    record=conn.execute('''INSERT INTO coordinator.sandbox_spend(request_id,run_id,phase,operation,reserved_micro)
      VALUES(%s,%s,%s,%s,%s) RETURNING *''',(request_id,run_id,phase,operation,maximum_micro)).fetchone()
    return {'new_reservation':True,'record':record}


def settle(conn,request_id,*,confirmed_charge_micro=None):
    # Serialize with reservations, so a concurrent caller cannot ignore a charge.
    conn.execute('SELECT id FROM coordinator.sandbox_budget WHERE id=1 FOR UPDATE')
    row=conn.execute('SELECT * FROM coordinator.sandbox_spend WHERE request_id=%s FOR UPDATE',(request_id,)).fetchone()
    if not row:raise HTTPException(404,'Cost reservation not found')
    if row['state']=='CONFIRMED':
        if confirmed_charge_micro!=row['charged_micro']:raise HTTPException(409,'Confirmed cost cannot be rewritten')
        return row
    if confirmed_charge_micro is None:
        return conn.execute("UPDATE coordinator.sandbox_spend SET state='UNCERTAIN' WHERE request_id=%s RETURNING *",(request_id,)).fetchone()
    if type(confirmed_charge_micro) is not int or confirmed_charge_micro<0:
        raise HTTPException(422,'Non-negative provider charge required')
    if confirmed_charge_micro>row['reserved_micro']:
        # Persist the hold rather than raise and accidentally roll it back.
        conn.execute('UPDATE coordinator.sandbox_budget SET suspended=true WHERE id=1')
        return conn.execute("UPDATE coordinator.sandbox_spend SET state='OVER_BOUND',charged_micro=%s WHERE request_id=%s RETURNING *",(confirmed_charge_micro,request_id)).fetchone()
    return conn.execute("UPDATE coordinator.sandbox_spend SET state='CONFIRMED',charged_micro=%s WHERE request_id=%s RETURNING *",(confirmed_charge_micro,request_id)).fetchone()


def testing_readiness(conn,now=None):
    """Read-only admission hint; each later request still needs reserve()."""
    now=now or datetime.now(timezone.utc)
    exists=conn.execute("SELECT to_regclass('coordinator.sandbox_budget') AS name").fetchone()
    budget=conn.execute('SELECT suspended,credit_checked_at FROM coordinator.sandbox_budget WHERE id=1').fetchone() if exists and exists['name'] else None
    if not budget:return {'allowed':False,'code':'BUDGET_NOT_CONFIGURED','message':'Provider testing is unavailable until its budget is configured. Saved runs remain inspectable.'}
    if budget['suspended']:return {'allowed':False,'code':'PAID_TESTING_PAUSED','message':'Paid testing is paused. Saved runs remain inspectable; no new voice session will start.'}
    if not timedelta(0)<=now-budget['credit_checked_at']<=timedelta(hours=24):
        return {'allowed':False,'code':'CREDIT_CHECK_REQUIRED','message':'The daily credit check is due before provider testing can resume.'}
    return {'allowed':True,'code':'READY','message':'Provider testing remains subject to per-request budget and evidence checks.'}


def require_testing(conn):
    status=testing_readiness(conn)
    if not status['allowed']:raise HTTPException(503,status['message'])
    return status
