import json,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
import pytest
from sandbox.spend import initialize,reserve,settle


@pytest.fixture
def ledger():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Sandbox storage required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text())
 # Private temporary tables isolate both balances and writes from the actual
 # sandbox ledger. Rollback alone still reads its existing held reservations.
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  conn.execute('CREATE TEMP TABLE sandbox_budget (LIKE coordinator.sandbox_budget INCLUDING ALL)')
  conn.execute('CREATE TEMP TABLE sandbox_spend (LIKE coordinator.sandbox_spend INCLUDING ALL)')
  class IsolatedLedger:
   def execute(self,sql,*args,**kwargs):
    for table in ('sandbox_budget','sandbox_spend'):
     sql=sql.replace('coordinator.'+table,'pg_temp.'+table)
    return conn.execute(sql,*args,**kwargs)
  isolated=IsolatedLedger()
  now=datetime.now(timezone.utc)
  initialize(isolated,environment='sandbox',remaining_credit_usd=132.5,checked_at=now)
  yield isolated,now
  conn.rollback()


def request(conn,phase='integration',**kw):
 return reserve(conn,request_id=kw.pop('request_id',uuid4()),run_id=kw.pop('run_id',uuid4()),phase=phase,operation='reply',maximum_micro=kw.pop('maximum_micro',1_000_000),**kw)


def test_reservation_prevents_duplicate_paid_execution_and_holds_unknown_cost(ledger):
 conn,now=ledger;rid=uuid4();run=uuid4()
 a=request(conn,request_id=rid,run_id=run,now=now)
 assert a['new_reservation']
 assert not request(conn,request_id=rid,run_id=run,now=now)['new_reservation']
 assert settle(conn,rid)['state']=='UNCERTAIN'
 assert not request(conn,request_id=rid,run_id=run,now=now)['new_reservation']
 assert settle(conn,rid,confirmed_charge_micro=100)['state']=='CONFIRMED'
 with pytest.raises(HTTPException):settle(conn,rid,confirmed_charge_micro=0)


def test_phase_budget_and_credit_freshness_block_fallback(ledger):
 conn,now=ledger
 held=conn.execute("SELECT coalesce(sum(CASE WHEN state='CONFIRMED' THEN charged_micro ELSE reserved_micro END),0) AS held FROM coordinator.sandbox_spend WHERE phase='integration'").fetchone()['held']
 remaining=10_000_000-int(held)
 while remaining>0:
  amount=min(1_000_000,remaining);request(conn,now=now,maximum_micro=amount);remaining-=amount
 with pytest.raises(HTTPException) as limit:request(conn,now=now)
 assert limit.value.status_code==429
 assert request(conn,phase='development',now=now+timedelta(hours=23))['new_reservation']
 with pytest.raises(HTTPException) as stale:request(conn,phase='development',now=now+timedelta(hours=25))
 assert stale.value.status_code==503


def test_low_credit_retains_reserve_and_operational_initialization_is_rejected(ledger):
 conn,now=ledger
 initialize(conn,environment='sandbox',remaining_credit_usd=10.5,checked_at=now)
 with pytest.raises(HTTPException):request(conn,now=now)
 with pytest.raises(ValueError):initialize(conn,environment='operational',remaining_credit_usd=100,checked_at=now)


def test_charge_exceeding_bound_suspends_all_future_requests(ledger):
 conn,now=ledger;rid=uuid4()
 request(conn,request_id=rid,now=now,maximum_micro=100)
 assert settle(conn,rid,confirmed_charge_micro=101)['state']=='OVER_BOUND'
 with pytest.raises(HTTPException) as stopped:request(conn,now=now)
 assert stopped.value.status_code==503
 initialize(conn,environment='sandbox',remaining_credit_usd=132.5,checked_at=now)
 with pytest.raises(HTTPException):request(conn,now=now)


@pytest.mark.parametrize('operation',[
 'bolna-participant-transcribe','bolna-participant-reply','bolna-participant-synthesize',
 'bolna-institution-participant'])
def test_bolna_participant_operations_use_the_same_bounded_ledger(ledger,operation):
 conn,now=ledger
 result=reserve(conn,request_id=uuid4(),run_id=uuid4(),phase='development',operation=operation,
                maximum_micro=100_000,now=now)
 assert result['new_reservation']


def test_paid_admission_exposes_suspension_and_daily_check_without_mutating(ledger):
 from sandbox.spend import testing_readiness,require_testing
 conn,now=ledger
 assert testing_readiness(conn,now)['allowed'] is True
 assert testing_readiness(conn,now+timedelta(hours=25))['code']=='CREDIT_CHECK_REQUIRED'
 conn.execute('UPDATE coordinator.sandbox_budget SET suspended=true WHERE id=1')
 assert testing_readiness(conn,now)['code']=='PAID_TESTING_PAUSED'
 with pytest.raises(HTTPException):require_testing(conn)
 assert conn.execute('SELECT suspended FROM coordinator.sandbox_budget WHERE id=1').fetchone()['suspended'] is True
