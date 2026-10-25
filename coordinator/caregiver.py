"""Caregiver explanation derived only from checked workflow checkpoints."""


def caregiver_summary(row,w):
    result={'synthetic':True,'statements':[],'pending':[],'refund_payment_verified':False,
            'insurance_decision_made_by_agent':False}
    if not row['consent_active']:
        result['pending']=['Coordination is on hold because investigation permission is inactive.']
        return result
    def add(text,kind,identifier,issuer):
        result['statements'].append({'text':text,'source':{'kind':kind,'id':identifier,'issuer':issuer}})
    q=w['query']
    add('The claims desk reported an information request. Hospital documents and claims receipt are checked separately.',
        'conversation',w['query_call_id'],w.get('source_mode','UNKNOWN'))
    for kind in q['required_documents']:
        if kind not in w['documents']:
            result['pending'].append('Still needed: '+kind.replace('_',' ')+'.')
    if not w.get('receipt'):
        result['pending'].append('The receiving claims desk has not yet independently confirmed the exact response packet.')
    else:
        e=w['receipt']['envelope']
        add('The receiving claims desk confirmed the exact response packet. This receipt is separate from insurance approval.',
            'receipt',e['receipt_id'],e['source'])
    if w.get('query_resolution'):
        e=w['query_resolution']['envelope']
        add('The TPA confirmed that its information request is answered and the enhancement is linked.',
            'query_resolution',e['event_id'],e['source'])
    elif w.get('receipt'):
        result['pending'].append('TPA confirmation of query completion and enhancement linkage is still needed.')
    if w.get('decision'):
        e=w['decision']['envelope']
        outcome='authorized' if e['outcome']=='AUTHORIZED' else 'denied'
        add(f'The synthetic insurer {outcome} this request with a payable amount of INR {e["payable_inr"]:,}. Reason: {e["reason"]}',
            'insurer_decision',e['id'],e['source'])
    else:
        result['pending'].append('No final insurer decision has been independently verified.')
    if w.get('clearance'):
        e=w['clearance']['envelope']
        status='issued administrative discharge clearance' if e['discharge_clearance']=='ISSUED' else 'reported a remaining patient balance'
        add(f'The hospital {status}. Final bill INR {e["bill_inr"]:,}; patient share INR {e["patient_payable_inr"]:,}; deposit INR {e["deposit_inr"]:,}; balance due INR {e["balance_due_inr"]:,}; refund due INR {e["refund_due_inr"]:,}.',
            'hospital_reconciliation',e['decision_id'],e['source'])
        result['pending'].append('Refund payment has not been verified. A refund due is not proof of payment.')
    elif w.get('decision'):
        result['pending'].append('The hospital still needs to reconcile the final bill, insurer decision and deposit.')
    return result
