"""Give conversation evaluation the actual scoped backend outcomes it needs.

Reports and uploads do not become verified facts here. Only the coordinator's
already checked document map and independently verified outcome fields are
summarized. The independent checkpoint verifier remains the final authority.
"""
from copy import deepcopy


def dialogue_facts(record,snapshot,operations=()):
 facts=deepcopy(record);w=snapshot.get('complex_workflow') or {}
 checked=[]
 for item in w.get('documents',{}).values():
  document=item.get('record') or {}
  checked.append({k:document[k] for k in ('id','kind','revision','ready','signed_by') if k in document})
 evidence={'source':'CURRENT_COORDINATOR_VERIFICATION_RESULTS','checked_and_linked_documents':checked,
  'recipient_receipt_verified':bool(w.get('receipt')),
  'query_resolution_verified':bool(w.get('query_resolution')),
  'decision_verified':bool(w.get('decision')),'hospital_reconciliation_verified':bool(w.get('clearance'))}
 for key in ('query_resolution','decision','clearance'):
  value=w.get(key) or {}
  if value.get('envelope'):
   evidence[key]={k:v for k,v in value['envelope'].items()
    if isinstance(v,(str,bool,int,float,type(None))) and k not in
    {'case_id','patient_id','packet_hash','consent_version'} and (not isinstance(v,str) or len(v)<=200)}
 facts['assistant_backend_results']=evidence
 if operations:facts['authorized_institution_action_results']=list(operations)
 return facts
