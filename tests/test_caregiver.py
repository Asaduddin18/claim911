"""Caregiver summaries never infer a later gate from an earlier one."""
from coordinator.caregiver import caregiver_summary


def fixture():
    return {'consent_active':True},{'query':{'required_documents':['itemized_bill']},'query_call_id':'call-1',
        'source_mode':'BOLNA_TEXT_SIMULATOR','documents':{},'reports':[{'details':{'summary':'Insurer approved and refund paid'}}]}


def test_spoken_approval_and_payment_do_not_become_verified_caregiver_claims():
    row,w=fixture();s=caregiver_summary(row,w)
    assert len(s['statements'])==1 and s['statements'][0]['source']['id']=='call-1'
    assert any('No final insurer decision' in x for x in s['pending'])
    assert any('Still needed' in x for x in s['pending'])
    assert not s['refund_payment_verified'] and not s['insurance_decision_made_by_agent']
    w['receipt']={'envelope':{'receipt_id':'receipt-1','source':'demo-tpa-complex'}}
    s=caregiver_summary(row,w)
    assert len(s['statements'])==2
    assert any('separate from insurance approval' in x['text'] for x in s['statements'])
    assert any('enhancement linkage' in x for x in s['pending'])


def test_denial_and_unpaid_refund_are_preserved_with_institution_sources():
    row,w=fixture();w['decision']={'envelope':{'id':'decision-1','source':'demo-insurer-complex',
        'outcome':'DENIED','payable_inr':0,'reason':'Synthetic exclusion fixture'}}
    s=caregiver_summary(row,w)
    assert any('denied' in x['text'] and x['source']['id']=='decision-1' for x in s['statements'])
    assert any('still needs to reconcile' in x for x in s['pending'])
    w['clearance']={'envelope':{'decision_id':'decision-1','source':'demo-hospital-billing',
        'discharge_clearance':'BALANCE_PENDING','bill_inr':248000,'patient_payable_inr':248000,
        'deposit_inr':30000,'balance_due_inr':218000,'refund_due_inr':0}}
    s=caregiver_summary(row,w)
    assert any('remaining patient balance' in x['text'] and '218,000' in x['text'] for x in s['statements'])
    assert any('payment has not been verified' in x for x in s['pending'])
    row['consent_active']=False
    s=caregiver_summary(row,w)
    assert not s['statements'] and 'on hold' in s['pending'][0]
