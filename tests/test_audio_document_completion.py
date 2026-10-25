from sandbox.audio_transport import document_report_complete
from sandbox.audio_transport import institution_report_complete
from sandbox.audio_transport import caregiver_intake_reply,caregiver_handoff_reply
from sandbox.scripted_desks import ScriptedDesk


def test_caregiver_can_answer_language_clarification_without_granting_disclosure():
 assert caregiver_intake_reply([{'role':'user','content':'What is your preferred language for updates?'}])=='English is fine, thank you.'
 assert 'investigate' in caregiver_intake_reply([{'role':'user','content':'May I investigate the case?'}])
 assert 'which documents' in caregiver_intake_reply([{'role':'user','content':'May I share your documents with the TPA?'}])
 assert 'ready to leave' in caregiver_intake_reply([{'role':'user','content':'Have I understood your concern?'}])


def test_caregiver_handoff_answers_the_current_question():
 assert 'amount due separate' in caregiver_handoff_reply([{'role':'user','content':'Would you like me to explain whether the refund has been paid?'}])
 assert 'final bill' in caregiver_handoff_reply([{'role':'user','content':'Would it help to see the bill, insurer amount and patient share?'}])


def test_desk_replies_are_directly_about_the_latest_question_and_own_record():
 record={'patient_id':'DEMO-PATIENT-84','admission_id':'ADM42',
  'references':{'preauthorization':'PRE37','enhancement':'ENH18','final_request':'FIN63',
               'query':'QRY25','claim':'CLM86'},
  'received_at':'2026-10-23T10:20:00+05:30','required_documents':['itemized_bill_v2','signed_discharge_summary','implant_invoice'],
  'enhancement_linked':False,'query_state':'OPEN'}
 tpa=ScriptedDesk('tpa',record)
 assert tpa.reply([{'role':'user','content':'What is the query reference for this request?'}])=='The query reference is QRY25.'
 assert 'arrived on 23 October 2026 at 10:20 UTC +05:30' in tpa.reply([{'role':'user','content':'When did the original request arrive?'}])
 assert 'revised itemized bill' in tpa.reply([{'role':'user','content':'Which documents are still required?'}])
 assert 'not linked' in tpa.reply([{'role':'user','content':'Is the enhancement linked to the claim?'}])
 assert 'still open' in tpa.reply([{'role':'user','content':'Has the outstanding query been answered?'}])
 hospital=ScriptedDesk('hospital_insurance',record)
 assert 'claims desk has to verify its own receipt' in hospital.reply([{'role':'user','content':'Did the final packet reach the claims desk?'}])


def test_followup_requires_verified_evidence_and_report_after_owning_desk_action():
 pending=[{'tool':'claim911_report_update'}]
 assert not institution_report_complete(pending,{},'query_resolution')
 assert not institution_report_complete(pending,{'query_resolution':{'verified':True}},'query_resolution',1)
 assert institution_report_complete(pending+[{'tool':'claim911_report_update'}],{'query_resolution':{'verified':True}},'query_resolution',1)


def test_unavailable_report_ends_conversation_but_ready_without_evidence_does_not():
 def report(ready,result):
  return [{'tool':'claim911_report_document','arguments':{'ready':ready},'result':{'reported_document_result':result}}]
 assert document_report_complete(report(False,'REPORTED_UNAVAILABLE'))
 assert not document_report_complete(report(False,'REPORTED_UNAVAILABLE'),requires_release=True)
 assert not document_report_complete(report(True,'AWAITING_UPLOADED_PROOF'))
 assert not document_report_complete(report(True,'REFERENCE_CONFIRMATION_REQUIRED'))
 assert document_report_complete(report(True,'UPLOADED_DOCUMENT_CHECKED'))
 assert document_report_complete(report(True,'UPLOADED_DOCUMENT_CHECKED'),requires_release=True)
