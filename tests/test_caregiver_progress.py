from copy import deepcopy
from uuid import uuid4
import pytest
from experience.presentation import caregiver_progress


def snapshot():
 return {'incident':{'id':str(uuid4()),'state':'INVESTIGATING','reference':'UNCONFIRMED_FINAL_REFERENCE','consent_active':True,'consent_version':1},'documents':[],'events':[],'calls':[],'complex_workflow':None}


def test_progress_tracks_all_post_document_gates_without_claiming_execution():
 s=snapshot();w={'tasks':[],'approval_current':False};s['complex_workflow']=w
 assert 'approval is needed' in caregiver_progress(s)['status']
 w['approval_current']=True
 assert 'ready for hospital submission' in caregiver_progress(s)['status']
 w['reports']=[{'purpose':'PACKET_SUBMISSION','details':{'dispatch_reference':'SYN-DISPATCH'}}]
 assert 'receipt is still unconfirmed' in caregiver_progress(s)['status']
 w['receipt']={'verified':True}
 assert 'received your response' in caregiver_progress(s)['status']
 assert 'linkage still need confirmation' in caregiver_progress(s)['next_action']
 w['query_resolution']={'verified':True}
 assert 'decision is still pending verification' in caregiver_progress(s)['status']
 w['decision']={'verified':True}
 assert 'billing still needs to reconcile' in caregiver_progress(s)['next_action']


@pytest.mark.parametrize('kind,owner,expected',[
 ('itemized_bill','billing','corrected bill'),('signed_discharge_summary','medical_records','signed discharge summary'),('implant_invoice','implant_store','implant invoice')])
def test_missing_document_has_named_owner_and_no_false_background_work(kind,owner,expected):
 s=snapshot();s['complex_workflow']={'tasks':[{'kind':kind,'owner':owner,'state':'NEEDED'}]}
 progress=caregiver_progress(s)
 assert expected in progress['status'] and progress['stage']==1
 assert 'is checking' not in progress['next_action']


def test_verified_reconciliation_does_not_treat_balance_pending_as_clearance():
 s=snapshot();s['complex_workflow']={'clearance':{'envelope':{'discharge_clearance':'BALANCE_PENDING'}}}
 assert caregiver_progress(s)['stage']==2
 assert 'outstanding' in caregiver_progress(s)['status']
 s['complex_workflow']['clearance']['envelope']['discharge_clearance']='ISSUED'
 assert caregiver_progress(s)['stage']==3
 assert 'administrative clearance confirmed' in caregiver_progress(s)['status']


def test_hold_or_revocation_does_not_display_old_verified_outcome_as_current_action():
 s=snapshot();s['complex_workflow']={'clearance':{'envelope':{'discharge_clearance':'ISSUED'}}}
 s['incident']['consent_active']=False
 assert caregiver_progress(s)['status']=='Permission needed'
 s['incident']['state']='HUMAN_REVIEW'
 assert 'coordinator' in caregiver_progress(s)['status']
 assert 'hold' in caregiver_progress(s)['next_action']
