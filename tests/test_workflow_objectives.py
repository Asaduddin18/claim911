"""Offline scope regression from an observed hosted-agent desk mix-up."""
from coordinator.workflow_calls import prepare_context


def fixture():
    row={'case_id':'SYNTHETIC-CASE','patient_id':'DEMO-PATIENT-84','reference':'FIN63',
         'consent_active':True,'consent_version':1}
    w={'query':{'admission_id':'ADM42','references':{'query':'QRY25','claim':'CLM86'}},
       'documents':{'itemized_bill':{},'signed_discharge_summary':{},'implant_invoice':{}},'approval':None,
       'reports':[{'purpose':'BILLING_DOCUMENT','details':{'summary':'Revised bill ready'}},
                  {'purpose':'RECORDS_DOCUMENT','details':{'summary':'Summary awaiting signature'}}],
       'decision':{'envelope':{'outcome':'AUTHORIZED'}},'clearance':{'envelope':{'refund_due_inr':12000}}}
    return row,w


def test_billing_document_scope_excludes_other_desk_tasks():
    row,w=fixture();context=prepare_context(row,w,'BILLING_DOCUMENT')
    assert context['workflow']['assigned_document_kind']=='itemized_bill'
    assert context['workflow']['collected_document_kinds']==['itemized_bill']
    assert [r['purpose'] for r in context['workflow']['reported_updates']]==['BILLING_DOCUMENT']
    assert 'discharge_summary' not in context['objective']
    assert 'implant_invoice' not in context['objective']
    assert context['workflow']['decision'] is None
    assert context['workflow']['clearance'] is None


def test_records_scope_preserves_its_signature_requirement():
    row,w=fixture();context=prepare_context(row,w,'RECORDS_DOCUMENT')
    assert context['workflow']['assigned_document_kind']=='signed_discharge_summary'
    assert 'treating team signature' in context['objective']
    assert context['workflow']['collected_document_kinds']==['signed_discharge_summary']
    assert 'itemized_bill' not in context['objective']
    assert 'implant_invoice' not in context['objective']


def test_caregiver_intake_answers_the_reported_blocker_without_language_detour():
    row,_=fixture();context=prepare_context(row,None,'CAREGIVER_INTAKE')
    objective=context['objective'].casefold()
    assert 'speak english' in objective
    assert 'permission is already active' in objective
    assert 'confirmation or correction' in objective
    assert 'before calling claim911_report_update' in objective
    assert 'do not ask another intake question' in objective
    assert 'request references or documents' in objective
    assert 'complete final utterance' in objective
    assert "thanks, that's all i need for this call." in objective
    assert 'preferred language' not in objective


def test_claims_followup_requests_institution_resolution_before_reporting_completion():
    row,w=fixture();w['receipt']={'synthetic':True}
    context=prepare_context(row,w,'TPA_QUERY_FOLLOWUP')
    assert 'resolve the query and link the existing enhancement' in context['objective']
    assert 'actual result before recording' in context['objective']
    assert 'backend signature verification is required' in context['objective']
