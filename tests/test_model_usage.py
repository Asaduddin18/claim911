from sandbox.model_usage import usage_evidence


def test_usage_is_provider_telemetry_not_a_claim_of_verified_billing():
 result={'model':'gpt-5-mini-2025-08-07','usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'prompt_tokens_details':{'cached_tokens':10},'completion_tokens_details':{'reasoning_tokens':12},'secret':'must-not-leak'},'api_key':'must-not-leak'}
 evidence=usage_evidence(result)
 assert evidence['usage']=={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'cached_tokens':10,'reasoning_tokens':12}
 assert evidence['billing_verified'] is False and evidence['reservation_released'] is False
 assert 'must-not-leak' not in str(evidence)


def test_missing_malformed_or_unknown_usage_leaves_reservation_untouched():
 for result in [{}, {'model':'other','usage':{}}, {'model':'gpt-5-mini','usage':{'prompt_tokens':1,'completion_tokens':2,'total_tokens':99}}, {'model':'gpt-5-mini','usage':{'prompt_tokens':True,'completion_tokens':2,'total_tokens':3}}]:
  assert usage_evidence(result) is None


from tests.test_sandbox_spend import ledger

def test_usage_attaches_to_reservation_without_settling_the_charge(ledger):
 from uuid import uuid4
 from sandbox.spend import reserve,settle
 from sandbox.model_usage import store_usage
 conn,now=ledger;request_id=uuid4()
 reserve(conn,request_id=request_id,run_id=uuid4(),phase='integration',operation='reply',maximum_micro=100000,now=now)
 settle(conn,request_id)
 assert store_usage(conn,request_id,{'model':'gpt-5-mini','usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}})
 row=conn.execute('SELECT * FROM coordinator.sandbox_spend WHERE request_id=%s',(request_id,)).fetchone()
 assert row['state']=='UNCERTAIN' and row['charged_micro'] is None and row['reserved_micro']==100000
 assert row['cost_evidence']['usage']['total_tokens']==120


def test_report_usage_cannot_attach_to_another_runs_request(ledger):
 import pytest
 from uuid import uuid4
 from sandbox.spend import reserve
 from sandbox.model_usage import attach_report_usage
 conn,now=ledger;request_id=uuid4();run_id=uuid4()
 reserve(conn,request_id=request_id,run_id=run_id,phase='integration',operation='persona',maximum_micro=100000,now=now)
 call={'request_id':str(request_id),'operation':'persona','model':'gpt-5-mini','usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
 with pytest.raises(ValueError):attach_report_usage(conn,{'scope':'TEXT_PARTICIPANT_ONLY','run_id':str(uuid4()),'model_calls':[call]})
 assert attach_report_usage(conn,{'scope':'TEXT_PARTICIPANT_ONLY','run_id':str(run_id),'model_calls':[call]})==1
