from uuid import uuid4
import json
from tests.test_native_sandbox_calls import sandbox_core


def test_uploaded_reference_candidates_are_case_bound_and_do_not_become_reported_facts(sandbox_core):
 core,_,id=sandbox_core;i=core.get('/v1/incidents/'+id).json()['incident']
 slip={'kind':'hospital_reference_slip','case_id':str(i['case_id']),'patient_id':i['patient_id'],'admission_id':'ADM-SYN-1',
  'references':{'preauthorization':'PA-SYN-1','enhancement':'ENH-SYN-1','final_request':'FINAL-SYN-1'},'private_key':'must-never-enter-model-context'}
 def upload(value):core.post(f'/v1/incidents/{id}/documents',files={'file':('reference-slip.json',json.dumps(value).encode(),'application/json')},data={'kind':'other'})
 upload(slip|{'case_id':str(uuid4())})
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).json();headers={'X-Call-Token':call['call_token']}
 assert not core.get('/v1/tools/context',headers=headers).json()['uploaded_reference_candidates']
 upload(slip);context=core.get('/v1/tools/context',headers=headers).json();candidate=context['uploaded_reference_candidates'][0]
 assert candidate['support_status']=='UPLOADED_UNVERIFIED' and 'confirmation' in candidate['instruction']
 assert 'private_key' not in json.dumps(context) and context['reference']=='UNCONFIRMED_FINAL_REFERENCE'
 assert core.get('/v1/incidents/'+id).json().get('reference_discovery') is None


def test_bolna_context_carries_the_same_candidate_confirmation_policy(sandbox_core):
 core,_,id=sandbox_core;i=core.get('/v1/incidents/'+id).json()['incident']
 slip={'kind':'hospital_reference_slip','case_id':str(i['case_id']),'patient_id':i['patient_id'],
       'admission_id':'ADM-SYN-1','references':{'preauthorization':'PA-SYN-1','enhancement':'ENH-SYN-1','final_request':'FINAL-SYN-1'}}
 core.post(f'/v1/incidents/{id}/documents',files={'file':('reference-slip.json',json.dumps(slip).encode(),'application/json')},data={'kind':'other'})
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).json()
 context=core.get('/v1/tools/context',headers={'X-Call-Token':call['call_token']}).json()
 assert 'ONE canonical candidate at a time' in context['instructions']
 assert 'An upload alone is not confirmation' in context['instructions']
 assert 'Do not recap all four together' in context['objective']
 assert core.get('/v1/incidents/'+id).json().get('reference_discovery') is None


def test_hospital_spoken_reference_preserves_internal_id_and_rejects_bad_alias():
 import pytest
 from coordinator.reference_evidence import hospital_dispatch_reference
 internal=str(uuid4())
 assert hospital_dispatch_reference({'id':internal,'submission_reference':'HSP01'})=='HSP01'
 assert hospital_dispatch_reference({'id':internal})==internal
 with pytest.raises(ValueError):hospital_dispatch_reference({'id':internal,'submission_reference':'HSP-01'})


def test_hospital_report_blocks_invented_candidate_without_changing_reference(sandbox_core):
 core,_,id=sandbox_core;i=core.get('/v1/incidents/'+id).json()['incident']
 slip={'kind':'hospital_reference_slip','case_id':str(i['case_id']),'patient_id':i['patient_id'],
       'admission_id':'ADM42','references':{'preauthorization':'INITIAL-123','enhancement':'ENH18','final_request':'FIN63'}}
 core.post(f'/v1/incidents/{id}/documents',files={'file':('slip.json',json.dumps(slip).encode(),'application/json')},data={'kind':'other'})
 call=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'HOSPITAL_REFERENCE_DISCOVERY'}).json()
 h={'X-Call-Token':call['call_token']};core.get('/v1/tools/context',headers=h)
 report={'admission_id':'ADM42','initial_reference':'INITIAL123','enhancement_reference':'ENH18',
         'final_reference':'FIN63','submission_status':'UNKNOWN','summary':'Staff readback for synthetic case.'}
 bad=core.post('/v1/tools/references',headers=h,json=report)
 assert bad.status_code==422 and bad.json()['detail']['fields']==['initial_reference']
 assert core.get('/v1/incidents/'+id).json()['incident']['reference']=='UNCONFIRMED_FINAL_REFERENCE'
 report['initial_reference']='INITIAL-123'
 good=core.post('/v1/tools/references',headers=h,json=report)
 assert good.status_code==200 and good.json()['call_complete']
 again=core.post('/v1/tools/references',headers=h,json=report)
 # A changed context must be refreshed even for a duplicate report.
 if again.status_code==409:
  core.get('/v1/tools/context',headers=h);again=core.post('/v1/tools/references',headers=h,json=report)
 assert again.status_code==200 and again.json()['call_complete']


def test_reference_comparison_preserves_fields_and_whole_slip():
 from coordinator.reference_evidence import candidate_report_conflicts
 a={'claim':'CLM86','final':'FIN63'}
 assert candidate_report_conflicts({'claim':'FIN63','final':'FIN63'},[a])==['claim']
 assert candidate_report_conflicts(a,[a])==[]
 assert candidate_report_conflicts(a,[])==[]
 assert candidate_report_conflicts({'claim':'CLM86','final':'FIN64'},[a,{'claim':'CLM87','final':'FIN64'}])
