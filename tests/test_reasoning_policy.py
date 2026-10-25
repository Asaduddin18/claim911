from copy import deepcopy
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from coordinator.reasoning import propose,evaluate,decision_view


def case():
 return {'incident':{'id':str(uuid4()),'state':'INVESTIGATING','reference':'UNCONFIRMED_FINAL_REFERENCE',
                     'consent_active':True,'consent_version':1},'documents':[],'events':[],'calls':[], 'complex_workflow':None}


def test_stale_or_forged_proposal_cannot_skip_workflow_gate():
 snapshot=case();proposal=propose(snapshot)[0]
 assert evaluate(proposal,snapshot).state=='permitted'
 assert not evaluate(proposal,snapshot).dispatch_authorized
 forged=proposal.model_copy(update={'action':'request_submission','desk':'hospital_insurance','purpose':'PACKET_SUBMISSION'})
 assert evaluate(forged,snapshot).state=='blocked'
 changed=deepcopy(snapshot);changed['documents'].append({'id':str(uuid4()),'filename':'revised-bill.json'})
 assert evaluate(proposal,changed).state=='blocked'
 changed=deepcopy(snapshot);changed['incident']['consent_active']=False
 assert evaluate(proposal,changed).state=='blocked'
 forged=proposal.model_copy(update={'evidence_references':['document:'+str(uuid4())]})
 assert evaluate(forged,snapshot).state=='blocked'


def test_reported_dispatch_does_not_become_verified_receipt_or_insurer_decision():
 snapshot=case();snapshot['complex_workflow']={'tasks':[],'approval_current':True,
  'reports':[{'purpose':'PACKET_SUBMISSION','details':{'dispatch_reference':'SYN-DISPATCH'}}]}
 p=propose(snapshot)[0]
 assert p.action=='verify_receipt' and p.desk=='tpa'
 assert p.expected_checkpoint=='recipient_receipt_verified'
 snapshot['complex_workflow']['receipt']={'verified':True}
 assert propose(snapshot)[0].action=='verify_query'
 snapshot['complex_workflow']['query_resolution']={'verified':True}
 assert propose(snapshot)[0].action=='verify_decision'
 assert decision_view(snapshot)['engine']=='deterministic_baseline'


def test_consent_approval_and_expired_context_require_explicit_controls():
 snapshot=case();snapshot['incident']['consent_active']=False
 p=propose(snapshot)[0]
 assert p.action=='request_permission' and evaluate(p,snapshot).state=='approval_required'
 snapshot['incident']['consent_active']=True
 snapshot['complex_workflow']={'tasks':[],'approval_current':False}
 p=propose(snapshot)[0]
 assert p.purpose=='EXACT_PACKET_APPROVAL' and evaluate(p,snapshot).state=='approval_required'
 for timestamp in (datetime.now(timezone.utc)-timedelta(minutes=6),datetime.now(timezone.utc)+timedelta(seconds=5),datetime.now()):
  assert evaluate(p.model_copy(update={'created_at':timestamp}),snapshot).state=='blocked'


def test_three_document_owners_remain_separate_and_no_payment_claim_is_created():
 snapshot=case();snapshot['complex_workflow']={'tasks':[
  {'kind':'itemized_bill','owner':'billing','state':'NEEDED'},
  {'kind':'signed_discharge_summary','owner':'medical_records','state':'NEEDED'},
  {'kind':'implant_invoice','owner':'implant_store','state':'NEEDED'}]}
 proposals=propose(snapshot)
 assert {p.desk for p in proposals}=={'billing','medical_records','implant_store'}
 snapshot['complex_workflow']={'tasks':[],'approval_current':True,'receipt':{},'query_resolution':{},'decision':{},'clearance':{}}
 # Empty objects are not verification evidence.
 assert propose(snapshot)[0].action=='request_submission'
 snapshot['complex_workflow'].update(receipt={'id':'synthetic'},query_resolution={'id':'synthetic'},decision={'id':'synthetic'},clearance={'id':'synthetic'})
 p=propose(snapshot)[0]
 assert p.action=='handoff' and 'refund payment' in p.summary
