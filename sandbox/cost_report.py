"""Read-only ledger summary. Reservations and token counts are not invoices."""
from collections import Counter
from decimal import Decimal
from sandbox.model_usage import usage_evidence


def usd(micro):return str((Decimal(micro)/Decimal(1_000_000)).quantize(Decimal('0.000001')))


def summarize(budget,rows):
    groups={};states=Counter();token_totals={};missing_usage=0
    for row in rows:
        state=row['state'];states[state]+=1
        group=groups.setdefault((row['phase'],row['operation']),{'requests':0,'reservation_micro':0,
            'recorded_confirmed_micro':0,'unreconciled_hold_micro':0,'usage_requests':0})
        group['requests']+=1;group['reservation_micro']+=row['reserved_micro']
        if state=='CONFIRMED':group['recorded_confirmed_micro']+=row['charged_micro'] or 0
        else:group['unreconciled_hold_micro']+=row['reserved_micro']
        evidence=row.get('cost_evidence')
        evidence=evidence if isinstance(evidence,dict) else {}
        counts=evidence.get('usage');counts=counts if isinstance(counts,dict) else {}
        raw_usage={**counts,'prompt_tokens_details':{'cached_tokens':counts.get('cached_tokens')},
                   'completion_tokens_details':{'reasoning_tokens':counts.get('reasoning_tokens')}}
        valid=usage_evidence({'model':evidence.get('model'),'usage':raw_usage}) if evidence.get('source')=='PROVIDER_RESPONSE_TOKEN_USAGE' else None
        if valid:
            group['usage_requests']+=1
            model=valid['model'];counts=valid['usage']
            target=token_totals.setdefault(model,{'requests':0,'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,
                'cached_prompt_tokens_observed':0,'reasoning_completion_tokens_observed':0})
            target['requests']+=1
            for key in ('prompt_tokens','completion_tokens','total_tokens'):target[key]+=counts[key]
            target['cached_prompt_tokens_observed']+=counts.get('cached_tokens',0)
            target['reasoning_completion_tokens_observed']+=counts.get('reasoning_tokens',0)
        elif row['operation'] in {'reply','persona','judge','bolna-participant-reply','bolna-institution-participant'}:
            missing_usage+=1
    operations=[]
    for (phase,operation),group in sorted(groups.items()):
        operations.append({'phase':phase,'operation':operation,'requests':group['requests'],
            'original_reservations_usd':usd(group['reservation_micro']),
            'recorded_confirmed_charges_usd':usd(group['recorded_confirmed_micro']),
            'unreconciled_holds_usd':usd(group['unreconciled_hold_micro']),
            'requests_with_valid_token_usage':group['usage_requests']})
    confirmed=sum(g['recorded_confirmed_micro'] for g in groups.values())
    holds=sum(g['unreconciled_hold_micro'] for g in groups.values())
    return {'scope':'READ_ONLY_SANDBOX_LEDGER_SUMMARY','provider_requests':0,'ledger_writes':0,
        'paid_testing_suspended':budget['suspended'],'requests':sum(states.values()),'states':dict(sorted(states.items())),
        'recorded_confirmed_charges_usd':usd(confirmed),'unreconciled_reservation_holds_usd':usd(holds),
        'amount_counted_by_current_budget_ledger_usd':usd(confirmed+holds),
        'token_usage_by_model':token_totals,'model_requests_without_valid_token_usage':missing_usage,
        'operations':operations,'billing_reconciled':False,'reservations_released':False,
        'bolna_account_spend_included':False,'current_provider_credit_balances_verified':False,
        'limitations':[
            'Reservation holds are maximum budgets, not actual provider charges.',
            'Recorded confirmed charges describe the local ledger, not an independent invoice audit.',
            'Observed token usage covers only requests with valid saved provider telemetry.',
            'Cached prompt and reasoning counts are subsets, not extra tokens to add to total_tokens.',
            'Bolna account charges and balances require separate provider evidence.',
            'No prices are inferred and no monetary reservation is released by this report.']}
