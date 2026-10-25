from sandbox.dialogue_evidence import dialogue_facts


def test_a_report_or_upload_does_not_become_checked_evidence():
 record={'synthetic':True,'role':'billing'}
 facts=dialogue_facts(record,{'documents':[{'id':'uploaded-only'}],
  'complex_workflow':{'reports':[{'summary':'The insurer approved it.'}]}})
 assert facts['assistant_backend_results']['checked_and_linked_documents']==[]
 assert facts['assistant_backend_results']['decision_verified'] is False
 assert 'assistant_backend_results' not in record


def test_checked_document_result_supports_its_spoken_status_without_verifying_other_outcomes():
 facts=dialogue_facts({'synthetic':True,'role':'billing'},{'complex_workflow':{
  'documents':{'itemized_bill':{'record':{'id':'bill-v2','kind':'itemized_bill','revision':2,'ready':True}}}}})
 outcome=facts['assistant_backend_results']
 assert outcome['checked_and_linked_documents'][0]['id']=='bill-v2'
 assert outcome['recipient_receipt_verified'] is False
 assert outcome['decision_verified'] is False
