from sandbox.cost_report import summarize
from sandbox.model_usage import usage_evidence


def row(state='UNCERTAIN',charge=None,operation='persona',evidence=None):
 return {'phase':'development','operation':operation,'state':state,'reserved_micro':100000,'charged_micro':charge,'cost_evidence':evidence}


def test_reservations_are_not_reported_as_billed_spend_or_released():
 report=summarize({'suspended':True},[row(),row('CONFIRMED',0,'bolna-participant-synthesize')])
 assert report['recorded_confirmed_charges_usd']=='0.000000'
 assert report['unreconciled_reservation_holds_usd']=='0.100000'
 assert report['amount_counted_by_current_budget_ledger_usd']=='0.100000'
 assert report['billing_reconciled'] is False and report['reservations_released'] is False
 assert report['bolna_account_spend_included'] is False and report['paid_testing_suspended'] is True
 assert report['model_requests_without_valid_token_usage']==1


def test_token_subsets_are_not_double_counted_and_invalid_usage_is_not_accepted():
 evidence=usage_evidence({'model':'gpt-5-mini','usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150,
     'prompt_tokens_details':{'cached_tokens':20},'completion_tokens_details':{'reasoning_tokens':30}}})
 invalid={'source':'PROVIDER_RESPONSE_TOKEN_USAGE','model':'gpt-5-mini','usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':99}}
 report=summarize({'suspended':True},[row(evidence=evidence),row(evidence=invalid)])
 usage=report['token_usage_by_model']['gpt-5-mini']
 assert usage['total_tokens']==150 and usage['cached_prompt_tokens_observed']==20
 assert usage['reasoning_completion_tokens_observed']==30 and usage['requests']==1
 assert report['model_requests_without_valid_token_usage']==1


def test_recorded_charges_and_unknown_holds_remain_separate():
 report=summarize({'suspended':True},[row('CONFIRMED',1200),row('RESERVED')])
 assert report['recorded_confirmed_charges_usd']=='0.001200'
 assert report['unreconciled_reservation_holds_usd']=='0.100000'
 assert report['amount_counted_by_current_budget_ledger_usd']=='0.101200'
