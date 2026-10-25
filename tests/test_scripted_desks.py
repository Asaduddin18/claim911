from sandbox.scripted_desks import ScriptedDesk


def desk():
 return ScriptedDesk('hospital_insurance',{'patient_id':'DEMO-PATIENT-84','admission_id':'ADM-SYN-1','references':{'preauthorization':'PA-SYN-1','enhancement':'ENH-SYN-1','final_request':'FINAL-SYN-1'}})


def ask(actor,text):return actor.reply([{'role':'user','content':text}])


def test_caregiver_investigation_offer_is_answered_without_exposing_hidden_facts():
 actor=ScriptedDesk('caregiver',{})
 for question in ('Would you like me to find out the specific reason from the hospital?',
                  'May I investigate the clearance hold?', 'Should I look into the reason?'):
  answer=ask(actor,question)
  assert answer.startswith('Yes, please check') and 'do not know' in answer


def test_scripted_desk_cannot_invent_claims_fields_or_confirm_foreign_reference():
 actor=desk()
 assert 'CLM' not in ask(actor,'What is the claim reference?')
 assert 'differs' in ask(actor,'Is FINAL-SYN-999 correct?')
 assert 'correct' in ask(actor,'Is FINAL-SYN-1 correct?')


def test_readback_prefix_does_not_hide_the_next_requested_field():
 answer=ask(desk(),'You provided ADM-SYN-1. What is the initial reference?')
 assert 'PA-SYN-1' in answer and 'ADM-SYN-1' not in answer
 answer=ask(desk(),'The initial approval reference is recorded. What is the enhancement reference?')
 assert 'ENH-SYN-1' in answer and 'one identifier' not in answer
 assert 'correct reference' in ask(desk(),'Initial PA-SYN-1, enhancement ENH-SYN-1, final FINAL-SYN-1. Is that correct?')


def test_multiple_reference_request_requires_clarification_instead_of_long_audio():
 assert 'one identifier' in ask(desk(),'Give the initial, enhancement and final references.')
 assert 'one identifier' in ask(desk(),'What are the initial and final references?')


def test_enhancement_request_reference_is_the_same_scoped_identifier():
 for question in ('Thanks. Now can you provide the enhancement request reference for this admission?',
                  'What is the enhancement request number?'):
  assert 'ENH-SYN-1' in ask(desk(),question)


def test_spoken_requests_work_with_question_or_declarative_punctuation():
 for question in ['Please provide the admission ID for DEMO-PATIENT-84.',
                  'Please confirm the admission ID for DEMO-PATIENT-84?',
                  'You provided PA-SYN-1. What is the enhancement reference?',
                  'Please give the final request reference.']:
  assert any(value in ask(desk(),question) for value in ['ADM-SYN-1','ENH-SYN-1','FINAL-SYN-1'])


def test_claims_desk_answers_query_status_instead_of_repeating_final_reference():
 actor=ScriptedDesk('tpa',{'patient_id':'DEMO-PATIENT-84','admission_id':'ADM-SYN-1','references':{'query':'IR-SYN-1','claim':'CLM-SYN-1','final_request':'FINAL-SYN-1','enhancement':'ENH-SYN-1'},'received_at':'2026-10-23T10:20:00+05:30','query_state':'OPEN','enhancement_linked':False})
 answer=ask(actor,'Is there an outstanding information request for FINAL-SYN-1?')
 assert 'outstanding' in answer and 'not linked' in answer
 assert 'open' in ask(actor,'Is query IR-SYN-1 already closed?')


def test_role_specific_synthetic_participants_answer_from_only_their_desk_record():
 billing=ScriptedDesk('billing',{'documents':[{'kind':'itemized_bill','ready':True,'revision':2,'amount_inr':248000}],'deposit_inr':30000})
 records=ScriptedDesk('medical_records',{'documents':[{'kind':'signed_discharge_summary','ready':False}]})
 implant=ScriptedDesk('implant_store',{'documents':[{'kind':'implant_invoice','ready':True}]})
 insurer=ScriptedDesk('insurer',{'decision':None})
 caregiver=ScriptedDesk('caregiver',{})
 assert 'INR 248,000' in ask(billing,'What is the current itemized bill total?')
 assert 'deposit' in ask(billing,'Was a deposit paid?')
 assert 'waiting for the treating team' in ask(records,'Is the discharge summary signed?')
 assert 'invoice is available' in ask(implant,'Can you provide the implant invoice?')
 assert 'not issued a final decision' in ask(insurer,'Has the insurer approved the final request?')
 assert 'ready to leave' in ask(caregiver,'What is holding things up?')
 answer=ask(caregiver,'Has the hospital mentioned any documents or information they are waiting for?')
 assert 'not told us what is missing' in answer and 'check with the hospital and insurer' in answer
 assert answer.count('.') == 1 and '?' not in answer


def test_caregiver_answers_directly_and_does_not_ask_claim911_to_repeat_or_transfer_the_question():
 caregiver=ScriptedDesk('caregiver',{})
 assert 'please check with them for us' in ask(caregiver,'Would you like me to ask the hospital?')
 assert 'That is right' in ask(caregiver,'Thanks for clarifying.')
 consent=ask(caregiver,'Do you consent to the synthetic investigation?')
 assert 'agree to investigate' in consent and consent.count('.') == 1 and '?' not in consent
 assert 'agree to investigate' in ask(caregiver,'May I confirm this synthetic demonstration call and that you agree to proceed?')


def test_role_bounded_participant_refuses_to_invent_unknown_owner_facts():
 billing=ScriptedDesk('billing',{'documents':[]})
 records=ScriptedDesk('medical_records',{'documents':[]})
 insurer=ScriptedDesk('insurer',{'decision':None})
 assert 'cannot confirm a revised bill' in ask(billing,'What is the corrected bill total?')
 assert 'waiting for the treating team' in ask(records,'Is the discharge summary signed?')
 assert 'not issued a final decision' in ask(insurer,'Is insurance approved?')


def test_hospital_distinguishes_its_own_submission_record_from_claims_receipt():
 actor=ScriptedDesk('hospital_insurance',{'dispatches':[]})
 assert 'has not been submitted yet' in ask(actor,'Was the final response packet submitted?')
 assert 'claims desk has to verify' in ask(actor,'Did the packet reach the claims desk?')


def test_caregiver_answers_language_question_and_clarifies_unknown_question():
 actor=ScriptedDesk('caregiver',{})
 assert ask(actor,'Which language do you prefer?')=='English, please.'
 assert 'agree' not in ask(actor,'Which language do you prefer?')
 assert 'Could you ask that again?' in ask(actor,'Please explain your employer benefit code.')


def test_claims_answers_current_state_instead_of_a_hardcoded_initial_state():
 actor=ScriptedDesk('tpa',{'query_state':'ANSWERED','enhancement_linked':True})
 assert 'has been answered' in ask(actor,'Is the query still outstanding?')
 assert 'Yes.' in ask(actor,'Is the enhancement linked to the claim?')
 unknown=ScriptedDesk('tpa',{})
 assert 'cannot confirm' in ask(unknown,'Is the query closed?')


def test_each_document_owner_reports_exact_reference_revision_and_readback():
 for role,kind,reference in [('billing','itemized_bill','bill-v2'),('medical_records','signed_discharge_summary','summary-signed'),('implant_store','implant_invoice','implant-invoice')]:
  actor=ScriptedDesk(role,{'documents':[{'kind':kind,'id':reference,'revision':2,'ready':True}]})
  answer=ask(actor,'What is the exact document identifier and revision?')
  assert reference in answer and 'revision 2' in answer
  assert 'differs' in ask(actor,'Is document reference WRONG-DOC-999 correct?')
  assert reference in ask(actor,f'Can you confirm the document reference {reference}?')


def test_document_query_uses_only_the_current_required_list():
 actor=ScriptedDesk('tpa',{'query_state':'OPEN','required_documents':['signed_discharge_summary']})
 assert ask(actor,'Which documents do you need?')=='We still need signed discharge summary.'
 assert 'cannot confirm' in ask(ScriptedDesk('tpa',{}),'Which documents do you need?')


def test_final_caregiver_can_receive_the_three_short_handoff_sections():
 actor=ScriptedDesk('caregiver',{'verified_update':{'synthetic':True}})
 assert ask(actor,'May I continue?')=='Yes, please continue.'
 assert ask(actor,'Would you like me to continue with the financial details?')=='Yes, please continue.'
 answer=ask(actor,'Do you have any questions or need human help?')
 assert 'No more questions' in answer and 'summary in the app' in answer
